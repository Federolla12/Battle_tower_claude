"""
Gen 3 Move Definitions
======================
Data for all moves used by both teams. Each move is defined with its
mechanical properties — the executor uses these to resolve effects.
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class MoveDef:
    name: str
    type: str                     # "Fire", "Ground", etc.
    base_power: int               # 0 for status moves
    accuracy: int                 # 1-100, or 0 = never miss
    pp: int
    priority: int                 # -6 to +5
    category: str                 # "physical" | "special" | "status"
                                  # Overrides the Gen 3 type-based rule for
                                  # Counter (special case) and status moves
    contact: bool                 # Makes contact (triggers Static, etc.)
    # Secondary effect
    effect: Optional[str]         # Effect key (see EFFECTS below)
    effect_chance: int            # 0-100, chance of secondary effect
    # Special flags
    recoil: float                 # Fraction of damage dealt as recoil (neg = drain)
    is_explosion: bool            # User faints, halve target Def
    breaks_screens: bool          # Removes Reflect/Light Screen
    sound: bool                   # Bypasses Substitute


# Move database — keyed by move name
MOVE_DB: dict[str, MoveDef] = {}

def _m(name, type, bp, acc, pp, pri=0, cat=None, contact=False,
       effect=None, eff_chance=0, recoil=0.0,
       explosion=False, breaks_screens=False, sound=False):
    """Helper to register a move."""
    from .types import move_category
    if cat is None:
        cat = move_category(type) if bp > 0 else "status"
    MOVE_DB[name] = MoveDef(
        name=name, type=type, base_power=bp, accuracy=acc, pp=pp,
        priority=pri, category=cat, contact=contact,
        effect=effect, effect_chance=eff_chance,
        recoil=recoil, is_explosion=explosion,
        breaks_screens=breaks_screens, sound=sound,
    )


# ============================================================
# Team 1: Skarmory
# ============================================================

_m("Hidden Power", "Ground", 70, 100, 15,
   contact=False)

_m("Taunt", "Dark", 0, 100, 20,
   effect="taunt")

_m("Counter", "Fighting", 0, 100, 20, pri=-5,
   cat="physical",  # special case: Counter is physical category
   effect="counter", contact=True)

_m("Toxic", "Poison", 0, 85, 10,
   effect="toxic")

# ============================================================
# Team 1: Gengar
# ============================================================

_m("Giga Drain", "Grass", 60, 100, 5,
   recoil=-0.5)   # Negative recoil = drain 50% of damage dealt

_m("Psychic", "Psychic", 90, 100, 10,
   effect="spd_minus1", eff_chance=10, contact=False)

_m("Ice Punch", "Ice", 75, 100, 15,
   effect="freeze", eff_chance=10, contact=True)

_m("Fire Punch", "Fire", 75, 100, 15,
   effect="burn", eff_chance=10, contact=True)

# ============================================================
# Team 1: Snorlax
# ============================================================

_m("Rest", "Psychic", 0, 0, 10,  # never-miss (targets self)
   effect="rest")

_m("Sleep Talk", "Normal", 0, 0, 10,
   effect="sleep_talk")

_m("Curse", "???", 0, 0, 10,
   effect="curse_normal")  # Non-Ghost Curse: +1 Atk, +1 Def, -1 Spe

_m("Body Slam", "Normal", 85, 100, 15,
   effect="paralyze", eff_chance=30, contact=True)

# ============================================================
# Team 2: Aggron
# ============================================================

_m("Rock Slide", "Rock", 75, 90, 10,
   effect="flinch", eff_chance=30, contact=False)

_m("Substitute", "Normal", 0, 0, 10,
   effect="substitute")

_m("Focus Punch", "Fighting", 150, 100, 20, pri=-3,
   effect="focus_punch", contact=True)

_m("Thunder Wave", "Electric", 0, 100, 20,
   effect="paralyze_status")

# ============================================================
# Team 2: Weezing
# ============================================================

_m("Will-O-Wisp", "Fire", 0, 75, 15,
   effect="burn_status")

_m("Fire Blast", "Fire", 120, 85, 5,
   effect="burn", eff_chance=10, contact=False)

_m("Sludge Bomb", "Poison", 90, 100, 10,
   effect="poison", eff_chance=30, contact=False)

_m("Pain Split", "Normal", 0, 0, 20,
   effect="pain_split")

# ============================================================
# Team 2: Metagross
# ============================================================

_m("Meteor Mash", "Steel", 100, 85, 10,
   effect="atk_plus1_self", eff_chance=20, contact=True)

_m("Earthquake", "Ground", 100, 100, 10,
   contact=False)

_m("Brick Break", "Fighting", 75, 100, 15,
   breaks_screens=True, contact=True)

_m("Explosion", "Normal", 250, 100, 5,
   explosion=True, contact=False)


def get_move(name: str) -> MoveDef:
    """Look up a move by name. Raises KeyError if not found."""
    return MOVE_DB[name]
