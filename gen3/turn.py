"""
Gen 3 Turn Resolver
====================
Handles simultaneous move selection, speed-based ordering, and the full
turn sequence for 3v3 singles.

Turn sequence:
  1. Both players choose actions simultaneously
  2. Switches resolve first (priority +6)
  3. Moves resolve in priority/speed order
  4. End-of-turn effects
  5. Faint check → forced switch if needed
"""

import math
import random
from dataclasses import replace
from typing import List, Tuple, Optional
from .state import BattleState, Pokemon, FieldSide, EMPTY_FIELD
from .moves import get_move, MoveDef
from .executor import (
    execute_single_move, apply_end_of_turn, get_legal_actions,
    apply_damage_rolls, apply_secondary_effect, execute_status_move,
    _check_lum_berry, _check_chesto_berry,
    Dist, CRIT_RATE, PARA_SKIP, FREEZE_THAW,
)
from .damage import apply_stage

CONF_SELF_HIT = 0.5  # 50% confusion self-hit chance

# Type alias
Action = Tuple[str, str]  # ("move", move_name) or ("switch", idx)


# ============================================================
# Switch execution
# ============================================================

def execute_switch(state: BattleState, player: str,
                   target_idx: int) -> BattleState:
    """
    Switch the active Pokemon. Handles:
    - Natural Cure (cure status on switch out)
    - Clear volatiles on the outgoing mon
    - Update active index
    - Switch-in effects (Spikes, Sand Stream, Intimidate)
    """
    team = list(state.get_team(player))
    old_idx = state.get_active_idx(player)
    old_mon = team[old_idx]

    # Natural Cure: cure status when switching out
    status_out = old_mon.status
    if old_mon.ability == "Natural Cure" and old_mon.status is not None:
        status_out = None

    # Clear volatiles on outgoing Pokemon
    cleared = replace(old_mon,
                      status=status_out, status_turns=0 if status_out is None else old_mon.status_turns,
                      atk_stage=0, def_stage=0, spa_stage=0,
                      spd_stage=0, spe_stage=0,
                      substitute_hp=0, taunt_turns=0,
                      confused=False, confused_turns=0,
                      flinched=False, last_move=None,
                      last_damage_taken=0, last_damage_physical=False,
                      protect_consecutive=0,
                      leech_seeded=False,
                      move_locked=None)  # Choice Band resets
    team[old_idx] = cleared

    # Update state with cleared mon and new active index
    if player == "p1":
        state = replace(state, team_p1=tuple(team), active_p1=target_idx)
    else:
        state = replace(state, team_p2=tuple(team), active_p2=target_idx)

    # Switch-in effects
    state = _apply_spikes_on_switch(state, player)
    state = _apply_entry_effects(state, player)

    return state


def _apply_entry_effects(state: BattleState, player: str) -> BattleState:
    """On-entry ability effects: Sand Stream, Intimidate."""
    mon = state.active(player)
    opp = state.opp(player)
    opp_mon = state.active(opp)

    # Sand Stream: set permanent sandstorm (weather_turns=10000 = indefinite)
    if mon.ability == "Sand Stream":
        state = replace(state, weather="sand", weather_turns=10000)

    # Drizzle: rain
    if mon.ability == "Drizzle":
        state = replace(state, weather="rain", weather_turns=10000)

    # Drought: sun
    if mon.ability == "Drought":
        state = replace(state, weather="sun", weather_turns=10000)

    # Intimidate: lower opponent's Atk by 1
    if mon.ability == "Intimidate" and opp_mon.alive():
        if opp_mon.ability not in ("Clear Body", "White Smoke", "Hyper Cutter"):
            new_stage = max(-6, opp_mon.atk_stage - 1)
            if new_stage != opp_mon.atk_stage:
                new_opp = replace(opp_mon, atk_stage=new_stage)
                state = state.set_active(opp, new_opp)

    return state


def _apply_spikes_on_switch(state: BattleState, player: str) -> BattleState:
    """Apply Spikes damage when switching in."""
    mon = state.active(player)
    field = state.field_p1 if player == "p1" else state.field_p2

    if field.spikes == 0:
        return state

    # Flying types and Levitate are immune to Spikes
    if "Flying" in (mon.types[0], mon.types[1]):
        return state
    if mon.ability == "Levitate":
        return state

    # Gen 3 Spikes damage: 1/8, 1/6, 1/4 of max HP
    if field.spikes == 1:
        dmg = max(1, mon.max_hp // 8)
    elif field.spikes == 2:
        dmg = max(1, mon.max_hp // 6)
    else:  # 3
        dmg = max(1, mon.max_hp // 4)

    new_hp = max(0, mon.current_hp - dmg)
    new_mon = replace(mon, current_hp=new_hp)
    return state.set_active(player, new_mon)


# ============================================================
# Confusion resolution
# ============================================================

def _resolve_confusion(state: BattleState, player: str) -> List[Tuple[float, BattleState, bool]]:
    """
    Handle one turn of confusion. Returns [(prob, state, can_act)].
    - Decrements confused_turns.
    - If turns reach 0: snap out, can act.
    - Otherwise: 50% self-hit (can't act), 50% snap through and act.
    """
    mon = state.active(player)
    new_turns = mon.confused_turns - 1

    if new_turns <= 0:
        # Snap out of confusion
        new_mon = replace(mon, confused=False, confused_turns=0)
        return [(1.0, state.set_active(player, new_mon), True)]

    # Still confused: update counter
    confused_mon = replace(mon, confused_turns=new_turns)
    s_still = state.set_active(player, confused_mon)

    # Compute confusion self-hit damage (40 BP typeless physical)
    # Formula: floor(floor(22 * 40 * Atk / Def) / 50) + 2
    atk = apply_stage(mon.base_atk, mon.atk_stage)
    if mon.status == "burn" and mon.ability != "Guts":
        atk = atk // 2
    def_ = max(1, apply_stage(mon.base_def, mon.def_stage))
    dmg = math.floor(math.floor(22 * 40 * atk / def_) / 50) + 2
    dmg = max(1, dmg)

    new_hp = max(0, confused_mon.current_hp - dmg)
    hit_mon = replace(confused_mon, current_hp=new_hp)
    s_hit = state.set_active(player, hit_mon)

    return [(CONF_SELF_HIT, s_hit, False), (1 - CONF_SELF_HIT, s_still, True)]


# ============================================================
# Status checks (paralysis, sleep, freeze)
# ============================================================

def check_can_move(state: BattleState, player: str
                   ) -> Dist:
    """
    Check if a Pokemon can move this turn.
    Handles paralysis (25% skip), sleep (counter), freeze (20% thaw).

    Returns [(prob, state, can_act)] — probability distribution with
    a boolean indicating whether the mon can act.
    """
    mon = state.active(player)
    results = []

    if mon.status == "paralyze":
        # 25% chance to be fully paralyzed
        results.append((PARA_SKIP, state, False))
        results.append((1 - PARA_SKIP, state, True))

    elif mon.status == "sleep":
        if mon.status_turns > 0:
            # Still asleep — decrement counter
            new_mon = replace(mon, status_turns=mon.status_turns - 1)
            s = state.set_active(player, new_mon)
            # Check if waking up THIS turn
            if mon.status_turns == 1:
                # Wake up: can act
                woke_mon = replace(new_mon, status=None, status_turns=0)
                s_wake = state.set_active(player, woke_mon)
                results.append((1.0, s_wake, True))
            else:
                results.append((1.0, s, False))
        else:
            # status_turns == 0 means waking up
            new_mon = replace(mon, status=None, status_turns=0)
            s = state.set_active(player, new_mon)
            results.append((1.0, s, True))

    elif mon.status == "freeze":
        # 20% chance to thaw each turn
        thaw_mon = replace(mon, status=None, status_turns=0)
        s_thaw = state.set_active(player, thaw_mon)
        results.append((FREEZE_THAW, s_thaw, True))
        results.append((1 - FREEZE_THAW, state, False))

    else:
        results.append((1.0, state, True))

    return results


# ============================================================
# Move order determination
# ============================================================

def determine_order(state: BattleState,
                    action_p1: Action, action_p2: Action,
                    stochastic: bool = False
                    ) -> Tuple[str, str]:
    """
    Determine who goes first. Returns (first_player, second_player).

    Rules:
    1. Switches always go before moves (priority +6)
    2. Higher priority moves go first
    3. Same priority: faster Pokemon goes first
    4. Speed tie: random 50/50 when stochastic=True, p1 first otherwise
    """
    is_switch_p1 = action_p1[0] == "switch"
    is_switch_p2 = action_p2[0] == "switch"

    # Both switch: faster switches first (rarely matters)
    if is_switch_p1 and is_switch_p2:
        spd1 = state.active("p1").effective_speed()
        spd2 = state.active("p2").effective_speed()
        if spd1 == spd2:
            return ("p1", "p2") if (not stochastic or random.random() < 0.5) else ("p2", "p1")
        return ("p1", "p2") if spd1 > spd2 else ("p2", "p1")

    # One switches, one moves
    if is_switch_p1 and not is_switch_p2:
        return ("p1", "p2")
    if is_switch_p2 and not is_switch_p1:
        return ("p2", "p1")

    # Both use moves: compare priority
    move1 = get_move(action_p1[1])
    move2 = get_move(action_p2[1])

    if move1.priority > move2.priority:
        return ("p1", "p2")
    elif move2.priority > move1.priority:
        return ("p2", "p1")

    # Same priority: speed check
    spd1 = state.active("p1").effective_speed()
    spd2 = state.active("p2").effective_speed()

    if spd1 > spd2:
        return ("p1", "p2")
    elif spd2 > spd1:
        return ("p2", "p1")

    # Speed tie: random if stochastic, else p1 first
    if stochastic:
        return ("p1", "p2") if random.random() < 0.5 else ("p2", "p1")
    return ("p1", "p2")


def _is_speed_tie(state: BattleState,
                  action_p1: Action, action_p2: Action) -> bool:
    """Return True if the two actions result in a speed tie."""
    is_switch_p1 = action_p1[0] == "switch"
    is_switch_p2 = action_p2[0] == "switch"
    if is_switch_p1 != is_switch_p2:
        return False  # Switch always beats move, no tie possible
    if is_switch_p1 and is_switch_p2:
        spd1 = state.active("p1").effective_speed()
        spd2 = state.active("p2").effective_speed()
        return spd1 == spd2
    # Both using moves: must have same priority and same speed
    move1 = get_move(action_p1[1])
    move2 = get_move(action_p2[1])
    if move1.priority != move2.priority:
        return False
    spd1 = state.active("p1").effective_speed()
    spd2 = state.active("p2").effective_speed()
    return spd1 == spd2


# ============================================================
# Execute one player's action within a turn
# ============================================================

def execute_player_action(state: BattleState, player: str,
                          action: Action, was_hit: bool = False
                          ) -> Dist:
    """
    Execute a single player's action. Handles:
    - Switch actions
    - Status checks (para/sleep/freeze)
    - Focus Punch interruption
    - Move execution

    Args:
        was_hit: True if this player's active mon was directly hit
                 this turn (before substitute). Used for Focus Punch.

    Returns probability distribution over states.
    """
    mon = state.active(player)

    # Dead mons can't act
    if not mon.alive():
        return [(1.0, state)]

    # --- Switch ---
    if action[0] == "switch":
        new_state = execute_switch(state, player, action[1])
        return [(1.0, new_state)]

    # --- Move ---
    move_name = action[1]
    move = get_move(move_name)

    # Taunt check: if taunted and status move, fail
    # (This is also in get_legal_actions, but needed here for
    #  moves chosen before Taunt landed this turn)
    if mon.taunt_turns > 0 and move.base_power == 0:
        if move.effect not in ("counter",):
            return [(1.0, state)]

    # Focus Punch: fails if user was hit this turn
    if move.effect == "focus_punch" and was_hit:
        if mon.substitute_hp == 0:
            return [(1.0, state)]

    # Flinch check
    if mon.flinched:
        return [(1.0, state)]

    # Status checks (para skip, sleep, freeze)
    status_outcomes = check_can_move(state, player)
    results = []

    for p_status, s_after_status, can_act in status_outcomes:
        if not can_act:
            # Sleep Talk exception: can still act while asleep
            sleeping = s_after_status.active(player).status == "sleep"
            if not (sleeping and move_name == "Sleep Talk"):
                results.append((p_status, s_after_status))
                continue

        # Confusion check (applied when mon can otherwise act)
        mon_c = s_after_status.active(player)
        if mon_c.confused:
            conf_outcomes = _resolve_confusion(s_after_status, player)
        else:
            conf_outcomes = [(1.0, s_after_status, True)]

        for p_conf, s_conf, can_act_conf in conf_outcomes:
            if not can_act_conf:
                results.append((p_status * p_conf, s_conf))
                continue
            # Execute the move
            move_results = execute_single_move(s_conf, player, move)
            for p_move, s_move in move_results:
                # Choice Band lock rule:
                # only lock when this branch actually recorded the move as used.
                # Pure miss branches keep last_move unchanged (see executor.py).
                if s_move.active(player).last_move == move.name:
                    s_move = _apply_choice_lock(s_move, player, action)
                results.append((p_status * p_conf * p_move, s_move))

    return results


# ============================================================
# Full turn resolution (simultaneous moves)
# ============================================================

def _resolve_ordered(state: BattleState,
                     action_p1: Action, action_p2: Action,
                     first_pl: str, second_pl: str) -> Dist:
    """Execute one turn with a fixed move order. Choice Band lock is applied
    inside execute_player_action only when the move actually fires."""
    first_action = action_p1 if first_pl == "p1" else action_p2
    second_action = action_p2 if first_pl == "p1" else action_p1

    first_move = (get_move(first_action[1])
                  if first_action[0] == "move" else None)

    # Can the first move flinch?
    can_flinch = (first_move and first_move.effect == "flinch"
                  and first_move.effect_chance > 0)
    flinch_rate = first_move.effect_chance / 100 if can_flinch else 0

    final_results: Dist = []

    # --- First player acts ---
    first_results = execute_player_action(state, first_pl, first_action)

    for p1, s1 in first_results:
        second_mon = s1.active(second_pl)

        # If second player's mon fainted, skip their action
        if not second_mon.alive():
            s1 = apply_end_of_turn(s1)
            final_results.append((p1, s1))
            continue

        # Did the first move directly hit the second player?
        second_was_hit = _was_directly_hit(state, s1, second_pl)

        # Flinch branching
        if can_flinch and second_was_hit and second_action[0] == "move":
            for p_flinch, flinched in [(flinch_rate, True),
                                       (1 - flinch_rate, False)]:
                if flinched:
                    flinched_mon = replace(s1.active(second_pl), flinched=True)
                    s_f = s1.set_active(second_pl, flinched_mon)
                    s_f = apply_end_of_turn(s_f)
                    final_results.append((p1 * p_flinch, s_f))
                else:
                    second_results = execute_player_action(
                        s1, second_pl, second_action,
                        was_hit=second_was_hit
                    )
                    for p2, s2 in second_results:
                        s2 = apply_end_of_turn(s2)
                        final_results.append((p1 * p_flinch * p2, s2))
        else:
            # No flinch possible — second player acts normally
            second_results = execute_player_action(
                s1, second_pl, second_action,
                was_hit=second_was_hit
            )
            for p2, s2 in second_results:
                s2 = apply_end_of_turn(s2)
                final_results.append((p1 * p2, s2))

    return final_results


def resolve_turn(state: BattleState,
                 action_p1: Action, action_p2: Action) -> Dist:
    """
    Resolve one full turn with simultaneous action selection.

    Sequence:
    1. Determine order (switches first, then priority, then speed)
    2. First player acts
    3. Second player acts (if alive and not flinched)
    4. End-of-turn effects
    5. Choice Band lock applied only when move actually executes

    Speed ties are branched 50/50 for correct game-theoretic evaluation.
    Returns probability distribution over resulting states.
    """
    if _is_speed_tie(state, action_p1, action_p2):
        # Branch both orderings with equal probability
        r1 = _resolve_ordered(state, action_p1, action_p2, "p1", "p2")
        r2 = _resolve_ordered(state, action_p1, action_p2, "p2", "p1")
        combined = [(0.5 * p, s) for p, s in r1] + [(0.5 * p, s) for p, s in r2]
        return _merge_outcomes(combined)

    first_pl, second_pl = determine_order(state, action_p1, action_p2)
    return _merge_outcomes(_resolve_ordered(state, action_p1, action_p2,
                                            first_pl, second_pl))


def _was_directly_hit(old_state: BattleState,
                      new_state: BattleState,
                      player: str) -> bool:
    """Check if a player's mon was directly hit (not through sub)."""
    old_mon = old_state.active(player)
    new_mon = new_state.active(player)
    # HP decreased and no substitute was broken
    if new_mon.current_hp < old_mon.current_hp:
        return True
    # Check via damage tracking
    if new_mon.last_damage_taken > 0:
        return True
    return False


def _apply_choice_lock(state: BattleState, player: str,
                       action: Action) -> BattleState:
    """Lock Choice Band user into the move they used."""
    if action[0] != "move":
        return state
    mon = state.active(player)
    if mon.item in ("Choice Band", "Choice Specs") and not mon.item_consumed:
        if mon.move_locked is None and mon.alive():
            new_mon = replace(mon, move_locked=action[1])
            return state.set_active(player, new_mon)
    return state


def _merge_outcomes(outcomes: Dist) -> Dist:
    """Merge identical states, summing probabilities."""
    merged = {}
    for prob, state in outcomes:
        if prob < 1e-12:
            continue
        if state in merged:
            merged[state] += prob
        else:
            merged[state] = prob
    return [(prob, state) for state, prob in merged.items()]


# ============================================================
# Fast stochastic turn simulator (for MC rollouts)
# ============================================================

def simulate_turn_fast(state: BattleState,
                       action_p1: Action, action_p2: Action
                       ) -> BattleState:
    """
    Simulate one turn with random dice rolls. No probability branching.
    Much faster than resolve_turn — used for MC rollouts.
    """
    first_pl, second_pl = determine_order(state, action_p1, action_p2,
                                          stochastic=True)
    first_action = action_p1 if first_pl == "p1" else action_p2
    second_action = action_p2 if first_pl == "p1" else action_p1

    s = state
    second_was_hit = False

    # --- First player ---
    s, acted = _sim_player_action(s, first_pl, first_action, was_hit=False)

    if acted:
        second_was_hit = _was_directly_hit(state, s, second_pl)

        # Flinch check
        if first_action[0] == "move":
            fm = get_move(first_action[1])
            if (fm.effect == "flinch" and fm.effect_chance > 0
                    and second_was_hit and s.active(second_pl).alive()):
                if random.random() < fm.effect_chance / 100:
                    flinched = replace(s.active(second_pl), flinched=True)
                    s = s.set_active(second_pl, flinched)

    # --- Second player ---
    if s.active(second_pl).alive():
        s, _ = _sim_player_action(s, second_pl, second_action,
                                  was_hit=second_was_hit)

    # End of turn
    s = apply_end_of_turn(s)

    return s


def _sim_player_action(state: BattleState, player: str,
                       action: Action, was_hit: bool
                       ) -> Tuple[BattleState, bool]:
    """
    Simulate one player's action with random rolls.
    Returns (new_state, did_act).
    """
    mon = state.active(player)
    if not mon.alive():
        return state, False

    # Switch
    if action[0] == "switch":
        return execute_switch(state, player, action[1]), True

    move_name = action[1]
    move = get_move(move_name)

    # Taunt check
    if mon.taunt_turns > 0 and move.base_power == 0:
        if move.effect not in ("counter",):
            return state, False

    # Focus Punch check
    if move.effect == "focus_punch" and was_hit and mon.substitute_hp == 0:
        return state, False

    # Flinch check
    if mon.flinched:
        return state, False

    # Status checks
    if mon.status == "paralyze" and random.random() < PARA_SKIP:
        return state, False
    if mon.status == "freeze":
        if random.random() < FREEZE_THAW:
            mon = replace(mon, status=None, status_turns=0)
            state = state.set_active(player, mon)
        else:
            return state, False
    if mon.status == "sleep":
        if mon.status_turns > 1:
            new_mon = replace(mon, status_turns=mon.status_turns - 1)
            state = state.set_active(player, new_mon)
            if move_name != "Sleep Talk":
                return state, False
        elif mon.status_turns == 1:
            new_mon = replace(mon, status=None, status_turns=0)
            state = state.set_active(player, new_mon)
        else:
            new_mon = replace(mon, status=None, status_turns=0)
            state = state.set_active(player, new_mon)

    # Confusion check
    mon = state.active(player)
    if mon.confused:
        new_turns = mon.confused_turns - 1
        if new_turns <= 0:
            mon = replace(mon, confused=False, confused_turns=0)
            state = state.set_active(player, mon)
        else:
            confused_mon = replace(mon, confused_turns=new_turns)
            if random.random() < CONF_SELF_HIT:
                # Self-hit
                atk = apply_stage(mon.base_atk, mon.atk_stage)
                if mon.status == "burn" and mon.ability != "Guts":
                    atk = atk // 2
                def_ = max(1, apply_stage(mon.base_def, mon.def_stage))
                dmg = math.floor(math.floor(22 * 40 * atk / def_) / 50) + 2
                dmg = max(1, dmg)
                new_hp = max(0, confused_mon.current_hp - dmg)
                state = state.set_active(player, replace(confused_mon, current_hp=new_hp))
                return state, False
            else:
                state = state.set_active(player, confused_mon)
                mon = confused_mon

    # Execute move via sampling from the distribution
    results = execute_single_move(state, player, move)
    if not results:
        return state, True

    # Sample one outcome
    r = random.random()
    cumulative = 0.0
    for prob, s in results:
        cumulative += prob
        if r <= cumulative:
            # Lock only on sampled branches that actually recorded the move.
            if s.active(player).last_move == move.name:
                s = _apply_choice_lock(s, player, action)
            return s, True
    s = results[-1][1]
    if s.active(player).last_move == move.name:
        s = _apply_choice_lock(s, player, action)
    return s, True


# ============================================================
# Rollout policy (smart random)
# ============================================================

def choose_rollout_action(state: BattleState, player: str) -> Action:
    """
    Choose an action for MC rollouts. Weighted toward good plays:
    - Super-effective moves get higher weight
    - Status moves on already-statused targets get low weight
    - Switches get baseline weight
    """
    from .types import type_effectiveness
    actions = get_legal_actions(state, player)
    if len(actions) == 1:
        return actions[0]

    mon = state.active(player)
    opp_mon = state.active(state.opp(player))
    weights = []

    for action in actions:
        if action[0] == "switch":
            weights.append(1.0)
            continue

        move = get_move(action[1])

        if move.base_power > 0:
            # Damaging move: weight by effectiveness
            eff = type_effectiveness(move.type,
                                     opp_mon.types[0], opp_mon.types[1])
            # Check Levitate
            if opp_mon.ability == "Levitate" and move.type == "Ground":
                eff = 0.0
            if eff == 0:
                weights.append(0.01)
            else:
                # Scale by power × effectiveness
                w = move.base_power * eff / 100
                # STAB bonus
                if move.type in mon.types:
                    w *= 1.3
                weights.append(max(0.1, w))
        else:
            # Status move
            if move.effect in ("paralyze_status", "burn_status", "toxic"):
                if opp_mon.status is not None:
                    weights.append(0.05)  # Already statused
                else:
                    weights.append(1.5)
            elif move.effect == "substitute":
                if mon.substitute_hp > 0 or mon.current_hp <= mon.max_hp // 4:
                    weights.append(0.05)
                else:
                    weights.append(1.0)
            elif move.effect == "rest":
                if mon.current_hp < mon.max_hp // 2:
                    weights.append(2.0)
                else:
                    weights.append(0.2)
            elif move.effect == "recover_half":
                if mon.current_hp < mon.max_hp * 2 // 3:
                    weights.append(2.0)
                else:
                    weights.append(0.1)
            elif move.effect in ("curse_normal", "atk_plus2_self",
                                 "atk_spe_plus1_self", "spa_spd_plus1_self",
                                 "spe_plus2_self", "spd_plus2_self"):
                weights.append(1.5)
            elif move.effect == "sleep_talk":
                if mon.status == "sleep":
                    weights.append(3.0)
                else:
                    weights.append(0.01)
            elif move.effect in ("sleep_status", "confuse_status"):
                if opp_mon.status is not None or opp_mon.confused:
                    weights.append(0.05)
                else:
                    weights.append(2.0)
            elif move.effect == "lay_spikes":
                weights.append(0.5)
            else:
                weights.append(0.8)

    # Normalize and sample
    total = sum(weights)
    if total == 0:
        return random.choice(actions)
    return random.choices(actions, weights=weights, k=1)[0]
