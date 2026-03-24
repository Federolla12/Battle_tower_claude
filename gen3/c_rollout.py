"""
Python wrapper for the C rollout simulator via ctypes.

Data-driven: all move data is passed from Python to C at startup via
init_moves_data(), so no recompile is needed when moves are added.
"""
import ctypes, os, sys, random
from .state import BattleState
from .moves import MOVE_DB, MoveDef

_dir = os.path.dirname(__file__)
_lib_name = "rollout.dll" if sys.platform == "win32" else "rollout.so"
_lib_path = os.path.join(_dir, _lib_name)

if not os.path.exists(_lib_path):
    print(f"ERROR: C extension not found at {_lib_path}")
    if sys.platform == "win32":
        print(f"  gcc -O3 -shared -o gen3\\rollout.dll gen3\\rollout.c")
    else:
        print(f"  gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm")
    sys.exit(1)

_lib = ctypes.CDLL(_lib_path)

# ── C structs (must match rollout.c exactly) ─────────────────────────

class CMon(ctypes.Structure):
    _fields_ = [
        ("t1", ctypes.c_int), ("t2", ctypes.c_int),
        ("ab", ctypes.c_int), ("item", ctypes.c_int), ("item_c", ctypes.c_int),
        ("mv", ctypes.c_int * 4), ("mlock", ctypes.c_int),
        ("mhp", ctypes.c_int), ("hp", ctypes.c_int),
        ("atk", ctypes.c_int), ("def_", ctypes.c_int),
        ("spa", ctypes.c_int), ("spd", ctypes.c_int), ("spe", ctypes.c_int),
        ("st", ctypes.c_int), ("st_t", ctypes.c_int),
        ("as_", ctypes.c_int), ("ds", ctypes.c_int),
        ("sas", ctypes.c_int), ("sds", ctypes.c_int), ("ss", ctypes.c_int),
        ("sub", ctypes.c_int), ("taunt", ctypes.c_int), ("flinch", ctypes.c_int),
        ("ldmg", ctypes.c_int), ("lphys", ctypes.c_int),
    ]

class CState(ctypes.Structure):
    _fields_ = [
        ("team", (CMon * 3) * 2),
        ("act", ctypes.c_int * 2),
        ("weath", ctypes.c_int), ("weath_t", ctypes.c_int),
        ("refl", ctypes.c_int * 2), ("ls", ctypes.c_int * 2),
        ("spk", ctypes.c_int * 2),
        ("turn", ctypes.c_int),
    ]

# MV_t struct — must match rollout.c typedef
class CMoveData(ctypes.Structure):
    _fields_ = [
        ("type",    ctypes.c_int),
        ("bp",      ctypes.c_int),
        ("acc",     ctypes.c_int),
        ("pri",     ctypes.c_int),
        ("eff",     ctypes.c_int),
        ("eff_ch",  ctypes.c_int),
        ("boom",    ctypes.c_int),
        ("brk",     ctypes.c_int),
        ("recoil",  ctypes.c_float),
    ]

# ── C function signatures ─────────────────────────────────────────────

_lib.init_moves_data.argtypes = [
    ctypes.POINTER(CMoveData), ctypes.c_int, ctypes.c_int
]
_lib.init_moves_data.restype = None

_lib.run_rollouts.argtypes = [ctypes.POINTER(CState), ctypes.c_int, ctypes.c_uint]
_lib.run_rollouts.restype = ctypes.c_int

# ── Enum maps ─────────────────────────────────────────────────────────

TYPE_MAP = {
    "Normal":0,"Fighting":1,"Flying":2,"Poison":3,"Ground":4,
    "Rock":5,"Bug":6,"Ghost":7,"Steel":8,"Fire":9,"Water":10,
    "Grass":11,"Electric":12,"Psychic":13,"Ice":14,"Dragon":15,
    "Dark":16,None:17,"???":18,
}

STATUS_MAP = {None:0,"burn":1,"paralyze":2,"poison":3,"toxic":4,"freeze":5,"sleep":6}

ITEM_MAP = {
    None:0,
    "Leftovers":1,
    "Choice Band":2,
    "Lum Berry":3,
    "Chesto Berry":4,
    "Sitrus Berry":5,
    "Salac Berry":6,
    "Petaya Berry":7,
    "Liechi Berry":8,
    "BrightPowder":9,
    "Shell Bell":10,
    "Choice Specs":11,
    "White Herb":12,
}

ABILITY_MAP = {
    "None":0,"Keen Eye":1,"Levitate":2,"Thick Fat":3,"Sturdy":4,"Clear Body":5,
    "Intimidate":6,"Natural Cure":7,"Shed Skin":8,
    # Abilities with no special C logic — map to 0 so they're "no-op"
    "Rock Head":0,"Guts":0,"Hustle":0,"Swift Swim":0,"Chlorophyll":0,
    "Sand Stream":0,"Drought":0,"Drizzle":0,"Static":0,"Flame Body":0,
    "Water Absorb":0,"Volt Absorb":0,"Flash Fire":0,"Wonder Guard":0,
    "Arena Trap":0,"Magnet Pull":0,"Synchronize":0,"Own Tempo":0,
    "Hyper Cutter":0,"Battle Armor":0,"Shell Armor":0,"Inner Focus":0,
    "Immunity":0,"Limber":0,"Insomnia":0,"Vital Spirit":0,"Oblivious":0,
    "Sand Veil":0,"Snow Cloak":0,"Run Away":0,"Early Bird":0,
    "Color Change":0,"Compoundeyes":0,"Compound Eyes":0,"Tinted Lens":0,
    "Swarm":0,"Blaze":0,"Torrent":0,"Overgrow":0,"Speed Boost":0,
    "Pressure":0,"Truant":0,"Liquid Ooze":0,"Huge Power":0,"Pure Power":0,
    "Plus":0,"Minus":0,"Forecast":0,"Trace":0,"Shadow Tag":0,
    "Serene Grace":0,"Super Luck":0,"Sniper":0,"No Guard":0,
    "Steadfast":0,"Stall":0,"Skill Link":0,"Reckless":0,"Adaptability":0,
    "Normalize":0,"Soundproof":0,"Damp":0,"Cloud Nine":0,"Illuminate":0,
    "Effect Spore":0,"Pickup":0,"Truant":0,
}

WEATHER_MAP = {None:0,"sun":1,"rain":2,"sand":3,"hail":4}

# ── Effect string → C EF_* integer mapping ───────────────────────────
# These values MUST match the #define EF_* constants in rollout.c

EFFECT_MAP: dict[str | None, int] = {
    None:               0,
    "flinch":           1,
    "burn":             2,
    "paralyze":         3,
    "freeze":           4,
    "poison":           5,
    "spd_minus1":       6,
    "atk_plus1_self":   7,
    "taunt":           10,
    "toxic":           11,
    "counter":         12,
    "substitute":      13,
    "rest":            14,
    "sleep_talk":      15,
    "curse_normal":    16,
    "paralyze_status": 17,
    "burn_status":     18,
    "pain_split":      19,
    "focus_punch":     20,
    "sleep_status":    21,
    "recover_half":    22,
    "atk_plus2_self":  23,
    "atk_spe_plus1_self": 24,
    "spa_spd_plus1_self": 25,
    "spe_plus2_self":  26,
    "spd_plus2_self":  27,
    "all_stats_plus1_self": 28,
    "confuse":         29,
    "confuse_status":  30,
    "ohko":            31,
    "seismic_toss":    32,
    "night_shade":     32,   # same fixed-damage logic
    "lay_spikes":      33,
    "def_minus2_opp":  34,
    "spe_minus2_opp":  35,
    "spd_minus2_opp":  36,
    "atk_minus1_opp":  37,
    "atk_minus2_opp":  38,
    "def_minus1_opp":  39,
    "spe_minus1":      40,
    "def_plus1_self":  41,
    "spa_minus1":      42,
    "spa_minus2_self": 43,
    "atk_def_minus1_self": 44,
    "atk_def_minus1_opp":  45,
    "rain_dance":      46,
    "sunny_day":       47,
    "hail":            48,
    "sandstorm_move":  49,
    "roar":            50,
    "haze":            51,
    "psych_up":        52,
    "swagger":         53,
    "belly_drum":      54,
    "spa_plus3_self":  55,
    "atk_def_plus1_self": 56,
    "def_spd_plus1_self": 57,
    "def_plus2_self":  58,
    "mirror_coat":     59,
    "leech_seed":      60,
    # Howl / Meditate → +1 Atk (same as atk_plus1_self)
    "atk_plus1_self_status": 7,
    # Stubs: all map to EF_NONE (0) — no-op in rollouts
    "attract":         0,
    "protect":         0,
    "endure":          0,
    "baton_pass":      0,
    "destiny_bond":    0,
    "skill_swap":      0,
    "trick":           0,
    "memento":         0,
    "encore":          0,
    "disable":         0,
    "perish_song":     0,
    "trap":            0,
    "follow_me":       0,
    "metronome":       0,
    "role_play":       0,
    "recycle":         0,
    "grudge":          0,
    "spite":           0,
    "torment":         0,
    "imprison":        0,
    "evasion_plus1":   0,
    "acc_minus1":      0,
    "safeguard":       0,
    "reflect":         0,
    "light_screen":    0,
    "dream_eater":     0,  # drain handled via recoil=-0.5 in move def
}

# ── Build move index and C data array from MOVE_DB ───────────────────

def _build_move_data():
    """
    Assign each move in MOVE_DB a sequential integer index and build
    the CMoveData array to pass to C.  Returns (MOVE_INDEX, array, struggle_idx).
    """
    # Stable ordering: sort by insertion-order equivalent (dict preserves insertion in 3.7+)
    names = list(MOVE_DB.keys())

    MOVE_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(names)}

    arr = (CMoveData * len(names))()
    for idx, name in enumerate(names):
        m: MoveDef = MOVE_DB[name]
        c = arr[idx]
        c.type   = TYPE_MAP.get(m.type, 0)
        c.bp     = m.base_power
        c.acc    = m.accuracy
        c.pri    = m.priority
        c.eff    = EFFECT_MAP.get(m.effect, 0)
        c.eff_ch = m.effect_chance
        c.boom   = int(m.is_explosion)
        c.brk    = int(m.breaks_screens)
        c.recoil = m.recoil

    struggle_idx = MOVE_INDEX.get("Struggle", 0)
    return MOVE_INDEX, arr, struggle_idx

MOVE_INDEX, _MOVE_ARRAY, _STRUGGLE_IDX = _build_move_data()

# Keep the array alive at module level so C doesn't get a dangling pointer
_lib.init_moves_data(_MOVE_ARRAY, len(MOVE_INDEX), _STRUGGLE_IDX)

# ── State conversion ──────────────────────────────────────────────────

def _conv_mon(py) -> CMon:
    c = CMon()
    c.t1 = TYPE_MAP.get(py.types[0], 0)
    c.t2 = TYPE_MAP.get(py.types[1], 17)  # 17 = T_NONE
    c.ab = ABILITY_MAP.get(py.ability, 0)
    c.item = ITEM_MAP.get(py.item, 0)
    c.item_c = int(py.item_consumed)
    for i, mv in enumerate(py.moves[:4]):
        c.mv[i] = MOVE_INDEX.get(mv, _STRUGGLE_IDX)
    c.mlock = MOVE_INDEX.get(py.move_locked, -1) if py.move_locked else -1
    c.mhp = py.max_hp
    c.hp  = py.current_hp
    c.atk = py.base_atk
    c.def_ = py.base_def
    c.spa = py.base_spa
    c.spd = py.base_spd
    c.spe = py.base_spe
    c.st   = STATUS_MAP.get(py.status, 0)
    c.st_t = py.status_turns
    c.as_  = py.atk_stage
    c.ds   = py.def_stage
    c.sas  = py.spa_stage
    c.sds  = py.spd_stage
    c.ss   = py.spe_stage
    c.sub  = py.substitute_hp
    c.taunt = py.taunt_turns
    c.flinch = int(py.flinched)
    c.ldmg  = py.last_damage_taken
    c.lphys = int(py.last_damage_physical)
    return c


def convert_state(py: BattleState) -> CState:
    c = CState()
    for p in range(2):
        team = py.team_p1 if p == 0 else py.team_p2
        for i, mon in enumerate(team):
            c.team[p][i] = _conv_mon(mon)
    c.act[0] = py.active_p1
    c.act[1] = py.active_p2
    c.weath   = WEATHER_MAP.get(py.weather, 0)
    c.weath_t = py.weather_turns
    c.refl[0] = py.field_p1.reflect_turns
    c.refl[1] = py.field_p2.reflect_turns
    c.ls[0]   = py.field_p1.light_screen_turns
    c.ls[1]   = py.field_p2.light_screen_turns
    c.spk[0]  = py.field_p1.spikes
    c.spk[1]  = py.field_p2.spikes
    c.turn    = py.turn_number
    return c


def c_rollout(state: BattleState, n_sims: int, seed: int | None = None) -> float:
    """Run MC rollouts via C extension. Returns P1 win probability."""
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    c = convert_state(state)
    wins = _lib.run_rollouts(ctypes.byref(c), n_sims, seed)
    return wins / n_sims if n_sims > 0 else 0.5
