"""
Gen 3 Stat Calculator
=====================
Computes final stats at level 100 from base stats, nature, EVs, and IVs.
"""

import math
from .natures import nature_modifier


def calc_hp(base_hp: int, iv: int = 31, ev: int = 0, level: int = 100) -> int:
    """
    Gen 3 HP formula at a given level.
    HP = floor((2 * Base + IV + floor(EV/4)) * Level / 100) + Level + 10
    
    Special case: Shedinja always has 1 HP.
    """
    return math.floor(
        (2 * base_hp + iv + math.floor(ev / 4)) * level / 100
    ) + level + 10


def calc_stat(base: int, iv: int = 31, ev: int = 0,
              nature: str = "Hardy", stat_name: str = "atk",
              level: int = 100) -> int:
    """
    Gen 3 stat formula (non-HP) at a given level.
    Stat = floor((floor((2 * Base + IV + floor(EV/4)) * Level / 100) + 5) * NatureMod)
    """
    raw = math.floor(
        (2 * base + iv + math.floor(ev / 4)) * level / 100
    ) + 5
    return math.floor(raw * nature_modifier(nature, stat_name))


# Base stats for the 6 species on these teams
# Format: (HP, Atk, Def, SpA, SpD, Spe)
BASE_STATS = {
    "Skarmory":  (65, 80, 140, 40, 70, 70),
    "Gengar":    (60, 65, 60, 130, 75, 110),
    "Snorlax":   (160, 110, 65, 65, 110, 30),
    "Aggron":    (70, 110, 180, 60, 60, 50),
    "Weezing":   (65, 90, 120, 85, 70, 60),
    "Metagross": (80, 135, 130, 95, 90, 70),
}

# Type data for these species
SPECIES_TYPES = {
    "Skarmory":  ("Steel", "Flying"),
    "Gengar":    ("Ghost", "Poison"),
    "Snorlax":   ("Normal", None),
    "Aggron":    ("Steel", "Rock"),
    "Weezing":   ("Poison", None),
    "Metagross": ("Steel", "Psychic"),
}


def compute_all_stats(species: str, nature: str,
                      evs: dict, ivs: dict = None,
                      level: int = 50) -> dict:
    """
    Compute all 6 stats for a Pokemon.
    
    Args:
        species: Pokemon species name
        nature: Nature name (e.g. "Impish")
        evs: Dict of {"hp": 252, "atk": 0, ...} — missing keys default to 0
        ivs: Dict of {"hp": 31, ...} — missing keys default to 31
        level: Battle level (default 100)
    
    Returns:
        Dict with keys: hp, atk, def, spa, spd, spe
    """
    base = BASE_STATS[species]
    if ivs is None:
        ivs = {}
    
    stat_names = ["hp", "atk", "def", "spa", "spd", "spe"]
    
    result = {}
    for i, name in enumerate(stat_names):
        base_val = base[i]
        iv = ivs.get(name, 31)
        ev = evs.get(name, 0)
        
        if name == "hp":
            result[name] = calc_hp(base_val, iv, ev, level)
        else:
            result[name] = calc_stat(base_val, iv, ev, nature, name, level)
    
    return result
