"""
Gen 3 Fast Rollout Simulator
==============================
Bypasses the probability-branching executor entirely.
Directly samples one random outcome per move for maximum speed.
"""

import math
import random
from dataclasses import replace
from .state import BattleState, Pokemon
from .moves import get_move, MoveDef
from .damage import (
    calc_damage, Attacker, Defender, MoveInfo, Conditions, apply_stage
)
from .types import type_effectiveness, move_category
from .executor import get_legal_actions, apply_end_of_turn, CRIT_RATE, PARA_SKIP, FREEZE_THAW


def _fast_attacker(mon: Pokemon) -> Attacker:
    return Attacker(mon.species, 50, mon.base_atk, mon.base_spa,
                    mon.types, mon.ability, mon.item,
                    mon.status, mon.atk_stage, mon.spa_stage)

def _fast_defender(mon: Pokemon, state: BattleState, player: str) -> Defender:
    field = state.field_p1 if player == "p1" else state.field_p2
    return Defender(mon.species, mon.base_def, mon.base_spd,
                    mon.types, mon.ability, mon.item,
                    mon.def_stage, mon.spd_stage,
                    field.reflect_turns > 0, field.light_screen_turns > 0)


def fast_execute_move(state: BattleState, player: str,
                      move_name: str) -> BattleState:
    """
    Execute a move with random sampling. No probability distributions.
    Returns a single concrete new state.
    """
    opp = state.opp(player)
    attacker = state.active(player)
    defender = state.active(opp)
    move = get_move(move_name)

    # Update last_move
    state = state.set_active(player, replace(attacker, last_move=move_name))
    attacker = state.active(player)

    # --- Status moves ---
    if move.base_power == 0 and move.effect != "counter":
        # Accuracy check
        if move.accuracy > 0 and move.accuracy < 100:
            if random.random() >= move.accuracy / 100:
                return state  # Miss

        return _fast_status(state, player, move)

    # --- Counter ---
    if move.effect == "counter":
        if not attacker.last_damage_physical or attacker.last_damage_taken == 0:
            return state
        dmg = attacker.last_damage_taken * 2
        if defender.substitute_hp > 0:
            new_sub = max(0, defender.substitute_hp - dmg)
            new_def = replace(defender, substitute_hp=new_sub)
        else:
            new_def = replace(defender, current_hp=max(0, defender.current_hp - dmg))
        return state.set_active(opp, new_def)

    # --- Damaging moves ---
    # Accuracy
    if move.accuracy > 0 and move.accuracy < 100:
        if random.random() >= move.accuracy / 100:
            # Explosion still faints on miss? No — if it misses, user doesn't faint
            return state

    # Crit check
    is_crit = random.random() < CRIT_RATE

    # Calculate damage
    mi = MoveInfo(move.name, move.type, move.base_power,
                  move.is_explosion, move.breaks_screens)
    cond = Conditions(state.weather, is_crit)
    atk_data = _fast_attacker(attacker)
    def_data = _fast_defender(defender, state, opp)
    rolls = calc_damage(atk_data, def_data, mi, cond)

    if all(r == 0 for r in rolls):
        # Immune
        if move.is_explosion:
            new_atk = replace(attacker, current_hp=0)
            state = state.set_active(player, new_atk)
        return state

    # Random roll
    dmg = random.choice(rolls)

    # Apply damage
    hit_directly = False
    if defender.substitute_hp > 0:
        new_sub = max(0, defender.substitute_hp - dmg)
        new_def = replace(defender, substitute_hp=new_sub,
                          last_damage_taken=0, last_damage_physical=False)
        state = state.set_active(opp, new_def)
    else:
        new_hp = max(0, defender.current_hp - dmg)
        cat = move_category(move.type) if move.base_power > 0 else "status"
        new_def = replace(defender, current_hp=new_hp,
                          last_damage_taken=dmg,
                          last_damage_physical=(cat == "physical"))
        state = state.set_active(opp, new_def)
        hit_directly = True

    # Recoil / drain
    if move.recoil != 0:
        atk = state.active(player)
        if move.recoil > 0:
            recoil_dmg = max(1, math.floor(dmg * move.recoil))
            new_hp = max(0, atk.current_hp - recoil_dmg)
        else:
            drain_amt = max(1, math.floor(dmg * abs(move.recoil)))
            new_hp = min(atk.max_hp, atk.current_hp + drain_amt)
        state = state.set_active(player, replace(atk, current_hp=new_hp))

    # Explosion: user faints
    if move.is_explosion:
        atk = state.active(player)
        state = state.set_active(player, replace(atk, current_hp=0))

    # Secondary effect
    if move.effect and move.effect_chance > 0 and hit_directly:
        target = state.active(opp)
        if target.alive() and target.substitute_hp == 0:
            if random.random() < move.effect_chance / 100:
                state = _fast_secondary(state, player, opp, move)

    return state


def _fast_status(state: BattleState, player: str, move: MoveDef) -> BattleState:
    """Handle status moves with direct state mutation."""
    opp = state.opp(player)
    attacker = state.active(player)
    target = state.active(opp)
    eff = move.effect

    if eff == "taunt":
        new_t = replace(target, taunt_turns=2)
        return state.set_active(opp, new_t)

    elif eff == "toxic":
        if target.substitute_hp > 0 or target.status is not None:
            return state
        if "Poison" in target.types or "Steel" in target.types:
            return state
        new_t = replace(target, status="toxic", status_turns=0)
        s = state.set_active(opp, new_t)
        return _fast_lum_berry(s, opp)

    elif eff == "paralyze_status":
        if target.substitute_hp > 0 or target.status is not None:
            return state
        if "Ground" in target.types:
            return state
        new_t = replace(target, status="paralyze")
        s = state.set_active(opp, new_t)
        return _fast_lum_berry(s, opp)

    elif eff == "burn_status":
        if target.substitute_hp > 0 or target.status is not None:
            return state
        if "Fire" in target.types:
            return state
        new_t = replace(target, status="burn")
        s = state.set_active(opp, new_t)
        return _fast_lum_berry(s, opp)

    elif eff == "substitute":
        cost = attacker.max_hp // 4
        if attacker.current_hp <= cost or attacker.substitute_hp > 0:
            return state
        new_a = replace(attacker, current_hp=attacker.current_hp - cost,
                        substitute_hp=cost)
        return state.set_active(player, new_a)

    elif eff == "rest":
        new_a = replace(attacker, current_hp=attacker.max_hp,
                        status="sleep", status_turns=2)
        s = state.set_active(player, new_a)
        # Chesto Berry
        mon = s.active(player)
        if mon.item == "Chesto Berry" and not mon.item_consumed:
            new_a = replace(mon, status=None, status_turns=0, item_consumed=True)
            s = s.set_active(player, new_a)
        return s

    elif eff == "sleep_talk":
        if attacker.status != "sleep":
            return state
        other_moves = [m for m in attacker.moves if m != "Sleep Talk"]
        if not other_moves:
            return state
        chosen = random.choice(other_moves)
        return fast_execute_move(state, player, chosen)

    elif eff == "curse_normal":
        new_a = replace(attacker,
                        atk_stage=min(6, attacker.atk_stage + 1),
                        def_stage=min(6, attacker.def_stage + 1),
                        spe_stage=max(-6, attacker.spe_stage - 1))
        return state.set_active(player, new_a)

    elif eff == "pain_split":
        if target.substitute_hp > 0:
            return state
        avg = (attacker.current_hp + target.current_hp) // 2
        new_a = replace(attacker, current_hp=min(attacker.max_hp, avg))
        new_t = replace(target, current_hp=min(target.max_hp, avg))
        s = state.set_active(player, new_a)
        return s.set_active(opp, new_t)

    return state


def _fast_secondary(state: BattleState, player: str, opp: str,
                    move: MoveDef) -> BattleState:
    """Apply a secondary effect (already rolled success)."""
    target = state.active(opp)
    eff = move.effect

    if eff == "burn" and target.status is None:
        if "Fire" not in target.types:
            new_t = replace(target, status="burn")
            s = state.set_active(opp, new_t)
            return _fast_lum_berry(s, opp)

    elif eff == "paralyze" and target.status is None:
        new_t = replace(target, status="paralyze")
        s = state.set_active(opp, new_t)
        return _fast_lum_berry(s, opp)

    elif eff == "freeze" and target.status is None:
        if "Ice" not in target.types:
            new_t = replace(target, status="freeze")
            s = state.set_active(opp, new_t)
            return _fast_lum_berry(s, opp)

    elif eff == "poison" and target.status is None:
        if "Poison" not in target.types and "Steel" not in target.types:
            new_t = replace(target, status="poison")
            s = state.set_active(opp, new_t)
            return _fast_lum_berry(s, opp)

    elif eff == "spd_minus1":
        if target.ability != "Clear Body":
            new_t = replace(target, spd_stage=max(-6, target.spd_stage - 1))
            return state.set_active(opp, new_t)

    elif eff == "atk_plus1_self":
        atk = state.active(player)
        new_a = replace(atk, atk_stage=min(6, atk.atk_stage + 1))
        return state.set_active(player, new_a)

    return state


def _fast_lum_berry(state: BattleState, player: str) -> BattleState:
    mon = state.active(player)
    if mon.item == "Lum Berry" and not mon.item_consumed and mon.status:
        return state.set_active(player,
            replace(mon, status=None, status_turns=0, item_consumed=True))
    return state


# ============================================================
# Fast turn simulator
# ============================================================

def fast_simulate_turn(state: BattleState,
                       action_p1, action_p2) -> BattleState:
    """
    Simulate one complete turn with random sampling.
    No probability distributions — purely stochastic.
    """
    from .turn import determine_order, execute_switch

    first_pl, second_pl = determine_order(state, action_p1, action_p2)
    first_action = action_p1 if first_pl == "p1" else action_p2
    second_action = action_p2 if first_pl == "p1" else action_p1

    s = state
    first_acted = False

    # --- First player ---
    first_mon = s.active(first_pl)
    if first_mon.alive():
        if first_action[0] == "switch":
            s = execute_switch(s, first_pl, first_action[1])
            first_acted = True
        else:
            # Status checks
            can_move = True
            move = get_move(first_action[1])

            if first_mon.taunt_turns > 0 and move.base_power == 0:
                if move.effect not in ("counter",):
                    can_move = False

            if can_move and first_mon.status == "paralyze":
                if random.random() < PARA_SKIP:
                    can_move = False
            if can_move and first_mon.status == "freeze":
                if random.random() < FREEZE_THAW:
                    new_mon = replace(first_mon, status=None, status_turns=0)
                    s = s.set_active(first_pl, new_mon)
                else:
                    can_move = False
            if can_move and first_mon.status == "sleep":
                fm = s.active(first_pl)
                if fm.status_turns > 1:
                    s = s.set_active(first_pl, replace(fm, status_turns=fm.status_turns - 1))
                    if first_action[1] != "Sleep Talk":
                        can_move = False
                elif fm.status_turns == 1:
                    s = s.set_active(first_pl, replace(fm, status=None, status_turns=0))
                else:
                    s = s.set_active(first_pl, replace(fm, status=None, status_turns=0))

            if can_move:
                s = fast_execute_move(s, first_pl, first_action[1])
                first_acted = True

    # Flinch check for second player
    second_mon = s.active(second_pl)
    flinched = False
    if first_acted and first_action[0] == "move" and second_mon.alive():
        fm = get_move(first_action[1])
        if fm.effect == "flinch" and fm.effect_chance > 0:
            old_hp = state.active(second_pl).current_hp
            new_hp = second_mon.current_hp
            if new_hp < old_hp:  # was hit
                if random.random() < fm.effect_chance / 100:
                    flinched = True

    # --- Second player ---
    second_mon = s.active(second_pl)
    if second_mon.alive() and not flinched:
        if second_action[0] == "switch":
            s = execute_switch(s, second_pl, second_action[1])
        else:
            can_move = True
            move = get_move(second_action[1])

            # Taunt (including mid-turn)
            sm = s.active(second_pl)
            if sm.taunt_turns > 0 and move.base_power == 0:
                if move.effect not in ("counter",):
                    can_move = False

            # Focus Punch: fails if hit
            if can_move and move.effect == "focus_punch":
                old_hp = state.active(second_pl).current_hp
                if second_mon.current_hp < old_hp and second_mon.substitute_hp == 0:
                    can_move = False

            if can_move and sm.status == "paralyze":
                if random.random() < PARA_SKIP:
                    can_move = False
            if can_move and sm.status == "freeze":
                if random.random() < FREEZE_THAW:
                    s = s.set_active(second_pl, replace(sm, status=None, status_turns=0))
                else:
                    can_move = False
            if can_move and sm.status == "sleep":
                sm2 = s.active(second_pl)
                if sm2.status_turns > 1:
                    s = s.set_active(second_pl, replace(sm2, status_turns=sm2.status_turns - 1))
                    if second_action[1] != "Sleep Talk":
                        can_move = False
                elif sm2.status_turns == 1:
                    s = s.set_active(second_pl, replace(sm2, status=None, status_turns=0))
                else:
                    s = s.set_active(second_pl, replace(sm2, status=None, status_turns=0))

            if can_move:
                s = fast_execute_move(s, second_pl, second_action[1])

    # End of turn + Choice Band lock
    s = apply_end_of_turn(s)
    for pl, act in [(first_pl, first_action), (second_pl, second_action)]:
        if act[0] == "move":
            mon = s.active(pl)
            if mon.item == "Choice Band" and not mon.item_consumed:
                if mon.move_locked is None and mon.alive():
                    s = s.set_active(pl, replace(mon, move_locked=act[1]))

    return s
