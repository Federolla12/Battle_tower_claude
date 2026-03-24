"""
Gen 3 Battle Engine — Interactive Analysis Server
Both sides controlled by the user (chess analysis style).
"""
import sys, os, json, time, random, threading, traceback
from flask import Flask, jsonify, request, send_from_directory
from dataclasses import dataclass, field, replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen3.state import make_pokemon, make_battle, BattleState
from gen3.search import SearchEngine
from gen3.executor import (get_legal_actions,
                            _make_attacker, _make_defender, _make_move_info)
from gen3.turn import resolve_turn, execute_switch
from gen3.moves import get_move
from gen3.damage import calc_damage, Conditions
from gen3.types import type_effectiveness
from gen3.team_parser import parse_showdown_paste, validate_team
import functools

@functools.lru_cache(maxsize=1)
def _load_bf_sets():
    import os
    path = os.path.join(os.path.dirname(__file__), "gen3", "bf_sets.json")
    with open(path) as f:
        return json.load(f)

app = Flask(__name__, static_folder="static")

@dataclass
class GameSession:
    """Mutable server session state for one local analysis board."""
    game_state: BattleState | None = None
    analysis_result: dict | None = None
    analysis_depth: int = 0
    analysis_running: bool = False
    analysis_current_depth: int = -1
    analysis_error: str | None = None
    analysis_thread: threading.Thread | None = None
    log_entries: list = field(default_factory=list)
    state_history: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)
    pending_outcomes: list = field(default_factory=list)


# ============================================================
# Global server lock + singleton session
# ============================================================
lock = threading.Lock()
SESSION = GameSession()

DEFAULT_TEAM1 = [
    dict(species="Skarmory",nature="Impish",evs={"hp":252,"def":232,"spe":24},ivs={"spa":30,"spd":30},moves=["Hidden Power","Taunt","Counter","Toxic"],item="Leftovers",ability="Keen Eye"),
    dict(species="Gengar",nature="Timid",evs={"spa":252,"spd":4,"spe":252},ivs={"atk":0},moves=["Giga Drain","Psychic","Ice Punch","Fire Punch"],item="Lum Berry",ability="Levitate"),
    dict(species="Snorlax",nature="Careful",evs={"hp":252,"atk":4,"spd":252},ivs={},moves=["Rest","Sleep Talk","Curse","Body Slam"],item="Chesto Berry",ability="Thick Fat"),
]
DEFAULT_TEAM2 = [
    dict(species="Aggron",nature="Impish",evs={"hp":248,"atk":8,"def":252},ivs={},moves=["Rock Slide","Substitute","Focus Punch","Thunder Wave"],item="Leftovers",ability="Sturdy"),
    dict(species="Weezing",nature="Sassy",evs={"hp":252,"atk":4,"spd":252},ivs={},moves=["Will-O-Wisp","Fire Blast","Sludge Bomb","Pain Split"],item="Lum Berry",ability="Levitate"),
    dict(species="Metagross",nature="Jolly",evs={"atk":252,"spd":4,"spe":252},ivs={},moves=["Meteor Mash","Earthquake","Brick Break","Explosion"],item="Choice Band",ability="Clear Body"),
]

# Custom team data (set by /api/set_teams)
custom_team1 = None
custom_team2 = None


def _mons_from_data(team_data):
    return [make_pokemon(m["species"], m["nature"], m["evs"], m.get("ivs", {}),
                         m["moves"], m["item"], m["ability"]) for m in team_data]


def build_teams():
    t1_data = custom_team1 if custom_team1 is not None else DEFAULT_TEAM1
    t2_data = custom_team2 if custom_team2 is not None else DEFAULT_TEAM2
    return _mons_from_data(t1_data), _mons_from_data(t2_data)

def init_game():
    t1, t2 = build_teams()
    SESSION.game_state = make_battle(t1, t2)
    SESSION.analysis_result = None
    SESSION.analysis_depth = 0
    SESSION.log_entries = []
    SESSION.state_history = []
    SESSION.redo_stack = []
    SESSION.pending_outcomes = []

# ============================================================
# Background analysis
# ============================================================
ANALYSIS_TIMEOUT = 60  # seconds — skip remaining stages after this

def run_analysis(state):
    SESSION.analysis_running = True
    try:
        # With OpenMP parallel rollouts (~450K games/sec on 8 cores):
        #   depth 0 mc=500:  ~0.1s  — instant baseline
        #   depth 1 mc=300:  ~3s    — 1-ply quick pass
        #   depth 1 mc=800:  ~7s    — 1-ply refined
        #   depth 2 mc=50:   ~35s   — 2-ply rough (background)
        stages = [(0, 500), (1, 300), (1, 800), (2, 50)]
        t_start = time.time()
        for d, mc in stages:
            if time.time() - t_start > ANALYSIS_TIMEOUT:
                break
            with lock:
                if SESSION.game_state is not state:
                    return
                SESSION.analysis_current_depth = d
            random.seed(int(time.time()*1000) + d)
            eng = SearchEngine(max_depth=d, mc_rollouts=mc)
            r = eng.analyze(state)
            with lock:
                if SESSION.game_state is state:
                    SESSION.analysis_result = r
                    SESSION.analysis_depth = d
    except Exception as e:
        traceback.print_exc()
        with lock:
            if SESSION.game_state is state:
                SESSION.analysis_error = str(e)
    finally:
        SESSION.analysis_running = False

def start_analysis():
    SESSION.analysis_result = None
    SESSION.analysis_depth = -1
    SESSION.analysis_current_depth = -1
    SESSION.analysis_error = None
    s = SESSION.game_state
    SESSION.analysis_thread = threading.Thread(target=run_analysis, args=(s,), daemon=True)
    SESSION.analysis_thread.start()

# ============================================================
# Serialization
# ============================================================
def describe_outcome(old_s, new_s):
    """
    Return a list of human-readable strings describing the observable differences
    between old_s and new_s. Used by the outcome picker.
    """
    parts = []

    for player, label in [("p1", "P1"), ("p2", "P2")]:
        old_team = list(old_s.get_team(player))
        new_team = list(new_s.get_team(player))
        old_act_idx = old_s.get_active_idx(player)
        new_act_idx = new_s.get_active_idx(player)

        # Active mon switched
        if old_act_idx != new_act_idx:
            parts.append(f"{label}: {old_team[old_act_idx].species} → {new_team[new_act_idx].species}")

        for i, (om, nm) in enumerate(zip(old_team, new_team)):
            name = om.species
            # HP changes
            if nm.current_hp != om.current_hp and om.alive():
                diff = om.current_hp - nm.current_hp
                if diff > 0 and not nm.alive():
                    parts.append(f"{label} {name}: −{diff} HP → KO!")
                elif diff > 0:
                    pct = round(diff / om.max_hp * 100)
                    parts.append(f"{label} {name}: −{diff} HP ({pct}%) → {nm.current_hp}/{nm.max_hp}")
                else:
                    parts.append(f"{label} {name}: +{-diff} HP → {nm.current_hp}/{nm.max_hp}")
            # Substitute
            if nm.substitute_hp != om.substitute_hp:
                if om.substitute_hp > 0 and nm.substitute_hp == 0:
                    parts.append(f"{label} {name}: Sub broke")
                elif om.substitute_hp > 0:
                    parts.append(f"{label} {name}: Sub −{om.substitute_hp - nm.substitute_hp}")
                elif nm.substitute_hp > 0 and om.substitute_hp == 0:
                    parts.append(f"{label} {name}: +Sub ({nm.substitute_hp} HP)")
            # Status
            if om.status != nm.status:
                if nm.status:
                    parts.append(f"{label} {name}: {nm.status.upper()}")
                else:
                    parts.append(f"{label} {name}: status cured")
            # Confusion / stat stages (active mon only)
            if i in (old_act_idx, new_act_idx):
                if not om.confused and nm.confused:
                    parts.append(f"{label} {name}: confused")
                elif om.confused and not nm.confused:
                    parts.append(f"{label} {name}: confusion ended")
                for attr, slbl in [("atk_stage","Atk"),("def_stage","Def"),
                                    ("spa_stage","SpA"),("spd_stage","SpD"),("spe_stage","Spe")]:
                    ov, nv = getattr(om, attr), getattr(nm, attr)
                    if nv != ov:
                        parts.append(f"{label} {name}: {slbl}{'+' if nv>ov else ''}{nv-ov}")

    if old_s.weather != new_s.weather:
        parts.append(f"Weather: {new_s.weather or 'clear'}")

    if not parts:
        parts.append("No observable change (miss / blocked / failed)")

    return parts


def ser_mon(m, active=False):
    return {"species":m.species,"hp":m.current_hp,"maxHp":m.max_hp,"status":m.status,
            "statusTurns":m.status_turns,"types":list(m.types),"item":m.item,
            "itemConsumed":m.item_consumed,"ability":m.ability,"moves":list(m.moves),
            "moveLocked":m.move_locked,"atkStage":m.atk_stage,"defStage":m.def_stage,
            "spaStage":m.spa_stage,"spdStage":m.spd_stage,"speStage":m.spe_stage,
            "substituteHp":m.substitute_hp,"tauntTurns":m.taunt_turns,
            "isActive":active,"alive":m.alive()}

def ser_state(s):
    return {
        "turn": s.turn_number,
        "p1": [ser_mon(m, i==s.active_p1) for i,m in enumerate(s.team_p1)],
        "p2": [ser_mon(m, i==s.active_p2) for i,m in enumerate(s.team_p2)],
        "weather": s.weather, "weatherTurns": s.weather_turns,
        "isTerminal": s.is_terminal(), "winner": s.winner(),
        "p1NeedsSwitch": not s.active("p1").alive() and any(m.alive() for i,m in enumerate(s.team_p1) if i!=s.active_p1),
        "p2NeedsSwitch": not s.active("p2").alive() and any(m.alive() for i,m in enumerate(s.team_p2) if i!=s.active_p2),
    }

def _move_damage_info(s, player, move_name):
    """Compute type effectiveness and damage range for a move vs current opponent."""
    try:
        move = get_move(move_name)
    except KeyError:
        return {}
    if move.base_power == 0:
        return {}
    opp = "p2" if player == "p1" else "p1"
    attacker = s.active(player)
    defender = s.active(opp)
    def_field = s.field_p1 if opp == "p1" else s.field_p2
    try:
        atk = _make_attacker(attacker)
        dfn = _make_defender(defender, def_field)
        mi = _make_move_info(move)
        cond = Conditions(weather=s.weather, is_critical=False)
        rolls = calc_damage(atk, dfn, mi, cond)
        eff = type_effectiveness(move.type, defender.types[0], defender.types[1])
        if defender.ability == "Levitate" and move.type == "Ground":
            eff = 0.0
        if not any(r > 0 for r in rolls):
            return {"typeEff": 0.0}
        denom = max(1, defender.current_hp)
        return {
            "typeEff": eff,
            "dmgMin": rolls[0], "dmgMax": rolls[-1],
            "dmgPctMin": round(rolls[0] / denom * 100),
            "dmgPctMax": round(rolls[-1] / denom * 100),
        }
    except Exception:
        return {}


def ser_actions(s, player):
    acts = get_legal_actions(s, player)
    out = []
    for a in acts:
        if a[0] == "move":
            info = {"type":"move","id":a[1],"label":a[1]}
            info.update(_move_damage_info(s, player, a[1]))
            out.append(info)
        else:
            team = s.team_p1 if player=="p1" else s.team_p2
            out.append({"type":"switch","id":a[1],"label":f"Switch→{team[a[1]].species}",
                         "species":team[a[1]].species,
                         "hp":team[a[1]].current_hp,"maxHp":team[a[1]].max_hp})
    return out

def _get_turn_events(old_state, new_state, a1=None, a2=None):
    """Summarize HP/status/stage changes between two states."""
    from gen3.moves import get_move
    events = []

    # Detect when a status/boost move was chosen but didn't fire (flinch, para skip, sleep).
    BOOST_EFFECTS = {"curse_normal", "calm_mind", "swords_dance", "bulk_up",
                     "agility", "amnesia", "growth", "nasty_plot", "meditate",
                     "harden", "sharpen", "defense_curl", "minimize",
                     "barrier", "acid_armor", "iron_defense", "cosmic_power",
                     "substitute", "taunt", "toxic", "will_o_wisp",
                     "paralyze_status", "burn_status", "sleep_status",
                     "leech_seed", "protect", "rest", "counter", "encore"}

    def _check_move_skipped(player, action, opp_action, old_s, new_s):
        if action is None or action[0] != "move":
            return None
        move_name = action[1]
        try:
            move = get_move(move_name)
        except KeyError:
            return None
        if move.base_power > 0:
            return None  # damaging moves can just miss or do 0 — don't infer skips
        old_mon = old_s.active(player)
        new_mon = new_s.active(player)
        if not old_mon.alive():
            return None

        # Only flag if the move's expected effect didn't appear to happen
        if move.effect not in ("curse_normal",):
            return None  # Only track Curse for now (clear visual indicator)
        if old_mon.atk_stage >= 6:
            return None  # Already at max — no change expected
        if (new_mon.atk_stage == old_mon.atk_stage and
                new_mon.def_stage == old_mon.def_stage):
            # Determine reason from pre-turn status
            if old_mon.status == "sleep":
                return f"{old_mon.species} is fast asleep"
            if old_mon.status == "freeze":
                return f"{old_mon.species} is frozen solid"
            if old_mon.status == "paralyze":
                return f"{old_mon.species} was paralyzed — couldn't move"
            # Check if opponent's move can flinch
            if opp_action and opp_action[0] == "move":
                try:
                    opp_move = get_move(opp_action[1])
                    if opp_move.effect == "flinch":
                        return f"{old_mon.species} flinched"
                except KeyError:
                    pass
            return f"{old_mon.species}'s {move_name} failed"
        return None

    skip1 = _check_move_skipped("p1", a1, a2, old_state, new_state)
    skip2 = _check_move_skipped("p2", a2, a1, old_state, new_state)

    sides = [
        (old_state.team_p1, new_state.team_p1, "p1"),
        (old_state.team_p2, new_state.team_p2, "p2"),
    ]
    for old_team, new_team, player in sides:
        for old_mon, new_mon in zip(old_team, new_team):
            hp_diff = old_mon.current_hp - new_mon.current_hp
            if hp_diff > 0 and old_mon.alive():
                pct = round(hp_diff / old_mon.max_hp * 100)
                events.append(f"{old_mon.species} -{hp_diff} ({pct}%)")
            elif hp_diff < 0 and old_mon.alive():
                events.append(f"{old_mon.species} +{-hp_diff} HP")
            if not old_mon.status and new_mon.status:
                events.append(f"{old_mon.species}: {new_mon.status}")
            if old_mon.alive() and not new_mon.alive():
                events.append(f"{old_mon.species} fainted")
            # Stat stage changes
            stage_names = [("atk", "Atk"), ("def", "Def"), ("spa", "SpA"),
                           ("spd", "SpD"), ("spe", "Spe")]
            for attr, label in stage_names:
                old_v = getattr(old_mon, f"{attr}_stage")
                new_v = getattr(new_mon, f"{attr}_stage")
                if new_v != old_v:
                    sign = "+" if new_v > old_v else ""
                    events.append(f"{old_mon.species}: {label}{sign}{new_v - old_v}")

    if skip1:
        events.append(skip1)
    if skip2:
        events.append(skip2)
    return events


def ser_analysis(r, s):
    if not r:
        if SESSION.analysis_error:
            return {"error": SESSION.analysis_error, "running": False, "moves": [],
                    "positionValue": 50.0, "depth": -1, "nodes": 0}
        return None
    moves = []
    for a in sorted(r["actions_p1"], key=lambda a: r["p1_analysis"][a]["guaranteed_win_pct"], reverse=True):
        info = r["p1_analysis"][a]
        name = a[1] if a[0]=="move" else f"Switch→{s.team_p1[a[1]].species}"
        ctr = info["best_opponent_response"]
        ctr_name = ctr[1] if ctr[0]=="move" else f"Switch→{s.team_p2[ctr[1]].species}"
        moves.append({"name":name,"winPct":round(info["guaranteed_win_pct"]*100,1),
                       "counter":ctr_name,"isBest":a==r["best_move_p1"]})
    return {"moves":moves,"positionValue":round(r["position_value"]*100,1),
            "depth":SESSION.analysis_depth,"currentDepth":SESSION.analysis_current_depth,
            "nodes":r["nodes_searched"],"running":SESSION.analysis_running,
            "error": SESSION.analysis_error}

# ============================================================
# API
# ============================================================
@app.route("/")
def index():
    return send_from_directory("static","index.html")

@app.route("/api/state")
def get_state():
    with lock:
        s = SESSION.game_state
        return jsonify({
            "state": ser_state(s),
            "p1Actions": ser_actions(s,"p1"),
            "p2Actions": ser_actions(s,"p2"),
            "analysis": ser_analysis(SESSION.analysis_result, s),
            "log": SESSION.log_entries,
            "canUndo": len(SESSION.state_history) > 0,
            "canRedo": len(SESSION.redo_stack) > 0,
        })

@app.route("/api/outcomes", methods=["POST"])
def get_outcomes():
    """
    Compute all possible outcomes for a (p1, p2) action pair.
    Groups similar outcomes by observable state, returns sorted by probability.
    Does NOT advance game state.
    """
    data = request.json
    a1 = tuple(data["p1"])
    a2 = tuple(data["p2"])
    if a1[0] == "switch": a1 = ("switch", int(a1[1]))
    if a2[0] == "switch": a2 = ("switch", int(a2[1]))

    with lock:
        if SESSION.game_state.is_terminal():
            return jsonify({"error": "Game is over"}), 400
        old = SESSION.game_state
        try:
            outcomes = resolve_turn(SESSION.game_state, a1, a2)
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

        SESSION.pending_outcomes = outcomes  # cache for /api/commit

        # Group by observable key (active mon HP/status/stages/confusion + weather)
        groups = {}
        for i, (prob, ns) in enumerate(outcomes):
            def _mon_key(s, pl):
                m = s.active(pl)
                return (m.current_hp, m.substitute_hp, m.status, m.confused,
                        m.atk_stage, m.def_stage, m.spa_stage, m.spd_stage, m.spe_stage)
            key = (_mon_key(ns, "p1"), _mon_key(ns, "p2"),
                   ns.get_active_idx("p1"), ns.get_active_idx("p2"),
                   ns.weather)
            if key not in groups:
                groups[key] = {"prob": 0.0, "rep_idx": i, "rep_state": ns}
            groups[key]["prob"] += prob

        # Sort by descending probability
        sorted_groups = sorted(groups.values(), key=lambda g: -g["prob"])

        described = []
        for g in sorted_groups:
            events = describe_outcome(old, g["rep_state"])
            described.append({
                "idx": g["rep_idx"],          # index into pending_outcomes
                "prob": round(g["prob"] * 100, 1),
                "events": events,
            })

        return jsonify({"outcomes": described})


@app.route("/api/commit", methods=["POST"])
def commit_outcome():
    """
    Commit a specific outcome from the last /api/outcomes call.
    Body: {"idx": <index into pending_outcomes>, "n1": "move name", "n2": "move name"}
    """
    data = request.json
    idx = int(data["idx"])
    n1 = data.get("n1", "?")
    n2 = data.get("n2", "?")

    with lock:
        if idx < 0 or idx >= len(SESSION.pending_outcomes):
            return jsonify({"error": "Invalid outcome index"}), 400

        SESSION.state_history.append(SESSION.game_state)
        SESSION.redo_stack.clear()
        old = SESSION.game_state
        SESSION.game_state = SESSION.pending_outcomes[idx][1]
        SESSION.pending_outcomes = []

        events = describe_outcome(old, SESSION.game_state)
        SESSION.log_entries.append({"turn": old.turn_number, "p1": n1, "p2": n2, "events": events})
        start_analysis()

    return jsonify({"ok": True})


@app.route("/api/resolve", methods=["POST"])
def resolve():
    """Legacy: resolve randomly. Kept for backward compat."""
    data = request.json
    a1 = tuple(data["p1"])
    a2 = tuple(data["p2"])
    if a1[0]=="switch": a1=("switch",int(a1[1]))
    if a2[0]=="switch": a2=("switch",int(a2[1]))

    with lock:
        if SESSION.game_state.is_terminal():
            return jsonify({"error":"Game is over"}),400
        SESSION.state_history.append(SESSION.game_state)
        SESSION.redo_stack.clear()
        old = SESSION.game_state
        try:
            outcomes = resolve_turn(SESSION.game_state, a1, a2)
            probs = [p for p, _ in outcomes]
            SESSION.game_state = random.choices([s for _, s in outcomes], weights=probs, k=1)[0]
        except Exception as e:
            traceback.print_exc()
            SESSION.state_history.pop()
            return jsonify({"error": str(e)}), 500
        n1 = a1[1] if a1[0]=="move" else f"Switch→{old.team_p1[a1[1]].species}"
        n2 = a2[1] if a2[0]=="move" else f"Switch→{old.team_p2[a2[1]].species}"
        events = describe_outcome(old, SESSION.game_state)
        SESSION.log_entries.append({"turn":old.turn_number,"p1":n1,"p2":n2,"events":events})
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/edit_state", methods=["POST"])
def edit_state():
    """
    Directly edit the current battle state (HP, status, stages, weather).
    Body: {
      "p1": [{"hp": 100, "status": "burn", "stages": {"atk": 2}}, ...],  # one per mon
      "p2": [...],
      "weather": "sand" | ""
    }
    Any field omitted = no change for that field.
    """
    data = request.json

    with lock:
        SESSION.state_history.append(SESSION.game_state)
        SESSION.redo_stack.clear()
        s = SESSION.game_state

        for player in ["p1", "p2"]:
            edits = data.get(player, [])
            team = list(s.get_team(player))
            for i, ed in enumerate(edits):
                if i >= len(team) or not ed:
                    continue
                mon = team[i]
                kw = {}
                if "hp" in ed:
                    kw["current_hp"] = max(0, min(mon.max_hp, int(ed["hp"])))
                if "status" in ed:
                    st = ed["status"] or None
                    kw["status"] = st
                    kw["status_turns"] = 0 if not st else mon.status_turns
                if "stages" in ed:
                    for stat, val in ed["stages"].items():
                        kw[f"{stat}_stage"] = max(-6, min(6, int(val)))
                if kw:
                    team[i] = replace(mon, **kw)
            if player == "p1":
                s = replace(s, team_p1=tuple(team))
            else:
                s = replace(s, team_p2=tuple(team))

        if "weather" in data:
            w = data["weather"] or None
            turns = 10000 if w else 0
            s = replace(s, weather=w, weather_turns=turns)

        SESSION.game_state = s
        SESSION.log_entries.append({"turn": s.turn_number, "p1": "✎ edit", "p2": "—",
                             "events": ["State edited manually"]})
        start_analysis()

    return jsonify({"ok": True})


@app.route("/api/switch", methods=["POST"])
def forced_switch():
    """Handle a forced switch (after a KO)."""
    data = request.json
    player = data["player"]  # "p1" or "p2"
    idx = int(data["idx"])

    with lock:
        SESSION.state_history.append(SESSION.game_state)
        SESSION.redo_stack.clear()
        SESSION.game_state = execute_switch(SESSION.game_state, player, idx)
        SESSION.log_entries.append({"turn":SESSION.game_state.turn_number,
                            "p1": f"Switch→{SESSION.game_state.active(player).species}" if player=="p1" else "—",
                            "p2": f"Switch→{SESSION.game_state.active(player).species}" if player=="p2" else "—"})
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/undo", methods=["POST"])
def undo():
    with lock:
        if not SESSION.state_history:
            return jsonify({"error":"Nothing to undo"}),400
        SESSION.redo_stack.append(SESSION.game_state)
        SESSION.game_state = SESSION.state_history.pop()
        if SESSION.log_entries:
            SESSION.log_entries.pop()
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/redo", methods=["POST"])
def redo():
    with lock:
        if not SESSION.redo_stack:
            return jsonify({"error":"Nothing to redo"}),400
        SESSION.state_history.append(SESSION.game_state)
        SESSION.game_state = SESSION.redo_stack.pop()
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/bf_sets")
def get_bf_sets():
    """
    Return Battle Frontier sets, optionally filtered.
    Query params: species=Salamence, group=Group 1, playable=1
    """
    sets = _load_bf_sets()
    species = request.args.get("species", "").strip()
    group = request.args.get("group", "").strip()
    playable_only = request.args.get("playable", "0") == "1"

    if species:
        sets = [s for s in sets if s["species"].lower() == species.lower()]
    if group:
        sets = [s for s in sets if s["group"] == group]
    if playable_only:
        sets = [s for s in sets if s.get("playable")]
    return jsonify({"sets": sets, "total": len(sets)})


@app.route("/api/reset", methods=["POST"])
def reset():
    with lock:
        init_game()   # clears redo_stack and pending_outcomes
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/parse_team", methods=["POST"])
def parse_team():
    """
    Validate a Showdown team paste. Returns parsed team data or errors.
    Body: {"paste": "...", "player": "p1"|"p2"}
    """
    data = request.json
    paste = data.get("paste", "").strip()
    if not paste:
        return jsonify({"error": "Empty paste"}), 400
    try:
        mons = parse_showdown_paste(paste)
        warnings = validate_team(mons)
        # Return the parsed data for preview
        preview = [{"species": m["species"], "moves": m["moves"],
                    "item": m["item"], "ability": m["ability"],
                    "nature": m["nature"]} for m in mons]
        return jsonify({"ok": True, "team": preview, "warnings": warnings})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/set_teams", methods=["POST"])
def set_teams():
    """
    Apply new teams from Showdown paste and restart the game.
    Body: {"p1": "paste...", "p2": "paste..."}
    """
    global custom_team1, custom_team2
    data = request.json
    errors = {}

    new_t1 = None
    new_t2 = None

    if "p1" in data and data["p1"].strip():
        try:
            new_t1 = parse_showdown_paste(data["p1"])
        except ValueError as e:
            errors["p1"] = str(e)

    if "p2" in data and data["p2"].strip():
        try:
            new_t2 = parse_showdown_paste(data["p2"])
        except ValueError as e:
            errors["p2"] = str(e)

    if errors:
        return jsonify({"error": errors}), 400

    with lock:
        if new_t1 is not None:
            custom_team1 = new_t1
        if new_t2 is not None:
            custom_team2 = new_t2
        init_game()
        start_analysis()

    return jsonify({"ok": True})

if __name__ == "__main__":
    init_game()
    start_analysis()
    print("="*50)
    print("  Gen 3 Battle Engine")
    print("  http://localhost:5000")
    print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=False)
