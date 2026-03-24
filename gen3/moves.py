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


# ============================================================
# Common coverage moves
# ============================================================

_m("Surf", "Water", 95, 100, 15)
_m("Ice Beam", "Ice", 95, 100, 10,
   effect="freeze", eff_chance=10)
_m("Thunderbolt", "Electric", 95, 100, 15,
   effect="paralyze", eff_chance=10)
_m("Flamethrower", "Fire", 95, 100, 15,
   effect="burn", eff_chance=10)
_m("Shadow Ball", "Ghost", 80, 100, 15,
   effect="spd_minus1", eff_chance=20)
_m("Hyper Voice", "Normal", 90, 100, 10, sound=True)
_m("Crunch", "Dark", 80, 100, 15, contact=True,
   effect="spd_minus1", eff_chance=20)
_m("Return", "Normal", 102, 100, 20, contact=True)
_m("Double-Edge", "Normal", 100, 100, 15, contact=True,
   recoil=1/3)
_m("Dragon Claw", "Dragon", 80, 100, 15, contact=True)
_m("Aerial Ace", "Flying", 60, 0, 20, contact=True)   # acc=0 = never miss
_m("Thunderpunch", "Electric", 75, 100, 15, contact=True,
   effect="paralyze", eff_chance=10)
_m("Waterfall", "Water", 80, 100, 15, contact=True,
   effect="flinch", eff_chance=20)
_m("Dragon Breath", "Dragon", 60, 100, 20,
   effect="paralyze", eff_chance=30)
_m("Iron Tail", "Steel", 100, 75, 15, contact=True,
   effect="def_minus1", eff_chance=30)
_m("Rock Tomb", "Rock", 50, 80, 10,
   effect="spe_minus1", eff_chance=100)
_m("Ancient Power", "Rock", 60, 100, 5,
   effect="all_stats_plus1_self", eff_chance=10)
_m("Silver Wind", "Bug", 60, 100, 5,
   effect="all_stats_plus1_self", eff_chance=10)

# Fixed-damage moves (base_power=0 routes through execute_status_move)
_m("Seismic Toss", "Normal", 0, 100, 20, contact=True,
   effect="seismic_toss")
_m("Night Shade", "Ghost", 0, 100, 15, cat="special",
   effect="night_shade")

# ============================================================
# Setup / boost moves
# ============================================================

_m("Swords Dance", "Normal", 0, 0, 30, effect="atk_plus2_self")
_m("Dragon Dance", "Dragon", 0, 0, 20, effect="atk_spe_plus1_self")
_m("Calm Mind", "Psychic", 0, 0, 20, effect="spa_spd_plus1_self")
_m("Agility", "Psychic", 0, 0, 30, effect="spe_plus2_self")
_m("Amnesia", "Psychic", 0, 0, 20, effect="spd_plus2_self")

# ============================================================
# Recovery moves
# ============================================================

_m("Recover", "Normal", 0, 0, 20, effect="recover_half")
_m("Softboiled", "Normal", 0, 0, 10, effect="recover_half")
_m("Moonlight", "Normal", 0, 0, 5, effect="recover_half")   # weather modifier ignored
_m("Morning Sun", "Normal", 0, 0, 5, effect="recover_half")
_m("Synthesis", "Grass", 0, 0, 5, effect="recover_half")

# ============================================================
# Status-inflicting moves
# ============================================================

_m("Confuse Ray", "Ghost", 0, 100, 10, effect="confuse_status")
_m("Spore", "Grass", 0, 100, 15, effect="sleep_status")
_m("Hypnosis", "Psychic", 0, 60, 20, effect="sleep_status")

# ============================================================
# Entry-hazard move (laying Spikes — damage-on-switch already implemented)
# ============================================================

_m("Spikes", "Ground", 0, 0, 20, effect="lay_spikes")


# ============================================================
# Battle Frontier expanded move set
# ============================================================

# --- High-power coverage ---
_m("Blizzard",     "Ice",      120, 70, 5,  effect="freeze",    eff_chance=10)
_m("Hydro Pump",   "Water",    120, 80, 5)
_m("Thunder",      "Electric", 120, 70, 10, effect="paralyze",  eff_chance=30)
_m("Megahorn",     "Bug",      120, 85, 10, contact=True)
_m("Hyper Beam",   "Normal",   150, 90, 5)          # recharge simplified away
_m("Overheat",     "Fire",     140, 90, 5,  effect="spa_minus2_self", eff_chance=100)
_m("Heat Wave",    "Fire",     100, 90, 10, effect="burn",      eff_chance=10)
_m("Superpower",   "Fighting", 120, 100, 5, contact=True,
   effect="atk_def_minus1_self", eff_chance=100)
_m("Mega Kick",    "Normal",   120, 75, 5,  contact=True)
_m("SolarBeam",    "Grass",    120, 100, 10)         # 2-turn simplified
_m("Solar Beam",   "Grass",    120, 100, 10)

# --- Mid-power coverage ---
_m("Cross Chop",   "Fighting", 100, 80, 5,  contact=True)
_m("Sky Uppercut", "Fighting",  85, 90, 15, contact=True)
_m("Blaze Kick",   "Fire",      85, 90, 10, contact=True, effect="burn", eff_chance=10)
_m("Drill Peck",   "Flying",    80, 100, 20, contact=True)
_m("Signal Beam",  "Bug",       75, 100, 15, effect="confuse",  eff_chance=10)
_m("Headbutt",     "Normal",    70, 100, 15, contact=True, effect="flinch", eff_chance=30)
_m("Steel Wing",   "Steel",     70, 90,  25, contact=True,
   effect="def_plus1_self", eff_chance=10)
_m("Slash",        "Normal",    70, 100, 20, contact=True)   # high crit simplified
_m("Frustration",  "Normal",   102, 100, 20, contact=True)   # same power as Return
_m("Facade",       "Normal",    70, 100, 20, contact=True)   # status-doubling simplified
_m("Tri Attack",   "Normal",    80, 100, 10, effect="paralyze", eff_chance=7)  # simplified
_m("Shock Wave",   "Electric",  60, 0,   20)                 # acc=0 never miss
_m("Magical Leaf", "Grass",     60, 0,   20)
_m("Faint Attack", "Dark",      60, 0,   20, contact=True)
_m("Outrage",      "Dragon",    90, 100, 15, contact=True)   # confusion after simplified
_m("Thrash",       "Normal",    90, 100, 20, contact=True)
_m("Dive",         "Water",     80, 100, 10, contact=True)   # 2-turn simplified
_m("Fly",          "Flying",    70, 95,  15, contact=True)   # 2-turn simplified
_m("Dig",          "Ground",    60, 100, 10, contact=True)   # 2-turn simplified
_m("Bone Club",    "Ground",    65, 85,  20, effect="flinch", eff_chance=10)
_m("Bonemerang",   "Ground",    50, 90,  10)                 # 2 hits simplified to 1
_m("Double Kick",  "Fighting",  60, 100, 30, contact=True)   # 2 hits at 30 each
_m("Mist Ball",    "Psychic",   70, 100, 5,  effect="spa_minus1", eff_chance=50)
_m("Luster Purge", "Psychic",   70, 100, 5,  effect="spd_minus1", eff_chance=50)
_m("Bite",         "Dark",      60, 100, 25, contact=True, effect="flinch", eff_chance=30)
_m("Leech Life",   "Bug",       20, 100, 15, contact=True,  recoil=-0.5)
_m("Selfdestruct", "Normal",   200, 100, 5,  explosion=True)

# --- Priority moves ---
_m("Quick Attack",  "Normal",   40, 100, 30, pri=1, contact=True)
_m("Mach Punch",    "Fighting", 40, 100, 30, pri=1, contact=True)
_m("ExtremeSpeed",  "Normal",   80, 100, 5,  pri=2, contact=True)
_m("Extreme Speed", "Normal",   80, 100, 5,  pri=2, contact=True)

# --- Low-power coverage ---
_m("Icy Wind",     "Ice",       55, 95, 15, effect="spe_minus1",  eff_chance=100)
_m("Air Cutter",   "Flying",    55, 95, 25)
_m("Mud Shot",     "Ground",    55, 95, 15, effect="spe_minus1",  eff_chance=100)
_m("Sand Tomb",    "Ground",    35, 85, 15)                  # trap simplified away
_m("Dream Eater",  "Psychic",   100, 100, 15, recoil=-0.5)  # only works vs sleeping

# --- OHKO ---
_m("Fissure",    "Normal", 0, 30, 5, effect="ohko")
_m("Sheer Cold", "Ice",    0, 30, 5, effect="ohko")
_m("Horn Drill", "Normal", 0, 30, 5, effect="ohko")

# --- Setup / boost moves ---
_m("Bulk Up",      "Fighting", 0, 0, 20, effect="atk_def_plus1_self")
_m("Cosmic Power", "Psychic",  0, 0, 20, effect="def_spd_plus1_self")
_m("Acid Armor",   "Poison",   0, 0, 40, effect="def_plus2_self")
_m("Belly Drum",   "Normal",   0, 0, 10, effect="belly_drum")
_m("Tail Glow",    "Bug",      0, 0, 20, effect="spa_plus3_self")  # Gen 3: +3 SpA
_m("Howl",         "Normal",   0, 0, 40, effect="atk_plus1_self_status")
_m("Meditate",     "Psychic",  0, 0, 40, effect="atk_plus1_self_status")

# --- Weather ---
_m("Rain Dance",   "Water",    0, 0, 5,  effect="rain_dance")
_m("Sunny Day",    "Fire",     0, 0, 5,  effect="sunny_day")
_m("Hail",         "Ice",      0, 0, 10, effect="hail")
_m("Sandstorm",    "Rock",     0, 0, 10, effect="sandstorm_move")

# --- Screens / field ---
_m("Reflect",      "Psychic",  0, 0, 20, effect="reflect")
_m("Light Screen", "Psychic",  0, 0, 30, effect="light_screen")
_m("Safeguard",    "Normal",   0, 0, 25, effect="safeguard")

# --- Opponent stat drops (status moves) ---
_m("Screech",      "Normal",   0, 85, 40, effect="def_minus2_opp",  sound=True)
_m("Scary Face",   "Normal",   0, 90, 10, effect="spe_minus2_opp")
_m("Metal Sound",  "Steel",    0, 85, 40, effect="spd_minus2_opp",  sound=True)
_m("Swagger",      "Normal",   0, 90, 15, effect="swagger")
_m("Flatter",      "Dark",     0, 100, 15, effect="swagger")   # same simplified effect
_m("Leer",         "Normal",   0, 100, 30, effect="def_minus1_opp")
_m("Growl",        "Normal",   0, 100, 40, effect="atk_minus1_opp")
_m("Charm",        "Normal",   0, 100, 20, effect="atk_minus2_opp")
_m("Cotton Spore", "Grass",    0, 85, 40, effect="spe_minus2_opp")
_m("Fake Tears",   "Dark",     0, 100, 20, effect="spd_minus2_opp")
_m("Tickle",       "Normal",   0, 100, 20, effect="atk_def_minus1_opp")

# --- Status-inflicting ---
_m("Stun Spore",   "Grass",    0, 75, 30,  effect="paralyze_status")
_m("Glare",        "Normal",   0, 75, 30,  effect="paralyze_status")
_m("Sleep Powder", "Grass",    0, 75, 15,  effect="sleep_status")
_m("GrassWhistle", "Grass",    0, 55, 15,  effect="sleep_status")
_m("Lovely Kiss",  "Normal",   0, 75, 10,  effect="sleep_status")
_m("Sing",         "Normal",   0, 55, 15,  effect="sleep_status")
_m("Yawn",         "Normal",   0, 0,  10,  effect="sleep_status")  # simplified: no delay
_m("Leech Seed",   "Grass",    0, 90, 10,  effect="leech_seed")

# --- Recovery ---
_m("Milk Drink",   "Normal",   0, 0, 10, effect="recover_half")
_m("Wish",         "Normal",   0, 0, 10, effect="recover_half")   # simplified: instant

# --- Mirror / Counter ---
_m("Mirror Coat",  "Psychic",  0, 100, 20, pri=-5, cat="special", effect="mirror_coat")

# --- Utility ---
_m("Roar",         "Normal",   0, 0, 20,  pri=-5, effect="roar")
_m("Whirlwind",    "Normal",   0, 0, 20,  pri=-5, effect="roar")
_m("Haze",         "Ice",      0, 0, 30,  effect="haze")
_m("Psych Up",     "Normal",   0, 0, 10,  effect="psych_up")
_m("Swagger",      "Normal",   0, 90, 15, effect="swagger")       # already added above

# --- Evasion / accuracy modifiers (simplified as no-op misses) ---
_m("Double Team",   "Normal",  0, 0,  15, effect="evasion_plus1")
_m("Minimize",      "Normal",  0, 0,  20, effect="evasion_plus1")
_m("Sand-Attack",   "Ground",  0, 100, 15, effect="acc_minus1")
_m("Flash",         "Normal",  0, 70,  20, effect="acc_minus1")
_m("SmokeScreen",   "Normal",  0, 100, 20, effect="acc_minus1")
_m("Sweet Scent",   "Normal",  0, 100, 20, effect="acc_minus1")
_m("Tail Whip",     "Normal",  0, 100, 30, effect="def_minus1_opp")  # same as Leer

# --- Complex mechanics (stubs — no-op) ---
_m("Attract",       "Normal",  0, 100, 15, effect="attract")
_m("Protect",       "Normal",  0, 0,   10, pri=4, effect="protect")
_m("Detect",        "Fighting",0, 0,   5,  pri=4, effect="protect")
_m("Endure",        "Normal",  0, 0,   10, pri=4, effect="endure")
_m("Baton Pass",    "Normal",  0, 0,   40, effect="baton_pass")
_m("Destiny Bond",  "Ghost",   0, 0,   5,  effect="destiny_bond")
_m("Skill Swap",    "Psychic", 0, 100, 10, effect="skill_swap")
_m("Trick",         "Psychic", 0, 100, 10, effect="trick")
_m("Memento",       "Dark",    0, 100, 10, effect="memento")
_m("Encore",        "Normal",  0, 100, 5,  effect="encore")
_m("Disable",       "Normal",  0, 55,  20, effect="disable")
_m("Perish Song",   "Normal",  0, 0,   5,  sound=True, effect="perish_song")
_m("Mean Look",     "Normal",  0, 0,   5,  effect="trap")
_m("Block",         "Normal",  0, 0,   5,  effect="trap")
_m("Follow Me",     "Normal",  0, 0,   20, effect="follow_me")
_m("Metronome",     "Normal",  0, 0,   10, effect="metronome")
_m("Role Play",     "Psychic", 0, 0,   10, effect="role_play")
_m("Psych Up",      "Normal",  0, 0,   10, effect="psych_up")
_m("Recycle",       "Normal",  0, 0,   10, effect="recycle")
_m("Grudge",        "Ghost",   0, 0,   5,  effect="grudge")
_m("Spite",         "Ghost",   0, 100, 10, effect="spite")
_m("Torment",       "Dark",    0, 100, 15, effect="torment")
_m("Imprison",      "Psychic", 0, 0,   10, effect="imprison")
_m("Psywave",       "Psychic", 0, 80,  15, effect="seismic_toss")  # simplified
_m("SonicBoom",     "Normal",  0, 90,  20, effect="seismic_toss")  # simplified
_m("Dragon Rage",   "Dragon",  0, 100, 10, effect="seismic_toss")  # simplified
_m("Reversal",      "Fighting",1, 100, 15, contact=True)  # simplified: min damage
_m("Flail",         "Normal",  1, 100, 15, contact=True)  # simplified: min damage
_m("Endeavor",      "Normal",  0, 100, 5,  contact=True, effect="seismic_toss")
_m("Revenge",       "Fighting",60, 100, 10, contact=True)   # priority -1 simplified

# --- Aliases for Bulbapedia name variants ---
_m("AncientPower",  "Rock",    60, 100, 5, effect="all_stats_plus1_self", eff_chance=10)
_m("DragonBreath",  "Dragon",  60, 100, 20, effect="paralyze", eff_chance=30)
_m("ThunderPunch",  "Electric",75, 100, 15, contact=True, effect="paralyze", eff_chance=10)
_m("BubbleBeam",    "Water",   65, 100, 20, effect="spe_minus1", eff_chance=10)
_m("DoubleSlap",    "Normal",  15, 85,  10, contact=True)
_m("DynamicPunch",  "Fighting",100, 50, 5,  contact=True, effect="confuse", eff_chance=100)
_m("Headbutt",      "Normal",  70, 100, 15, contact=True, effect="flinch", eff_chance=30)


def get_move(name: str) -> MoveDef:
    """Look up a move by name. Raises KeyError if not found."""
    return MOVE_DB[name]
