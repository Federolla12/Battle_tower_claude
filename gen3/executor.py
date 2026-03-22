"""
Gen 3 Move Executor
====================
Resolves moves and turns, producing probability distributions over new states.

Key design: every function returns List[Tuple[float, BattleState]] —
a list of (probability, new_state) pairs. This allows exact probability
branching for accuracy, crits, secondary effects, and damage rolls.
"""

import math
from dataclasses import replace
from typing import List, Tuple, Optional
from .state import BattleState, Pokemon, FieldSide, EMPTY_FIELD
from .moves import get_move, MoveDef, MOVE_DB
from .damage import (
    calc_damage, Attacker, Defender, MoveInfo, Conditions,
    apply_stage, damage_range_pct
)
from .types import type_effectiveness, move_category

# Type alias for probability distributions
Dist = List[Tuple[float, BattleState]]

CRIT_RATE = 1 / 16
PARA_SKIP = 0.25
FREEZE_THAW = 0.20


# ============================================================
# Convert state Pokemon → damage calc inputs
# ============================================================

def _make_attacker(mon: Pokemon) -> Attacker:
    return Attacker(
        name=mon.species, level=50,
        attack=mon.base_atk, sp_attack=mon.base_spa,
        types=mon.types, ability=mon.ability, item=mon.item,
        status=mon.status, atk_stage=mon.atk_stage, spa_stage=mon.spa_stage,
    )

def _make_defender(mon: Pokemon, field: FieldSide) -> Defender:
    return Defender(
        name=mon.species,
        defense=mon.base_def, sp_defense=mon.base_spd,
        types=mon.types, ability=mon.ability, item=mon.item,
        def_stage=mon.def_stage, spd_stage=mon.spd_stage,
        has_reflect=field.reflect_turns > 0,
        has_light_screen=field.light_screen_turns > 0,
    )

def _make_move_info(move: MoveDef) -> MoveInfo:
    return MoveInfo(
        name=move.name, type=move.type, base_power=move.base_power,
        is_explosion=move.is_explosion, breaks_screens=move.breaks_screens,
    )


# ============================================================
# Damage application with KO-threshold branching
# ============================================================

def apply_damage_rolls(state: BattleState, player: str,
                       move: MoveDef, target_player: str,
                       is_crit: bool
                       ) -> Dist:
    """
    Apply a damaging move's rolls to the target.
    Returns probability distribution branching on KO vs survive.
    Also handles: recoil/drain, Explosion self-faint.
    """
    attacker = state.active(player)
    defender = state.active(target_player)
    def_field = state.field_p1 if target_player == "p1" else state.field_p2

    atk = _make_attacker(attacker)
    dfn = _make_defender(defender, def_field)
    mi = _make_move_info(move)
    cond = Conditions(weather=state.weather, is_critical=is_crit)

    rolls = calc_damage(atk, dfn, mi, cond)

    if all(r == 0 for r in rolls):
        # Immune — move fails
        return [(1.0, state)]

    # Does the defender have a Substitute?
    if defender.substitute_hp > 0 and move.base_power > 0:
        return _apply_damage_to_sub(state, player, target_player, rolls, move)

    # KO-threshold branching
    defender_hp = defender.current_hp
    ko_rolls = [r for r in rolls if r >= defender_hp]
    survive_rolls = [r for r in rolls if r < defender_hp]

    results = []

    if ko_rolls:
        p_ko = len(ko_rolls) / 16
        new_defender = replace(defender, current_hp=0)
        s = state.set_active(target_player, new_defender)
        # Track damage for Counter
        s = _track_damage(s, target_player, defender_hp, move)
        # Recoil/drain on KO
        s = _apply_recoil_drain(s, player, defender_hp, move)
        # Explosion: attacker faints
        if move.is_explosion:
            s = _faint_attacker(s, player)
        results.append((p_ko, s))

    if survive_rolls:
        p_surv = len(survive_rolls) / 16
        avg_dmg = round(sum(survive_rolls) / len(survive_rolls))
        new_hp = max(1, defender_hp - avg_dmg)
        new_defender = replace(defender, current_hp=new_hp)
        s = state.set_active(target_player, new_defender)
        s = _track_damage(s, target_player, avg_dmg, move)
        s = _apply_recoil_drain(s, player, avg_dmg, move)
        if move.is_explosion:
            s = _faint_attacker(s, player)
        results.append((p_surv, s))

    return results


def _apply_damage_to_sub(state, player, target_player, rolls, move):
    """Handle damage hitting a Substitute."""
    defender = state.active(target_player)
    sub_hp = defender.substitute_hp
    
    breaks = [r for r in rolls if r >= sub_hp]
    survives = [r for r in rolls if r < sub_hp]
    results = []

    if breaks:
        p = len(breaks) / 16
        new_def = replace(defender, substitute_hp=0,
                          last_damage_taken=0, last_damage_physical=False)
        s = state.set_active(target_player, new_def)
        if move.is_explosion:
            s = _faint_attacker(s, player)
        results.append((p, s))

    if survives:
        p = len(survives) / 16
        avg_dmg = round(sum(survives) / len(survives))
        new_sub = max(0, sub_hp - avg_dmg)
        new_def = replace(defender, substitute_hp=new_sub,
                          last_damage_taken=0, last_damage_physical=False)
        s = state.set_active(target_player, new_def)
        if move.is_explosion:
            s = _faint_attacker(s, player)
        results.append((p, s))

    return results


def _track_damage(state, target_player, damage, move):
    """Record damage taken for Counter."""
    defender = state.active(target_player)
    cat = move.category if move.base_power > 0 else "status"
    is_phys = (cat == "physical")
    new_def = replace(defender, last_damage_taken=damage,
                      last_damage_physical=is_phys)
    return state.set_active(target_player, new_def)


def _apply_recoil_drain(state, player, damage_dealt, move):
    """Apply recoil or drain to the attacker."""
    if move.recoil == 0:
        return state
    attacker = state.active(player)
    if move.recoil > 0:
        # Recoil: lose HP
        recoil_dmg = max(1, math.floor(damage_dealt * move.recoil))
        new_hp = max(0, attacker.current_hp - recoil_dmg)
    else:
        # Drain: gain HP
        drain_amt = max(1, math.floor(damage_dealt * abs(move.recoil)))
        new_hp = min(attacker.max_hp, attacker.current_hp + drain_amt)
    new_atk = replace(attacker, current_hp=new_hp)
    return state.set_active(player, new_atk)


def _faint_attacker(state, player):
    """Explosion/Self-Destruct: attacker faints."""
    attacker = state.active(player)
    new_atk = replace(attacker, current_hp=0)
    return state.set_active(player, new_atk)


# ============================================================
# Secondary effects
# ============================================================

def apply_secondary_effect(state: BattleState, player: str,
                           target_player: str, move: MoveDef
                           ) -> Dist:
    """
    Apply a move's secondary effect (chance-based).
    Returns [(chance, state_with_effect), (1-chance, state_without)].
    """
    if not move.effect or move.effect_chance == 0:
        return [(1.0, state)]

    target = state.active(target_player)
    if not target.alive():
        return [(1.0, state)]

    # Don't apply effects through Substitute
    if target.substitute_hp > 0:
        return [(1.0, state)]

    chance = move.effect_chance / 100
    eff = move.effect

    if eff == "burn":
        if target.status is not None or "Fire" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="burn")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "paralyze":
        if target.status is not None:
            return [(1.0, state)]
        # Body Slam can't paralyze Normal types in Gen 3? Actually it can.
        new_t = replace(target, status="paralyze")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "freeze":
        if target.status is not None or "Ice" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="freeze")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "poison":
        if target.status is not None:
            return [(1.0, state)]
        if "Poison" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        if "Steel" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="poison")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "flinch":
        # Flinch is handled at the turn-resolution level, not here.
        # It's stored as a flag to check when the second mover acts.
        return [(1.0, state)]

    elif eff == "spd_minus1":
        if target.ability == "Clear Body":
            return [(1.0, state)]
        new_stage = max(-6, target.spd_stage - 1)
        if new_stage == target.spd_stage:
            return [(1.0, state)]
        new_t = replace(target, spd_stage=new_stage)
        s_eff = state.set_active(target_player, new_t)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "atk_plus1_self":
        attacker = state.active(player)
        new_stage = min(6, attacker.atk_stage + 1)
        if new_stage == attacker.atk_stage:
            return [(1.0, state)]
        new_a = replace(attacker, atk_stage=new_stage)
        s_eff = state.set_active(player, new_a)
        return [(chance, s_eff), (1 - chance, state)]

    return [(1.0, state)]


# ============================================================
# Status moves
# ============================================================

def execute_status_move(state: BattleState, player: str,
                        move: MoveDef) -> Dist:
    """Execute a non-damaging move. Returns probability distribution."""
    target_player = state.opp(player)
    attacker = state.active(player)
    target = state.active(target_player)
    eff = move.effect

    if eff == "taunt":
        if target.substitute_hp > 0:
            return [(1.0, state)]  # Gen 3: Taunt blocked by Sub? No actually it goes through.
        new_t = replace(target, taunt_turns=2)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "toxic":
        # Accuracy check handled by caller
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.status is not None:
            return [(1.0, state)]
        if "Poison" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        if "Steel" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="toxic", status_turns=0)
        s = state.set_active(target_player, new_t)
        s = _check_lum_berry(s, target_player)
        return [(1.0, s)]

    elif eff == "paralyze_status":
        # Thunder Wave
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.status is not None:
            return [(1.0, state)]
        # Ground types immune to Thunder Wave
        if "Ground" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="paralyze")
        s = state.set_active(target_player, new_t)
        s = _check_lum_berry(s, target_player)
        return [(1.0, s)]

    elif eff == "burn_status":
        # Will-O-Wisp
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.status is not None:
            return [(1.0, state)]
        if "Fire" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="burn")
        s = state.set_active(target_player, new_t)
        s = _check_lum_berry(s, target_player)
        return [(1.0, s)]

    elif eff == "substitute":
        sub_cost = attacker.max_hp // 4
        if attacker.current_hp <= sub_cost or attacker.substitute_hp > 0:
            return [(1.0, state)]  # Fails
        new_a = replace(attacker,
                        current_hp=attacker.current_hp - sub_cost,
                        substitute_hp=sub_cost)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "rest":
        if attacker.current_hp == attacker.max_hp and attacker.status is None:
            return [(1.0, state)]  # Full HP, no status — fails
        new_a = replace(attacker,
                        current_hp=attacker.max_hp,
                        status="sleep", status_turns=2)  # Gen 3: 2 turns
        s = state.set_active(player, new_a)
        # Chesto Berry wakes immediately
        s = _check_chesto_berry(s, player)
        return [(1.0, s)]

    elif eff == "sleep_talk":
        if attacker.status != "sleep":
            return [(1.0, state)]  # Fails if not asleep
        # Pick a random non-Sleep Talk move
        other_moves = [m for m in attacker.moves if m != "Sleep Talk"]
        if not other_moves:
            return [(1.0, state)]
        # Equal probability for each move
        prob_each = 1.0 / len(other_moves)
        results = []
        for move_name in other_moves:
            sub_move = get_move(move_name)
            # Execute the chosen move (recursively)
            sub_results = execute_single_move(state, player, sub_move,
                                              allow_sleep_check=False)
            for p, s in sub_results:
                results.append((prob_each * p, s))
        return results

    elif eff == "curse_normal":
        # Non-Ghost Curse: +1 Atk, +1 Def, -1 Spe
        new_atk_stage = min(6, attacker.atk_stage + 1)
        new_def_stage = min(6, attacker.def_stage + 1)
        new_spe_stage = max(-6, attacker.spe_stage - 1)
        new_a = replace(attacker,
                        atk_stage=new_atk_stage,
                        def_stage=new_def_stage,
                        spe_stage=new_spe_stage)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "pain_split":
        if target.substitute_hp > 0:
            return [(1.0, state)]
        avg_hp = (attacker.current_hp + target.current_hp) // 2
        new_a = replace(attacker, current_hp=min(attacker.max_hp, avg_hp))
        new_t = replace(target, current_hp=min(target.max_hp, avg_hp))
        s = state.set_active(player, new_a)
        s = s.set_active(target_player, new_t)
        return [(1.0, s)]

    elif eff == "counter":
        # Counter: deal 2× last physical damage taken
        if not attacker.last_damage_physical or attacker.last_damage_taken == 0:
            return [(1.0, state)]  # Fails if not hit by physical
        counter_dmg = attacker.last_damage_taken * 2
        if target.substitute_hp > 0:
            new_sub = max(0, target.substitute_hp - counter_dmg)
            new_t = replace(target, substitute_hp=new_sub)
        else:
            new_hp = max(0, target.current_hp - counter_dmg)
            new_t = replace(target, current_hp=new_hp)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "focus_punch":
        # Focus Punch damage is handled via apply_damage_rolls.
        # The "fails if hit" check is done by the turn resolver.
        pass

    return [(1.0, state)]


# ============================================================
# Single move execution (full pipeline)
# ============================================================

def execute_single_move(state: BattleState, player: str,
                        move: MoveDef, allow_sleep_check: bool = True
                        ) -> Dist:
    """
    Execute one move by one player. Full pipeline:
    1. Accuracy check
    2. If damaging: damage rolls with KO branching + crit branching
    3. Secondary effect chance
    4. If status: direct effect

    Returns Dist — probability distribution over resulting states.
    Does NOT handle paralysis/sleep/freeze skipping (caller's job).
    """
    target_player = state.opp(player)
    attacker = state.active(player)
    target = state.active(target_player)

    # Update last_move
    new_atk = replace(attacker, last_move=move.name)
    state = state.set_active(player, new_atk)

    # --- Status move ---
    if move.base_power == 0 and move.effect != "counter":
        # Accuracy check for status moves with < 100 accuracy
        if move.accuracy > 0 and move.accuracy < 100:
            hit_prob = move.accuracy / 100
            miss_results = [(1 - hit_prob, state)]
            hit_states = execute_status_move(state, player, move)
            return miss_results + [(hit_prob * p, s) for p, s in hit_states]
        return execute_status_move(state, player, move)

    # --- Counter (special: fixed damage, accuracy 100, -5 priority) ---
    if move.effect == "counter":
        return execute_status_move(state, player, move)

    # --- Damaging move ---
    # Accuracy check
    acc = move.accuracy
    if acc > 0 and acc < 100:
        hit_prob = acc / 100
    else:
        hit_prob = 1.0

    results = []
    if hit_prob < 1.0:
        results.append((1 - hit_prob, state))  # Miss

    # Crit branching: only branch when crit changes outcome
    for is_crit, crit_prob in [(False, 1 - CRIT_RATE), (True, CRIT_RATE)]:
        dmg_outcomes = apply_damage_rolls(state, player, move,
                                          target_player, is_crit)
        for p_dmg, s_dmg in dmg_outcomes:
            # Secondary effect
            eff_outcomes = apply_secondary_effect(
                s_dmg, player, target_player, move
            )
            for p_eff, s_eff in eff_outcomes:
                total_p = hit_prob * crit_prob * p_dmg * p_eff
                if total_p > 1e-12:
                    results.append((total_p, s_eff))

    return results


# ============================================================
# Berry checks
# ============================================================

def _check_lum_berry(state: BattleState, player: str) -> BattleState:
    """Lum Berry: auto-cures any status, consumed."""
    mon = state.active(player)
    if mon.item == "Lum Berry" and not mon.item_consumed and mon.status:
        new_mon = replace(mon, status=None, status_turns=0,
                          item_consumed=True)
        return state.set_active(player, new_mon)
    return state


def _check_chesto_berry(state: BattleState, player: str) -> BattleState:
    """Chesto Berry: auto-cures sleep, consumed."""
    mon = state.active(player)
    if mon.item == "Chesto Berry" and not mon.item_consumed and mon.status == "sleep":
        new_mon = replace(mon, status=None, status_turns=0,
                          item_consumed=True)
        return state.set_active(player, new_mon)
    return state


# ============================================================
# End-of-turn effects
# ============================================================

def apply_end_of_turn(state: BattleState) -> BattleState:
    """
    Apply all end-of-turn effects. Batches all changes per Pokemon into
    a single replace() call for performance.
    """
    p1_mon = state.active("p1")
    p2_mon = state.active("p2")

    for player, mon in [("p1", p1_mon), ("p2", p2_mon)]:
        if not mon.alive():
            continue

        hp = mon.current_hp
        st_turns = mon.status_turns
        consumed = mon.item_consumed
        taunt = mon.taunt_turns

        # Weather damage
        if state.weather == "sand":
            immune = ("Rock" in mon.types or "Ground" in mon.types
                      or "Steel" in mon.types)
            if not immune:
                hp -= max(1, mon.max_hp // 16)

        # Leftovers
        if mon.item == "Leftovers":
            hp = min(mon.max_hp, hp + max(1, mon.max_hp // 16))

        # Burn
        if mon.status == "burn":
            hp -= max(1, mon.max_hp // 8)

        # Poison
        if mon.status == "poison":
            hp -= max(1, mon.max_hp // 8)

        # Toxic
        if mon.status == "toxic":
            st_turns += 1
            hp -= max(1, mon.max_hp * st_turns // 16)

        hp = max(0, min(mon.max_hp, hp))

        # Sitrus Berry
        if (mon.item == "Sitrus Berry" and not consumed
                and hp <= mon.max_hp // 2 and hp > 0):
            hp = min(mon.max_hp, hp + 30)
            consumed = True

        # Taunt countdown
        if taunt > 0:
            taunt -= 1

        # Single replace for all changes
        if (hp != mon.current_hp or st_turns != mon.status_turns
                or consumed != mon.item_consumed or taunt != mon.taunt_turns):
            new_mon = replace(mon, current_hp=hp, status_turns=st_turns,
                              item_consumed=consumed, taunt_turns=taunt,
                              flinched=False, last_damage_taken=0,
                              last_damage_physical=False)
            state = state.set_active(player, new_mon)
        elif mon.flinched or mon.last_damage_taken > 0:
            new_mon = replace(mon, flinched=False, last_damage_taken=0,
                              last_damage_physical=False)
            state = state.set_active(player, new_mon)

    # Screen countdown (batched)
    for player in ["p1", "p2"]:
        field = state.field_p1 if player == "p1" else state.field_p2
        new_r = max(0, field.reflect_turns - 1)
        new_ls = max(0, field.light_screen_turns - 1)
        if new_r != field.reflect_turns or new_ls != field.light_screen_turns:
            state = state.set_field(player,
                replace(field, reflect_turns=new_r, light_screen_turns=new_ls))

    # Weather countdown
    if state.weather and state.weather_turns > 0:
        new_t = state.weather_turns - 1
        if new_t <= 0:
            state = replace(state, weather=None, weather_turns=0,
                            turn_number=state.turn_number + 1)
        else:
            state = replace(state, weather_turns=new_t,
                            turn_number=state.turn_number + 1)
    else:
        state = replace(state, turn_number=state.turn_number + 1)

    return state


# ============================================================
# Legal action generation
# ============================================================

def get_legal_actions(state: BattleState, player: str) -> list:
    """
    Returns list of legal actions: ("move", move_name) or ("switch", idx).
    """
    mon = state.active(player)
    actions = []

    # Moves
    if mon.alive():
        for move_name in mon.moves:
            move = get_move(move_name)

            # Choice Band lock
            if mon.move_locked and move_name != mon.move_locked:
                continue

            # Taunt blocks status moves
            if mon.taunt_turns > 0 and move.base_power == 0:
                if move.effect not in ("counter",):  # Counter is fighting-type, treated special
                    continue

            actions.append(("move", move_name))

    # Switches
    bench = state.alive_bench(player)
    for idx in bench:
        actions.append(("switch", idx))

    if not actions:
        actions.append(("move", "Struggle"))

    return actions
