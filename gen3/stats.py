"""
Gen 3 Stat Calculator
=====================
Computes final stats at level 50 from base stats, nature, EVs, and IVs.
Base stats and types are loaded from pokedex_gen3.json (extracted from Showdown).
"""

import math
import json
import os
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


# ============================================================
# Load full Gen 3 Pokedex from JSON
# ============================================================

_POKEDEX_PATH = os.path.join(os.path.dirname(__file__), "pokedex_gen3.json")

def _load_pokedex():
    """Load base stats and types for all 386 Gen 3 species."""
    with open(_POKEDEX_PATH) as f:
        raw = json.load(f)

    base_stats = {}
    species_types = {}

    for name, data in raw.items():
        base_stats[name] = (
            data["hp"], data["atk"], data["def"],
            data["spa"], data["spd"], data["spe"],
        )
        species_types[name] = (data["type1"], data.get("type2"))

    return base_stats, species_types


BASE_STATS, SPECIES_TYPES = _load_pokedex()


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
        level: Battle level (default 50)

    Returns:
        Dict with keys: hp, atk, def, spa, spd, spe
    """
    if species not in BASE_STATS:
        raise ValueError(f"Unknown species: {species}. "
                         f"Check gen3/pokedex_gen3.json has it.")
    base = BASE_STATS[species]
    if ivs is None:
        ivs = {}

    stat_names = ["hp", "atk", "def", "spa", "spd", "spe"]

    # Shedinja special case
    result = {}
    for i, name in enumerate(stat_names):
        base_val = base[i]
        iv = ivs.get(name, 31)
        ev = evs.get(name, 0)

        if name == "hp":
            result[name] = calc_hp(base_val, iv, ev, level)
        else:
            result[name] = calc_stat(base_val, iv, ev, nature, name, level)

    if species == "Shedinja":
        result["hp"] = 1

    return result
