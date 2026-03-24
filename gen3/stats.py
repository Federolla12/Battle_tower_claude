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


# Base stats — format: (HP, Atk, Def, SpA, SpD, Spe)
BASE_STATS = {
    # --- Original 6 ---
    "Skarmory":   (65, 80, 140, 40, 70, 70),
    "Gengar":     (60, 65, 60, 130, 75, 110),
    "Snorlax":    (160, 110, 65, 65, 110, 30),
    "Aggron":     (70, 110, 180, 60, 60, 50),
    "Weezing":    (65, 90, 120, 85, 70, 60),
    "Metagross":  (80, 135, 130, 95, 90, 70),
    # --- Common Battle Tower picks ---
    "Salamence":  (95, 135, 80, 110, 80, 100),
    "Starmie":    (60, 75, 85, 100, 85, 115),
    "Milotic":    (95, 60, 79, 100, 125, 81),
    "Blissey":    (255, 10, 10, 75, 135, 55),
    "Tyranitar":  (100, 134, 110, 95, 100, 61),
    "Machamp":    (90, 130, 80, 65, 85, 55),
    "Heracross":  (80, 125, 75, 40, 95, 85),
    "Gyarados":   (95, 125, 79, 60, 100, 81),
    "Zapdos":     (90, 90, 85, 125, 90, 100),
    "Suicune":    (100, 75, 115, 90, 115, 85),
    "Raikou":     (90, 85, 75, 115, 100, 115),
    "Swampert":   (100, 110, 90, 85, 90, 60),
    "Blaziken":   (80, 120, 70, 110, 70, 80),
    "Gardevoir":  (68, 65, 65, 125, 115, 80),
    "Alakazam":   (55, 50, 45, 135, 95, 120),
    "Vaporeon":   (130, 65, 60, 110, 95, 65),
    "Jolteon":    (65, 65, 60, 110, 95, 130),
    "Dugtrio":    (35, 80, 50, 50, 70, 120),
    "Flygon":     (80, 100, 80, 80, 80, 100),
    "Breloom":    (60, 130, 80, 60, 60, 70),
    "Umbreon":    (95, 65, 110, 60, 130, 65),
    "Espeon":     (65, 65, 60, 130, 95, 110),
    "Clefable":   (95, 70, 73, 95, 90, 60),
    "Lapras":     (130, 85, 80, 85, 95, 60),
    "Dragonite":  (91, 134, 95, 100, 100, 80),
    "Marowak":    (60, 80, 110, 50, 80, 45),
    "Porygon2":   (85, 80, 90, 105, 95, 60),
    "Tauros":     (75, 100, 95, 40, 70, 110),
    "Ninjask":    (61, 90, 45, 50, 50, 160),
}

# Type data
SPECIES_TYPES = {
    "Skarmory":   ("Steel", "Flying"),
    "Gengar":     ("Ghost", "Poison"),
    "Snorlax":    ("Normal", None),
    "Aggron":     ("Steel", "Rock"),
    "Weezing":    ("Poison", None),
    "Metagross":  ("Steel", "Psychic"),
    "Salamence":  ("Dragon", "Flying"),
    "Starmie":    ("Water", "Psychic"),
    "Milotic":    ("Water", None),
    "Blissey":    ("Normal", None),
    "Tyranitar":  ("Rock", "Dark"),
    "Machamp":    ("Fighting", None),
    "Heracross":  ("Bug", "Fighting"),
    "Gyarados":   ("Water", "Flying"),
    "Zapdos":     ("Electric", "Flying"),
    "Suicune":    ("Water", None),
    "Raikou":     ("Electric", None),
    "Swampert":   ("Water", "Ground"),
    "Blaziken":   ("Fire", "Fighting"),
    "Gardevoir":  ("Psychic", None),
    "Alakazam":   ("Psychic", None),
    "Vaporeon":   ("Water", None),
    "Jolteon":    ("Electric", None),
    "Dugtrio":    ("Ground", None),
    "Flygon":     ("Dragon", "Ground"),
    "Breloom":    ("Grass", "Fighting"),
    "Umbreon":    ("Dark", None),
    "Espeon":     ("Psychic", None),
    "Clefable":   ("Normal", None),
    "Lapras":     ("Water", "Ice"),
    "Dragonite":  ("Dragon", "Flying"),
    "Marowak":    ("Ground", None),
    "Porygon2":   ("Normal", None),
    "Tauros":     ("Normal", None),
    "Ninjask":    ("Bug", "Flying"),
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
