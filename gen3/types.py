"""
Gen 3 Type System
=================
Type effectiveness chart and physical/special classification.
"""

# Gen 3: move category is determined by TYPE, not by individual move
PHYSICAL_TYPES = frozenset([
    "Normal", "Fighting", "Flying", "Poison", "Ground",
    "Rock", "Bug", "Ghost", "Steel"
])
SPECIAL_TYPES = frozenset([
    "Fire", "Water", "Grass", "Electric", "Psychic",
    "Ice", "Dragon", "Dark"
])

ALL_TYPES = PHYSICAL_TYPES | SPECIAL_TYPES


def move_category(move_type: str) -> str:
    """Returns 'physical' or 'special' based on the move's type (Gen 3 rule)."""
    if move_type in PHYSICAL_TYPES:
        return "physical"
    elif move_type in SPECIAL_TYPES:
        return "special"
    raise ValueError(f"Unknown type: {move_type}")


# Type effectiveness chart: TYPE_CHART[(atk_type, def_type)] = multiplier
# Only non-1.0 entries are stored; missing = 1.0 (neutral)
_CHART_DATA = {
    # Normal
    ("Normal", "Rock"): 0.5, ("Normal", "Ghost"): 0.0, ("Normal", "Steel"): 0.5,
    # Fighting
    ("Fighting", "Normal"): 2.0, ("Fighting", "Flying"): 0.5, ("Fighting", "Poison"): 0.5,
    ("Fighting", "Rock"): 2.0, ("Fighting", "Bug"): 0.5, ("Fighting", "Ghost"): 0.0,
    ("Fighting", "Steel"): 2.0, ("Fighting", "Psychic"): 0.5, ("Fighting", "Ice"): 2.0,
    ("Fighting", "Dark"): 2.0,
    # Flying
    ("Flying", "Fighting"): 2.0, ("Flying", "Rock"): 0.5, ("Flying", "Bug"): 2.0,
    ("Flying", "Steel"): 0.5, ("Flying", "Grass"): 2.0, ("Flying", "Electric"): 0.5,
    # Poison
    ("Poison", "Poison"): 0.5, ("Poison", "Ground"): 0.5, ("Poison", "Rock"): 0.5,
    ("Poison", "Ghost"): 0.5, ("Poison", "Steel"): 0.0, ("Poison", "Grass"): 2.0,
    # Ground
    ("Ground", "Flying"): 0.0, ("Ground", "Bug"): 0.5, ("Ground", "Steel"): 2.0,
    ("Ground", "Fire"): 2.0, ("Ground", "Grass"): 0.5, ("Ground", "Electric"): 2.0,
    ("Ground", "Poison"): 2.0, ("Ground", "Rock"): 2.0,
    # Rock
    ("Rock", "Fighting"): 0.5, ("Rock", "Ground"): 0.5, ("Rock", "Steel"): 0.5,
    ("Rock", "Fire"): 2.0, ("Rock", "Flying"): 2.0, ("Rock", "Bug"): 2.0,
    ("Rock", "Ice"): 2.0,
    # Bug
    ("Bug", "Fighting"): 0.5, ("Bug", "Flying"): 0.5, ("Bug", "Poison"): 0.5,
    ("Bug", "Ghost"): 0.5, ("Bug", "Steel"): 0.5, ("Bug", "Fire"): 0.5,
    ("Bug", "Grass"): 2.0, ("Bug", "Psychic"): 2.0, ("Bug", "Dark"): 2.0,
    # Ghost
    ("Ghost", "Normal"): 0.0, ("Ghost", "Ghost"): 2.0, ("Ghost", "Steel"): 0.5,
    ("Ghost", "Psychic"): 2.0, ("Ghost", "Dark"): 0.5,
    # Steel
    ("Steel", "Steel"): 0.5, ("Steel", "Fire"): 0.5, ("Steel", "Water"): 0.5,
    ("Steel", "Electric"): 0.5, ("Steel", "Rock"): 2.0, ("Steel", "Ice"): 2.0,
    # Fire
    ("Fire", "Rock"): 0.5, ("Fire", "Bug"): 2.0, ("Fire", "Steel"): 2.0,
    ("Fire", "Fire"): 0.5, ("Fire", "Water"): 0.5, ("Fire", "Grass"): 2.0,
    ("Fire", "Ice"): 2.0, ("Fire", "Dragon"): 0.5,
    # Water
    ("Water", "Ground"): 2.0, ("Water", "Rock"): 2.0, ("Water", "Fire"): 2.0,
    ("Water", "Water"): 0.5, ("Water", "Grass"): 0.5, ("Water", "Dragon"): 0.5,
    # Grass
    ("Grass", "Flying"): 0.5, ("Grass", "Poison"): 0.5, ("Grass", "Ground"): 2.0,
    ("Grass", "Rock"): 2.0, ("Grass", "Bug"): 0.5, ("Grass", "Steel"): 0.5,
    ("Grass", "Fire"): 0.5, ("Grass", "Water"): 2.0, ("Grass", "Grass"): 0.5,
    ("Grass", "Dragon"): 0.5,
    # Electric
    ("Electric", "Flying"): 2.0, ("Electric", "Ground"): 0.0, ("Electric", "Steel"): 0.5,
    ("Electric", "Water"): 2.0, ("Electric", "Grass"): 0.5, ("Electric", "Electric"): 0.5,
    ("Electric", "Dragon"): 0.5,
    # Psychic
    ("Psychic", "Fighting"): 2.0, ("Psychic", "Poison"): 2.0, ("Psychic", "Steel"): 0.5,
    ("Psychic", "Psychic"): 0.5, ("Psychic", "Dark"): 0.0,
    # Ice
    ("Ice", "Flying"): 2.0, ("Ice", "Ground"): 2.0, ("Ice", "Steel"): 0.5,
    ("Ice", "Fire"): 0.5, ("Ice", "Water"): 0.5, ("Ice", "Ice"): 0.5,
    ("Ice", "Grass"): 2.0, ("Ice", "Dragon"): 2.0,
    # Dragon
    ("Dragon", "Steel"): 0.5, ("Dragon", "Dragon"): 2.0,
    # Dark
    ("Dark", "Fighting"): 0.5, ("Dark", "Ghost"): 2.0, ("Dark", "Steel"): 0.5,
    ("Dark", "Psychic"): 2.0, ("Dark", "Dark"): 0.5,
}


def type_effectiveness(atk_type: str, def_type1: str, def_type2: str = None) -> float:
    """
    Compute the type effectiveness multiplier.
    Returns 0.0, 0.25, 0.5, 1.0, 2.0, or 4.0.
    """
    mult = _CHART_DATA.get((atk_type, def_type1), 1.0)
    if def_type2 and def_type2 != def_type1:
        mult *= _CHART_DATA.get((atk_type, def_type2), 1.0)
    return mult
