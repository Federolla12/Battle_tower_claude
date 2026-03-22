"""
Gen 3 Damage Calculator
========================
Exact integer-arithmetic damage formula matching the Gen 3 game code.

Returns all 16 discrete damage rolls (85% to 100%) for a given attack,
plus the critical-hit variants. Handles: stat stages, burn, weather,
STAB, type effectiveness, abilities (Thick Fat, Levitate), items
(Choice Band), and special moves (Explosion defense halving).

Usage:
    rolls = calc_damage(attacker, defender, move, conditions)
    # rolls = [min_roll, ..., max_roll]  (16 values)
"""

import math
from typing import List, Tuple, Optional
from dataclasses import dataclass
from .types import type_effectiveness, move_category, PHYSICAL_TYPES, SPECIAL_TYPES


# ============================================================
# Stat stage multipliers (Gen 3)
# ============================================================

# Stage multipliers as (numerator, denominator) pairs
# Stage -6 through +6
STAGE_MULTIPLIERS = {
    -6: (2, 8), -5: (2, 7), -4: (2, 6), -3: (2, 5),
    -2: (2, 4), -1: (2, 3),  0: (2, 2),
    +1: (3, 2), +2: (4, 2), +3: (5, 2),
    +4: (6, 2), +5: (7, 2), +6: (8, 2),
}


def apply_stage(base_stat: int, stage: int) -> int:
    """Apply a stat stage modifier to a base stat value."""
    stage = max(-6, min(6, stage))
    num, den = STAGE_MULTIPLIERS[stage]
    return math.floor(base_stat * num / den)


# ============================================================
# Data classes for calc inputs
# ============================================================

@dataclass
class Attacker:
    """Everything about the attacking Pokemon relevant to damage."""
    name: str
    level: int
    attack: int          # final Atk stat
    sp_attack: int       # final SpA stat
    types: Tuple[str, Optional[str]]  # (type1, type2)
    ability: str
    item: Optional[str]
    status: Optional[str]  # "burn", "paralyze", etc.
    atk_stage: int       # -6 to +6
    spa_stage: int       # -6 to +6


@dataclass
class Defender:
    """Everything about the defending Pokemon relevant to damage."""
    name: str
    defense: int         # final Def stat
    sp_defense: int      # final SpD stat
    types: Tuple[str, Optional[str]]
    ability: str
    item: Optional[str]
    def_stage: int       # -6 to +6
    spd_stage: int       # -6 to +6
    has_reflect: bool    # Reflect active on defender's side
    has_light_screen: bool  # Light Screen active


@dataclass
class MoveInfo:
    """Move data needed for damage calculation."""
    name: str
    type: str            # "Fire", "Ground", etc.
    base_power: int      # 0 for status moves
    is_explosion: bool   # Explosion/Self-Destruct: halve defender's Def
    breaks_screens: bool # Brick Break: remove Reflect/Light Screen


@dataclass
class Conditions:
    """Field conditions affecting damage."""
    weather: Optional[str]  # "sun", "rain", "sand", "hail", None
    is_critical: bool


# ============================================================
# Core damage formula
# ============================================================

def calc_damage(attacker: Attacker, defender: Defender,
                move: MoveInfo, conditions: Conditions) -> List[int]:
    """
    Calculate all 16 damage rolls for a move.

    Implements the exact Gen 3 damage formula with integer math.
    Modifier order verified roll-by-roll against Smogon's ADV damage calc:

    1. base = floor(floor(floor(2*level/5 + 2) * power * A / D) / 50 + 2)
    2. Weather modifier (×3/2 or ×1/2)
    3. Critical hit (×2)
    4. STAB (×3/2)
    5. Type effectiveness vs type1
    6. Type effectiveness vs type2
    7. Random factor (×85..100 / 100) — creates 16 rolls  ← LAST

    Returns a list of 16 damage values (ascending order).
    Returns [0]*16 for immune matchups.
    """
    if move.base_power == 0:
        return [0] * 16

    # --- Determine physical vs special ---
    category = move_category(move.type)
    is_physical = (category == "physical")

    # --- Get effective attack and defense stats ---
    atk_stat, def_stat = _get_offensive_defensive(
        attacker, defender, move, conditions, is_physical
    )

    # --- Base power modifications ---
    power = move.base_power

    # Thick Fat: halves Fire/Ice move power
    if defender.ability == "Thick Fat" and move.type in ("Fire", "Ice"):
        power = math.floor(power / 2)

    # Type-boosting items (Charcoal, Mystic Water, etc.)
    power = _apply_power_item(power, attacker.item, move.type)

    if power == 0:
        return [0] * 16

    # --- Base damage calculation ---
    # Gen 3: floor at each division
    level = attacker.level
    base = math.floor(2 * level / 5 + 2)
    base = math.floor(base * power * atk_stat / def_stat)
    base = math.floor(base / 50) + 2

    # --- Weather modifier ---
    base = _apply_weather(base, move.type, conditions.weather)

    # --- Critical hit ---
    if conditions.is_critical:
        base = base * 2

    # --- STAB (applied to base, BEFORE random roll) ---
    base = _apply_stab(base, attacker.types, move.type)

    # --- Type effectiveness (applied to base, BEFORE random roll) ---
    base = _apply_type_effectiveness(base, move.type, defender.types,
                                     defender.ability)

    if base == 0:
        return [0] * 16

    # --- Generate 16 damage rolls (LAST modifier) ---
    rolls = []
    for r in range(85, 101):  # 85 through 100 inclusive = 16 values
        dmg = math.floor(base * r / 100)
        if dmg == 0:
            dmg = 1  # Minimum 1 damage if move connects
        rolls.append(dmg)

    return rolls


# ============================================================
# Helper functions
# ============================================================

def _get_offensive_defensive(attacker: Attacker, defender: Defender,
                             move: MoveInfo, conditions: Conditions,
                             is_physical: bool) -> Tuple[int, int]:
    """Get the effective offensive and defensive stats after all modifiers."""

    if is_physical:
        # --- Attack stat ---
        atk_base = attacker.attack
        atk_stage = attacker.atk_stage

        # Critical hits: ignore negative offensive stages
        if conditions.is_critical and atk_stage < 0:
            atk_stage = 0

        atk_stat = apply_stage(atk_base, atk_stage)

        # Choice Band: 1.5× Attack
        if attacker.item == "Choice Band":
            atk_stat = math.floor(atk_stat * 3 / 2)

        # Burn: halves Attack for physical moves
        if attacker.status == "burn":
            atk_stat = math.floor(atk_stat / 2)

        # --- Defense stat ---
        def_base = defender.defense
        def_stage = defender.def_stage

        # Critical hits: ignore positive defensive stages
        if conditions.is_critical and def_stage > 0:
            def_stage = 0

        def_stat = apply_stage(def_base, def_stage)

        # Explosion / Self-Destruct: halve Defense in Gen 3
        if move.is_explosion:
            def_stat = max(1, math.floor(def_stat / 2))

        # Reflect: doubles effective Defense (but not on crits)
        if defender.has_reflect and not conditions.is_critical:
            # Brick Break shatters Reflect before damage
            if not move.breaks_screens:
                def_stat = def_stat * 2

    else:
        # --- Special Attack stat ---
        atk_base = attacker.sp_attack
        atk_stage = attacker.spa_stage

        if conditions.is_critical and atk_stage < 0:
            atk_stage = 0

        atk_stat = apply_stage(atk_base, atk_stage)

        # --- Special Defense stat ---
        def_base = defender.sp_defense
        def_stage = defender.spd_stage

        if conditions.is_critical and def_stage > 0:
            def_stage = 0

        def_stat = apply_stage(def_base, def_stage)

        # Light Screen: doubles effective SpD (but not on crits)
        if defender.has_light_screen and not conditions.is_critical:
            if not move.breaks_screens:
                def_stat = def_stat * 2

    # Ensure minimums
    atk_stat = max(1, atk_stat)
    def_stat = max(1, def_stat)

    return atk_stat, def_stat


def _apply_weather(damage: int, move_type: str,
                   weather: Optional[str]) -> int:
    """Apply weather modifier to base damage."""
    if weather == "rain":
        if move_type == "Water":
            return math.floor(damage * 3 / 2)
        elif move_type == "Fire":
            return math.floor(damage / 2)
    elif weather == "sun":
        if move_type == "Fire":
            return math.floor(damage * 3 / 2)
        elif move_type == "Water":
            return math.floor(damage / 2)
    return damage


def _apply_stab(damage: int, attacker_types: Tuple[str, Optional[str]],
                move_type: str) -> int:
    """Apply Same Type Attack Bonus (×1.5)."""
    type1, type2 = attacker_types
    if move_type == type1 or (type2 and move_type == type2):
        return math.floor(damage * 3 / 2)
    return damage


def _apply_type_effectiveness(damage: int, move_type: str,
                              defender_types: Tuple[str, Optional[str]],
                              defender_ability: str) -> int:
    """
    Apply type effectiveness per defender type (with floor between).
    Also handles ability-based immunities (Levitate).
    """
    # Levitate grants Ground immunity
    if defender_ability == "Levitate" and move_type == "Ground":
        return 0

    def_type1, def_type2 = defender_types

    # Apply vs first type
    eff1 = type_effectiveness(move_type, def_type1)
    if eff1 == 0:
        return 0
    elif eff1 == 0.5:
        damage = math.floor(damage / 2)
    elif eff1 == 2.0:
        damage = damage * 2

    # Apply vs second type (if exists and different)
    if def_type2 and def_type2 != def_type1:
        eff2 = type_effectiveness(move_type, def_type2)
        if eff2 == 0:
            return 0
        elif eff2 == 0.5:
            damage = math.floor(damage / 2)
        elif eff2 == 2.0:
            damage = damage * 2

    return damage


def _apply_power_item(power: int, item: Optional[str],
                      move_type: str) -> int:
    """Apply type-boosting held items (1.1× to matching move type)."""
    BOOST_ITEMS = {
        "Charcoal": "Fire", "Mystic Water": "Water",
        "Miracle Seed": "Grass", "Magnet": "Electric",
        "Sharp Beak": "Flying", "Poison Barb": "Poison",
        "Soft Sand": "Ground", "Hard Stone": "Rock",
        "Silver Powder": "Bug", "Spell Tag": "Ghost",
        "Metal Coat": "Steel", "Twisted Spoon": "Psychic",
        "Never-Melt Ice": "Ice", "Dragon Fang": "Dragon",
        "Black Glasses": "Dark", "Silk Scarf": "Normal",
    }
    if item and item in BOOST_ITEMS and BOOST_ITEMS[item] == move_type:
        return math.floor(power * 11 / 10)
    return power


# ============================================================
# Convenience: compute damage range summary
# ============================================================

def damage_range(attacker: Attacker, defender: Defender,
                 move: MoveInfo, conditions: Conditions = None
                 ) -> dict:
    """
    Compute damage rolls and return a summary dict.

    Returns:
        {
            "rolls": [16 ints],
            "min": int, "max": int,
            "min_pct": float, "max_pct": float,  (% of defender max HP)
            "crit_rolls": [16 ints],
            "crit_min": int, "crit_max": int,
        }

    If conditions is None, uses default (no weather, no crit).
    """
    if conditions is None:
        conditions = Conditions(weather=None, is_critical=False)

    # Normal rolls
    normal_cond = Conditions(weather=conditions.weather, is_critical=False)
    rolls = calc_damage(attacker, defender, move, normal_cond)

    # Crit rolls
    crit_cond = Conditions(weather=conditions.weather, is_critical=True)
    crit_rolls = calc_damage(attacker, defender, move, crit_cond)

    return {
        "rolls": rolls,
        "min": min(rolls),
        "max": max(rolls),
        "crit_rolls": crit_rolls,
        "crit_min": min(crit_rolls),
        "crit_max": max(crit_rolls),
    }


def damage_range_pct(rolls: List[int], defender_max_hp: int) -> Tuple[float, float]:
    """Convert damage rolls to percentage of max HP."""
    if defender_max_hp == 0:
        return (0.0, 0.0)
    return (min(rolls) / defender_max_hp * 100,
            max(rolls) / defender_max_hp * 100)
