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


def _safeguard_active(state: BattleState, player: str) -> bool:
    field = state.field_p1 if player == "p1" else state.field_p2
    return field.safeguard_turns > 0


# ============================================================
# Convert state Pokemon → damage calc inputs
# ============================================================

def _make_attacker(mon: Pokemon) -> Attacker:
    atk = mon.base_atk
    status = mon.status
    # Guts: +50% Atk when statused, and prevents burn from halving Atk
    if mon.ability == "Guts" and mon.status is not None:
        atk = int(atk * 1.5)
        status = None  # prevent burn-halving inside calc_damage
    # Hustle: +50% Atk (physical moves)
    if mon.ability == "Hustle":
        atk = int(atk * 1.5)
    return Attacker(
        name=mon.species, level=50,
        attack=atk, sp_attack=mon.base_spa,
        types=mon.types, ability=mon.ability, item=mon.item,
        status=status, atk_stage=mon.atk_stage, spa_stage=mon.spa_stage,
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

    # Ability-based type immunities with healing effect
    if move.type == "Electric" and defender.ability == "Volt Absorb":
        heal = max(1, defender.max_hp // 4)
        new_hp = min(defender.max_hp, defender.current_hp + heal)
        new_def = replace(defender, current_hp=new_hp)
        return [(1.0, state.set_active(target_player, new_def))]
    if move.type == "Water" and defender.ability == "Water Absorb":
        heal = max(1, defender.max_hp // 4)
        new_hp = min(defender.max_hp, defender.current_hp + heal)
        new_def = replace(defender, current_hp=new_hp)
        return [(1.0, state.set_active(target_player, new_def))]

    # Protect/Detect block incoming targeted damage moves.
    if defender.protected:
        return [(1.0, state)]

    # Does the defender have a Substitute?
    if defender.substitute_hp > 0 and move.base_power > 0:
        return _apply_damage_to_sub(state, player, target_player, rolls, move)

    # Endure: survive lethal hit at 1 HP.
    if defender.enduring and defender.current_hp > 1:
        rolls = [min(r, defender.current_hp - 1) for r in rolls]

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
        # Split survive rolls at the median so the search tree sees both a
        # low-damage and a high-damage HP bracket, not just a single average.
        # Each group keeps its own average; _merge_outcomes collapses them if
        # the rounded damage happens to be the same.
        mid = len(survive_rolls) // 2
        groups = [survive_rolls[:mid], survive_rolls[mid:]] if mid else [survive_rolls]
        for grp in groups:
            p_grp = len(grp) / 16
            avg_dmg = round(sum(grp) / len(grp))
            new_hp = max(1, defender_hp - avg_dmg)
            new_defender = replace(defender, current_hp=new_hp)
            s = state.set_active(target_player, new_defender)
            s = _track_damage(s, target_player, avg_dmg, move)
            s = _apply_recoil_drain(s, player, avg_dmg, move)
            if move.is_explosion:
                s = _faint_attacker(s, player)
            results.append((p_grp, s))

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
        mid = len(survives) // 2
        groups = [survives[:mid], survives[mid:]] if mid else [survives]
        for grp in groups:
            p = len(grp) / 16
            avg_dmg = round(sum(grp) / len(grp))
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
    """Apply recoil or drain to the attacker. Also handles Shell Bell."""
    attacker = state.active(player)
    # Shell Bell: heal 1/8 of damage dealt (not consumed)
    if move.base_power > 0 and attacker.item == "Shell Bell" and damage_dealt > 0:
        heal = max(1, damage_dealt // 8)
        new_hp = min(attacker.max_hp, attacker.current_hp + heal)
        attacker = replace(attacker, current_hp=new_hp)
        state = state.set_active(player, attacker)

    if move.recoil == 0:
        return state
    # Rock Head: no recoil from recoil moves
    if attacker.ability == "Rock Head" and move.recoil > 0:
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

    # Don't apply effects through Substitute (self-targeting effects bypass this)
    self_targeting = move.effect in (
        "atk_plus1_self", "all_stats_plus1_self",
        "spa_minus2_self", "atk_def_minus1_self", "def_plus1_self",
    )
    if target.substitute_hp > 0 and not self_targeting:
        return [(1.0, state)]

    chance = move.effect_chance / 100
    # Serene Grace doubles secondary effect chance
    if state.active(player).ability == "Serene Grace":
        chance = min(1.0, chance * 2)
    eff = move.effect

    if eff == "burn":
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.status is not None or "Fire" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="burn")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "paralyze":
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.status is not None:
            return [(1.0, state)]
        # Body Slam can't paralyze Normal types in Gen 3? Actually it can.
        new_t = replace(target, status="paralyze")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "freeze":
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.status is not None or "Ice" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        new_t = replace(target, status="freeze")
        s_eff = state.set_active(target_player, new_t)
        s_eff = _check_lum_berry(s_eff, target_player)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "poison":
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
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

    elif eff == "def_minus1":
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.def_stage - 1)
        if new_stage == target.def_stage:
            return [(1.0, state)]
        new_t = replace(target, def_stage=new_stage)
        s_eff = state.set_active(target_player, new_t)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "spe_minus1":
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.spe_stage - 1)
        if new_stage == target.spe_stage:
            return [(1.0, state)]
        new_t = replace(target, spe_stage=new_stage)
        s_eff = state.set_active(target_player, new_t)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "confuse":
        # Secondary confusion (Dragon Breath 30%, Dynamic Punch 100%, etc.)
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.confused:
            return [(1.0, state)]
        # Branch on random duration 2-5 turns
        results = []
        p_hit_each = chance / 4
        for turns in [2, 3, 4, 5]:
            new_t = replace(target, confused=True, confused_turns=turns)
            s_eff = state.set_active(target_player, new_t)
            results.append((p_hit_each, s_eff))
        results.append((1 - chance, state))
        return results

    elif eff == "all_stats_plus1_self":
        # Ancient Power / Silver Wind: +1 to all 5 stats (chance)
        attacker = state.active(player)
        new_a = replace(attacker,
                        atk_stage=min(6, attacker.atk_stage + 1),
                        def_stage=min(6, attacker.def_stage + 1),
                        spa_stage=min(6, attacker.spa_stage + 1),
                        spd_stage=min(6, attacker.spd_stage + 1),
                        spe_stage=min(6, attacker.spe_stage + 1))
        s_eff = state.set_active(player, new_a)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "spa_minus2_self":
        # Overheat: -2 SpA to user after attack
        attacker = state.active(player)
        new_stage = max(-6, attacker.spa_stage - 2)
        if new_stage == attacker.spa_stage:
            return [(1.0, state)]
        new_a = replace(attacker, spa_stage=new_stage)
        s_eff = state.set_active(player, new_a)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "atk_def_minus1_self":
        # Superpower: -1 Atk, -1 Def to user after attack
        attacker = state.active(player)
        new_a = replace(attacker,
                        atk_stage=max(-6, attacker.atk_stage - 1),
                        def_stage=max(-6, attacker.def_stage - 1))
        s_eff = state.set_active(player, new_a)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "def_plus1_self":
        # Steel Wing: +1 Def to user (10%)
        attacker = state.active(player)
        new_stage = min(6, attacker.def_stage + 1)
        if new_stage == attacker.def_stage:
            return [(1.0, state)]
        new_a = replace(attacker, def_stage=new_stage)
        s_eff = state.set_active(player, new_a)
        return [(chance, s_eff), (1 - chance, state)]

    elif eff == "spa_minus1":
        # Mist Ball: -1 SpA to target
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.spa_stage - 1)
        if new_stage == target.spa_stage:
            return [(1.0, state)]
        new_t = replace(target, spa_stage=new_stage)
        s_eff = state.set_active(target_player, new_t)
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

    self_targeting = {
        "substitute", "rest", "sleep_talk", "curse_normal",
        "atk_plus2_self", "atk_spe_plus1_self", "spa_spd_plus1_self",
        "spe_plus2_self", "spd_plus2_self", "recover_half",
        "atk_def_plus1_self", "def_spd_plus1_self", "def_plus2_self",
        "belly_drum", "spa_plus3_self", "atk_plus1_self_status",
        "rain_dance", "sunny_day", "hail", "sandstorm_move",
        "reflect", "light_screen", "safeguard", "protect", "endure",
        "haze", "psych_up",
    }
    if target.protected and eff not in self_targeting:
        return [(1.0, state)]

    if eff == "taunt":
        # Gen 3: Taunt is not blocked by Substitute
        new_t = replace(target, taunt_turns=3)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "toxic":
        # Accuracy check handled by caller
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if _safeguard_active(state, target_player):
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
        if _safeguard_active(state, target_player):
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
        if _safeguard_active(state, target_player):
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

    # --- Stat boost/drop moves ---

    elif eff == "atk_plus2_self":
        # Swords Dance
        new_stage = min(6, attacker.atk_stage + 2)
        if new_stage == attacker.atk_stage:
            return [(1.0, state)]
        new_a = replace(attacker, atk_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "atk_spe_plus1_self":
        # Dragon Dance
        new_a = replace(attacker,
                        atk_stage=min(6, attacker.atk_stage + 1),
                        spe_stage=min(6, attacker.spe_stage + 1))
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "spa_spd_plus1_self":
        # Calm Mind
        new_a = replace(attacker,
                        spa_stage=min(6, attacker.spa_stage + 1),
                        spd_stage=min(6, attacker.spd_stage + 1))
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "spe_plus2_self":
        # Agility
        new_stage = min(6, attacker.spe_stage + 2)
        if new_stage == attacker.spe_stage:
            return [(1.0, state)]
        new_a = replace(attacker, spe_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "spd_plus2_self":
        # Amnesia
        new_stage = min(6, attacker.spd_stage + 2)
        if new_stage == attacker.spd_stage:
            return [(1.0, state)]
        new_a = replace(attacker, spd_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    # --- Recovery moves ---

    elif eff == "recover_half":
        # Recover / Softboiled / Moonlight (weather modifier ignored)
        new_hp = min(attacker.max_hp,
                     attacker.current_hp + max(1, attacker.max_hp // 2))
        if new_hp == attacker.current_hp:
            return [(1.0, state)]
        new_a = replace(attacker, current_hp=new_hp)
        return [(1.0, state.set_active(player, new_a))]

    # --- Sleep-inflicting moves ---

    elif eff == "sleep_status":
        # Spore / Hypnosis (accuracy checked by caller)
        # Battle Tower rules: no Sleep Clause
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.status is not None:
            return [(1.0, state)]
        # Random duration 1-4 turns (equal probability)
        results = []
        for turns in [1, 2, 3, 4]:
            new_t = replace(target, status="sleep", status_turns=turns)
            s = state.set_active(target_player, new_t)
            s = _check_lum_berry(s, target_player)
            results.append((0.25, s))
        return results

    # --- Confusion-inflicting moves ---

    elif eff == "confuse_status":
        # Confuse Ray (never misses when it hits — accuracy handled by caller)
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if _safeguard_active(state, target_player):
            return [(1.0, state)]
        if target.confused:
            return [(1.0, state)]
        # Random duration 2-5 turns
        results = []
        for turns in [2, 3, 4, 5]:
            new_t = replace(target, confused=True, confused_turns=turns)
            s = state.set_active(target_player, new_t)
            results.append((0.25, s))
        return results

    # --- Fixed-damage moves ---

    elif eff == "seismic_toss":
        # Normal-type: Ghost immune
        if "Ghost" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        dmg = 50  # level 50
        if target.substitute_hp > 0:
            new_sub = max(0, target.substitute_hp - dmg)
            new_t = replace(target, substitute_hp=new_sub,
                            last_damage_taken=0, last_damage_physical=False)
        else:
            new_hp = max(0, target.current_hp - dmg)
            new_t = replace(target, current_hp=new_hp,
                            last_damage_taken=dmg, last_damage_physical=True)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "night_shade":
        # Ghost-type: Normal immune
        if "Normal" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        dmg = 50  # level 50
        if target.substitute_hp > 0:
            new_sub = max(0, target.substitute_hp - dmg)
            new_t = replace(target, substitute_hp=new_sub,
                            last_damage_taken=0, last_damage_physical=False)
        else:
            new_hp = max(0, target.current_hp - dmg)
            new_t = replace(target, current_hp=new_hp,
                            last_damage_taken=0, last_damage_physical=False)
        return [(1.0, state.set_active(target_player, new_t))]

    # --- Entry hazards ---

    elif eff == "lay_spikes":
        field = state.field_p1 if target_player == "p1" else state.field_p2
        if field.spikes >= 3:
            return [(1.0, state)]  # Max layers
        new_field = replace(field, spikes=field.spikes + 1)
        return [(1.0, state.set_field(target_player, new_field))]

    # --- Setup moves ---

    elif eff == "atk_def_plus1_self":
        # Bulk Up
        new_a = replace(attacker,
                        atk_stage=min(6, attacker.atk_stage + 1),
                        def_stage=min(6, attacker.def_stage + 1))
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "def_spd_plus1_self":
        # Cosmic Power
        new_a = replace(attacker,
                        def_stage=min(6, attacker.def_stage + 1),
                        spd_stage=min(6, attacker.spd_stage + 1))
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "def_plus2_self":
        # Acid Armor
        new_stage = min(6, attacker.def_stage + 2)
        if new_stage == attacker.def_stage:
            return [(1.0, state)]
        new_a = replace(attacker, def_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "belly_drum":
        cost = attacker.max_hp // 2
        if attacker.current_hp <= cost or attacker.atk_stage >= 6:
            return [(1.0, state)]
        new_a = replace(attacker, current_hp=attacker.current_hp - cost, atk_stage=6)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "spa_plus3_self":
        # Tail Glow (Gen 3: +3 SpA)
        new_stage = min(6, attacker.spa_stage + 3)
        if new_stage == attacker.spa_stage:
            return [(1.0, state)]
        new_a = replace(attacker, spa_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    elif eff == "atk_plus1_self_status":
        # Howl / Meditate
        new_stage = min(6, attacker.atk_stage + 1)
        if new_stage == attacker.atk_stage:
            return [(1.0, state)]
        new_a = replace(attacker, atk_stage=new_stage)
        return [(1.0, state.set_active(player, new_a))]

    # --- Weather moves ---

    elif eff == "rain_dance":
        s = replace(state, weather="rain", weather_turns=5)
        return [(1.0, s)]

    elif eff == "sunny_day":
        s = replace(state, weather="sun", weather_turns=5)
        return [(1.0, s)]

    elif eff == "hail":
        s = replace(state, weather="hail", weather_turns=5)
        return [(1.0, s)]

    elif eff == "sandstorm_move":
        s = replace(state, weather="sand", weather_turns=5)
        return [(1.0, s)]

    # --- Screens ---

    elif eff == "reflect":
        field = state.field_p1 if player == "p1" else state.field_p2
        if field.reflect_turns > 0:
            return [(1.0, state)]
        new_field = replace(field, reflect_turns=5)
        return [(1.0, state.set_field(player, new_field))]

    elif eff == "light_screen":
        field = state.field_p1 if player == "p1" else state.field_p2
        if field.light_screen_turns > 0:
            return [(1.0, state)]
        new_field = replace(field, light_screen_turns=5)
        return [(1.0, state.set_field(player, new_field))]

    elif eff == "safeguard":
        field = state.field_p1 if player == "p1" else state.field_p2
        if field.safeguard_turns > 0:
            return [(1.0, state)]
        new_field = replace(field, safeguard_turns=5)
        return [(1.0, state.set_field(player, new_field))]

    elif eff in ("protect", "endure"):
        # Gen 3 consecutive success chance: 1, 1/2, 1/4, ...
        success = 1.0 / (2 ** attacker.protect_consecutive)
        success = min(1.0, success)
        success_mon = replace(
            attacker,
            protect_consecutive=attacker.protect_consecutive + 1,
            protected=(eff == "protect"),
            enduring=(eff == "endure"),
        )
        fail_mon = replace(
            attacker,
            protect_consecutive=0,
            protected=False,
            enduring=False,
        )
        s_ok = state.set_active(player, success_mon)
        s_fail = state.set_active(player, fail_mon)
        return [(success, s_ok), (1 - success, s_fail)]

    # --- Opponent stat drops ---

    elif eff == "def_minus2_opp":
        # Screech
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.def_stage - 2)
        if new_stage == target.def_stage:
            return [(1.0, state)]
        new_t = replace(target, def_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "spe_minus2_opp":
        # Scary Face / Cotton Spore
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.spe_stage - 2)
        if new_stage == target.spe_stage:
            return [(1.0, state)]
        new_t = replace(target, spe_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "spd_minus2_opp":
        # Metal Sound
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.spd_stage - 2)
        if new_stage == target.spd_stage:
            return [(1.0, state)]
        new_t = replace(target, spd_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "def_minus1_opp":
        # Leer / Tail Whip
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_stage = max(-6, target.def_stage - 1)
        if new_stage == target.def_stage:
            return [(1.0, state)]
        new_t = replace(target, def_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "atk_minus1_opp":
        # Growl
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke", "Hyper Cutter"):
            return [(1.0, state)]
        new_stage = max(-6, target.atk_stage - 1)
        if new_stage == target.atk_stage:
            return [(1.0, state)]
        new_t = replace(target, atk_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "atk_minus2_opp":
        # Charm
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke", "Hyper Cutter"):
            return [(1.0, state)]
        new_stage = max(-6, target.atk_stage - 2)
        if new_stage == target.atk_stage:
            return [(1.0, state)]
        new_t = replace(target, atk_stage=new_stage)
        return [(1.0, state.set_active(target_player, new_t))]

    elif eff == "atk_def_minus1_opp":
        # Tickle
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if target.ability in ("Clear Body", "White Smoke"):
            return [(1.0, state)]
        new_t = replace(target,
                        atk_stage=max(-6, target.atk_stage - 1),
                        def_stage=max(-6, target.def_stage - 1))
        return [(1.0, state.set_active(target_player, new_t))]

    # --- Swagger / Flatter ---

    elif eff == "swagger":
        if target.substitute_hp > 0:
            return [(1.0, state)]
        new_atk = min(6, target.atk_stage + 2)
        new_t_atk = replace(target, atk_stage=new_atk)
        s = state.set_active(target_player, new_t_atk)
        if s.active(target_player).confused:
            return [(1.0, s)]
        results = []
        for turns in [2, 3, 4, 5]:
            new_t2 = replace(s.active(target_player), confused=True, confused_turns=turns)
            results.append((0.25, s.set_active(target_player, new_t2)))
        return results

    # --- Roar / Whirlwind (force switch) ---

    elif eff == "roar":
        if target.substitute_hp > 0:
            return [(1.0, state)]
        opp_team = list(state.get_team(target_player))
        opp_active_idx = state.get_active_idx(target_player)
        alternatives = [i for i, m in enumerate(opp_team)
                        if i != opp_active_idx and m.alive()]
        if not alternatives:
            return [(1.0, state)]
        # Branch equally over each possible switch-in
        # Apply full switch-in processing: clears outgoing volatiles,
        # applies Spikes/entry abilities (Intimidate, Sand Stream, etc.)
        from .turn import execute_switch  # local import to avoid circularity
        p = 1.0 / len(alternatives)
        results = []
        for idx in alternatives:
            new_s = execute_switch(state, target_player, idx)
            results.append((p, new_s))
        return results

    # --- Haze (clear all stat stages) ---

    elif eff == "haze":
        act_p = state.active(player)
        act_t = state.active(target_player)
        new_a = replace(act_p, atk_stage=0, def_stage=0, spa_stage=0,
                        spd_stage=0, spe_stage=0)
        new_t = replace(act_t, atk_stage=0, def_stage=0, spa_stage=0,
                        spd_stage=0, spe_stage=0)
        s = state.set_active(player, new_a)
        s = s.set_active(target_player, new_t)
        return [(1.0, s)]

    # --- Psych Up (copy opponent's stages) ---

    elif eff == "psych_up":
        opp = state.active(target_player)
        new_a = replace(attacker,
                        atk_stage=opp.atk_stage, def_stage=opp.def_stage,
                        spa_stage=opp.spa_stage, spd_stage=opp.spd_stage,
                        spe_stage=opp.spe_stage)
        return [(1.0, state.set_active(player, new_a))]

    # --- OHKO ---

    elif eff == "ohko":
        # Accuracy already applied by caller; if we reach here the move "hit"
        if target.ability == "Sturdy":
            return [(1.0, state)]  # Sturdy blocks OHKO
        new_t = replace(target, current_hp=0)
        return [(1.0, state.set_active(target_player, new_t))]

    # --- Mirror Coat ---

    elif eff == "mirror_coat":
        if attacker.last_damage_physical or attacker.last_damage_taken == 0:
            return [(1.0, state)]
        dmg = attacker.last_damage_taken * 2
        if target.substitute_hp > 0:
            new_sub = max(0, target.substitute_hp - dmg)
            new_t = replace(target, substitute_hp=new_sub)
        else:
            new_hp = max(0, target.current_hp - dmg)
            new_t = replace(target, current_hp=new_hp)
        return [(1.0, state.set_active(target_player, new_t))]

    # --- Leech Seed ---

    elif eff == "leech_seed":
        if target.substitute_hp > 0:
            return [(1.0, state)]
        if "Grass" in (target.types[0], target.types[1]):
            return [(1.0, state)]
        if target.leech_seeded:
            return [(1.0, state)]
        return [(1.0, state.set_active(target_player, replace(target, leech_seeded=True)))]

    # --- Stubs (no-op — complex mechanics not fully modelled) ---
    # attract, baton_pass,
    # destiny_bond, skill_swap, trick, memento, encore, disable, perish_song,
    # trap, follow_me, metronome, role_play, recycle, grudge, spite, torment,
    # imprison, evasion_plus1, acc_minus1

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

    # NOTE: We intentionally do NOT set last_move before the accuracy branch.
    # Doing so makes pure miss outcomes indistinguishable from successful
    # move-use outcomes in the turn layer, which in turn can cause
    # Choice Band to lock on misses.
    #
    # Instead, we create a separate state_with_last_move and only use it on
    # branches where the move actually counts as being used.
    next_consecutive = attacker.protect_consecutive
    if move.effect not in ("protect", "endure"):
        next_consecutive = 0
    state_with_last_move = state.set_active(
        player,
        replace(
            attacker,
            last_move=move.name,
            protect_consecutive=next_consecutive,
            protected=False,
            enduring=False,
        )
    )

    # --- Status move ---
    if move.base_power == 0 and move.effect != "counter":
        # Accuracy check for status moves with < 100 accuracy
        if move.accuracy > 0 and move.accuracy < 100:
            hit_prob = move.accuracy / 100
            # Pure misses do not count as move-use for Choice Band lock.
            miss_results = [(1 - hit_prob, state)]
            hit_states = execute_status_move(state_with_last_move, player, move)
            return miss_results + [(hit_prob * p, s) for p, s in hit_states]
        return execute_status_move(state_with_last_move, player, move)

    # --- Counter (special: fixed damage, accuracy 100, -5 priority) ---
    if move.effect == "counter":
        return execute_status_move(state_with_last_move, player, move)

    # --- Damaging move ---
    # Accuracy check
    acc = move.accuracy
    if acc > 0:  # acc == 0 means never miss
        hit_prob = acc / 100
        # Hustle lowers physical move accuracy by 20%
        if (attacker.ability == "Hustle" and move.category == "physical"):
            hit_prob = max(0.0, hit_prob * 0.8)
    else:
        hit_prob = 1.0

    results = []
    if hit_prob < 1.0:
        # Pure misses should not mark the move as used for downstream
        # Choice Band lock handling.
        results.append((1 - hit_prob, state))

    # Crit branching: only branch when crit changes outcome
    for is_crit, crit_prob in [(False, 1 - CRIT_RATE), (True, CRIT_RATE)]:
        dmg_outcomes = apply_damage_rolls(state_with_last_move, player, move,
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
        elif state.weather == "hail":
            if "Ice" not in (mon.types[0], mon.types[1]):
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

        # Leech Seed
        if mon.leech_seeded and hp > 0:
            drain = max(1, mon.max_hp // 8)
            drained = min(drain, hp)
            hp -= drain
            opp = state.opp(player)
            opp_mon = state.active(opp)
            if opp_mon.alive() and drained > 0:
                healed = min(opp_mon.max_hp, opp_mon.current_hp + drained)
                if healed != opp_mon.current_hp:
                    state = state.set_active(
                        opp, replace(opp_mon, current_hp=healed)
                    )

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
                              last_damage_physical=False,
                              protected=False, enduring=False)
            state = state.set_active(player, new_mon)
        elif mon.flinched or mon.last_damage_taken > 0 or mon.protected or mon.enduring:
            new_mon = replace(mon, flinched=False, last_damage_taken=0,
                              last_damage_physical=False,
                              protected=False, enduring=False)
            state = state.set_active(player, new_mon)

    # Pinch berries (trigger at ≤25% HP, single use)
    for player in ["p1", "p2"]:
        mon = state.active(player)
        if not mon.alive() or mon.item_consumed:
            continue
        if mon.current_hp > mon.max_hp // 4:
            continue
        item = mon.item
        new_mon = None
        if item == "Salac Berry":
            new_mon = replace(mon, spe_stage=min(6, mon.spe_stage + 1),
                              item_consumed=True)
        elif item == "Petaya Berry":
            new_mon = replace(mon, spa_stage=min(6, mon.spa_stage + 1),
                              item_consumed=True)
        elif item == "Liechi Berry":
            new_mon = replace(mon, atk_stage=min(6, mon.atk_stage + 1),
                              item_consumed=True)
        elif item == "Apicot Berry":
            new_mon = replace(mon, spd_stage=min(6, mon.spd_stage + 1),
                              item_consumed=True)
        elif item == "Ganlon Berry":
            new_mon = replace(mon, def_stage=min(6, mon.def_stage + 1),
                              item_consumed=True)
        if new_mon is not None:
            state = state.set_active(player, new_mon)

    # Screen countdown (batched)
    for player in ["p1", "p2"]:
        field = state.field_p1 if player == "p1" else state.field_p2
        new_r = max(0, field.reflect_turns - 1)
        new_ls = max(0, field.light_screen_turns - 1)
        new_sg = max(0, field.safeguard_turns - 1)
        if (new_r != field.reflect_turns
                or new_ls != field.light_screen_turns
                or new_sg != field.safeguard_turns):
            state = state.set_field(player,
                replace(field, reflect_turns=new_r,
                        light_screen_turns=new_ls,
                        safeguard_turns=new_sg))

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
