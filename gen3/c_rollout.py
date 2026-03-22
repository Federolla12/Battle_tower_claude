"""
Python wrapper for the C rollout simulator via ctypes.
"""
import ctypes, os, sys, random
from .state import BattleState

_dir = os.path.dirname(__file__)
_lib_name = "rollout.dll" if sys.platform == "win32" else "rollout.so"
_lib_path = os.path.join(_dir, _lib_name)

if not os.path.exists(_lib_path):
    print(f"ERROR: C extension not found at {_lib_path}")
    print(f"Compile it first:")
    if sys.platform == "win32":
        print(f"  gcc -O3 -shared -o gen3\\rollout.dll gen3\\rollout.c")
    else:
        print(f"  gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm")
    sys.exit(1)

_lib = ctypes.CDLL(_lib_path)

# C structs (must match rollout.c exactly)
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

_lib.run_rollouts.argtypes = [ctypes.POINTER(CState), ctypes.c_int, ctypes.c_uint]
_lib.run_rollouts.restype = ctypes.c_int

# Enum mappings
TYPE_MAP = {"Normal":0,"Fighting":1,"Flying":2,"Poison":3,"Ground":4,"Rock":5,"Bug":6,"Ghost":7,"Steel":8,"Fire":9,"Water":10,"Grass":11,"Electric":12,"Psychic":13,"Ice":14,"Dragon":15,"Dark":16,None:17,"???":18}
STATUS_MAP = {None:0,"burn":1,"paralyze":2,"poison":3,"toxic":4,"freeze":5,"sleep":6}
ITEM_MAP = {None:0,"Leftovers":1,"Choice Band":2,"Lum Berry":3,"Chesto Berry":4}
ABILITY_MAP = {"None":0,"Keen Eye":1,"Levitate":2,"Thick Fat":3,"Sturdy":4,"Clear Body":5}
MOVE_MAP = {"Hidden Power":0,"Taunt":1,"Counter":2,"Toxic":3,"Giga Drain":4,"Psychic":5,"Ice Punch":6,"Fire Punch":7,"Rest":8,"Sleep Talk":9,"Curse":10,"Body Slam":11,"Rock Slide":12,"Substitute":13,"Focus Punch":14,"Thunder Wave":15,"Will-O-Wisp":16,"Fire Blast":17,"Sludge Bomb":18,"Pain Split":19,"Meteor Mash":20,"Earthquake":21,"Brick Break":22,"Explosion":23,"Struggle":24}
WEATHER_MAP = {None:0,"sun":1,"rain":2,"sand":3,"hail":4}

def _conv_mon(py):
    c = CMon()
    c.t1 = TYPE_MAP[py.types[0]]
    c.t2 = TYPE_MAP[py.types[1]]
    c.ab = ABILITY_MAP.get(py.ability, 0)
    c.item = ITEM_MAP.get(py.item, 0)
    c.item_c = int(py.item_consumed)
    for i, m in enumerate(py.moves[:4]):
        c.mv[i] = MOVE_MAP.get(m, 24)
    c.mlock = MOVE_MAP.get(py.move_locked, -1) if py.move_locked else -1
    c.mhp = py.max_hp; c.hp = py.current_hp
    c.atk = py.base_atk; c.def_ = py.base_def
    c.spa = py.base_spa; c.spd = py.base_spd; c.spe = py.base_spe
    c.st = STATUS_MAP.get(py.status, 0); c.st_t = py.status_turns
    c.as_ = py.atk_stage; c.ds = py.def_stage
    c.sas = py.spa_stage; c.sds = py.spd_stage; c.ss = py.spe_stage
    c.sub = py.substitute_hp; c.taunt = py.taunt_turns
    c.flinch = int(py.flinched)
    c.ldmg = py.last_damage_taken; c.lphys = int(py.last_damage_physical)
    return c

def convert_state(py):
    c = CState()
    for p in range(2):
        team = py.team_p1 if p == 0 else py.team_p2
        for i, mon in enumerate(team):
            c.team[p][i] = _conv_mon(mon)
    c.act[0] = py.active_p1; c.act[1] = py.active_p2
    c.weath = WEATHER_MAP.get(py.weather, 0); c.weath_t = py.weather_turns
    c.refl[0] = py.field_p1.reflect_turns; c.refl[1] = py.field_p2.reflect_turns
    c.ls[0] = py.field_p1.light_screen_turns; c.ls[1] = py.field_p2.light_screen_turns
    c.spk[0] = py.field_p1.spikes; c.spk[1] = py.field_p2.spikes
    c.turn = py.turn_number
    return c

def c_rollout(state, n_sims, seed=None):
    """Run MC rollouts via C extension. Returns P1 win probability."""
    if seed is None:
        seed = random.randint(1, 2**31 - 1)
    c = convert_state(state)
    wins = _lib.run_rollouts(ctypes.byref(c), n_sims, seed)
    return wins / n_sims if n_sims > 0 else 0.5
