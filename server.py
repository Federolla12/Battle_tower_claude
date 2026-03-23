"""
Gen 3 Battle Engine — Interactive Analysis Server
Both sides controlled by the user (chess analysis style).
"""
import sys, os, json, time, random, threading
from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen3.state import make_pokemon, make_battle, BattleState
from gen3.search import SearchEngine
from gen3.executor import get_legal_actions
from gen3.turn import resolve_turn, execute_switch
from gen3.moves import get_move
from dataclasses import replace

app = Flask(__name__, static_folder="static")

# ============================================================
# Global state
# ============================================================
lock = threading.Lock()
game_state = None
analysis_result = None
analysis_depth = 0
analysis_running = False
analysis_thread = None
log_entries = []
state_history = []   # for undo

def build_teams():
    t1 = [
        make_pokemon("Skarmory","Impish",{"hp":252,"def":232,"spe":24},{"spa":30,"spd":30},["Hidden Power","Taunt","Counter","Toxic"],"Leftovers","Keen Eye"),
        make_pokemon("Gengar","Timid",{"spa":252,"spd":4,"spe":252},{"atk":0},["Giga Drain","Psychic","Ice Punch","Fire Punch"],"Lum Berry","Levitate"),
        make_pokemon("Snorlax","Careful",{"hp":252,"atk":4,"spd":252},{},["Rest","Sleep Talk","Curse","Body Slam"],"Chesto Berry","Thick Fat"),
    ]
    t2 = [
        make_pokemon("Aggron","Impish",{"hp":248,"atk":8,"def":252},{},["Rock Slide","Substitute","Focus Punch","Thunder Wave"],"Leftovers","Sturdy"),
        make_pokemon("Weezing","Sassy",{"hp":252,"atk":4,"spd":252},{},["Will-O-Wisp","Fire Blast","Sludge Bomb","Pain Split"],"Lum Berry","Levitate"),
        make_pokemon("Metagross","Jolly",{"atk":252,"spd":4,"spe":252},{},["Meteor Mash","Earthquake","Brick Break","Explosion"],"Choice Band","Clear Body"),
    ]
    return t1, t2

def init_game():
    global game_state, analysis_result, analysis_depth, log_entries, state_history
    t1, t2 = build_teams()
    game_state = make_battle(t1, t2)
    analysis_result = None
    analysis_depth = 0
    log_entries = []
    state_history = []

# ============================================================
# Background analysis
# ============================================================
def run_analysis(state):
    global analysis_result, analysis_depth, analysis_running
    analysis_running = True
    try:
        stages = [(0,300),(1,200),(2,200),(2,500)]
        for d, mc in stages:
            with lock:
                if game_state is not state:
                    return
            random.seed(int(time.time()*1000) + d)
            eng = SearchEngine(max_depth=d, mc_rollouts=mc)
            r = eng.analyze(state)
            with lock:
                if game_state is state:
                    analysis_result = r
                    analysis_depth = d
    finally:
        analysis_running = False

def start_analysis():
    global analysis_thread, analysis_result, analysis_depth
    analysis_result = None
    analysis_depth = -1
    s = game_state
    analysis_thread = threading.Thread(target=run_analysis, args=(s,), daemon=True)
    analysis_thread.start()

# ============================================================
# Serialization
# ============================================================
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

def ser_actions(s, player):
    acts = get_legal_actions(s, player)
    out = []
    for a in acts:
        if a[0] == "move":
            out.append({"type":"move","id":a[1],"label":a[1]})
        else:
            team = s.team_p1 if player=="p1" else s.team_p2
            out.append({"type":"switch","id":a[1],"label":f"Switch→{team[a[1]].species}",
                         "species":team[a[1]].species,
                         "hp":team[a[1]].current_hp,"maxHp":team[a[1]].max_hp})
    return out

def ser_analysis(r, s):
    if not r: return None
    moves = []
    for a in sorted(r["actions_p1"], key=lambda a: r["p1_analysis"][a]["guaranteed_win_pct"], reverse=True):
        info = r["p1_analysis"][a]
        name = a[1] if a[0]=="move" else f"Switch→{s.team_p1[a[1]].species}"
        ctr = info["best_opponent_response"]
        ctr_name = ctr[1] if ctr[0]=="move" else f"Switch→{s.team_p2[ctr[1]].species}"
        moves.append({"name":name,"winPct":round(info["guaranteed_win_pct"]*100,1),
                       "counter":ctr_name,"isBest":a==r["best_move_p1"]})
    return {"moves":moves,"positionValue":round(r["position_value"]*100,1),
            "depth":analysis_depth,"nodes":r["nodes_searched"],"running":analysis_running}

# ============================================================
# API
# ============================================================
@app.route("/")
def index():
    return send_from_directory("static","index.html")

@app.route("/api/state")
def get_state():
    with lock:
        s = game_state
        return jsonify({
            "state": ser_state(s),
            "p1Actions": ser_actions(s,"p1"),
            "p2Actions": ser_actions(s,"p2"),
            "analysis": ser_analysis(analysis_result, s),
            "log": log_entries,
            "canUndo": len(state_history) > 0,
        })

@app.route("/api/resolve", methods=["POST"])
def resolve():
    """Resolve a turn with both players' chosen actions."""
    global game_state, log_entries, state_history
    data = request.json
    a1 = tuple(data["p1"])  # e.g. ["move","Hidden Power"] or ["switch",1]
    a2 = tuple(data["p2"])
    if a1[0]=="switch": a1=("switch",int(a1[1]))
    if a2[0]=="switch": a2=("switch",int(a2[1]))

    with lock:
        if game_state.is_terminal():
            return jsonify({"error":"Game is over"}),400

        state_history.append(game_state)
        old = game_state

        # Resolve
        outcomes = resolve_turn(game_state, a1, a2)
        # Pick most likely outcome
        outcomes.sort(key=lambda x:-x[0])
        game_state = outcomes[0][1]

        # Log
        n1 = a1[1] if a1[0]=="move" else f"Switch→{old.team_p1[a1[1]].species}"
        n2 = a2[1] if a2[0]=="move" else f"Switch→{old.team_p2[a2[1]].species}"
        log_entries.append({"turn":old.turn_number,"p1":n1,"p2":n2})

        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/switch", methods=["POST"])
def forced_switch():
    """Handle a forced switch (after a KO)."""
    global game_state, state_history
    data = request.json
    player = data["player"]  # "p1" or "p2"
    idx = int(data["idx"])

    with lock:
        state_history.append(game_state)
        game_state = execute_switch(game_state, player, idx)
        log_entries.append({"turn":game_state.turn_number,
                            "p1": f"Switch→{game_state.active(player).species}" if player=="p1" else "—",
                            "p2": f"Switch→{game_state.active(player).species}" if player=="p2" else "—"})
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/undo", methods=["POST"])
def undo():
    global game_state, log_entries, state_history
    with lock:
        if not state_history:
            return jsonify({"error":"Nothing to undo"}),400
        game_state = state_history.pop()
        if log_entries:
            log_entries.pop()
        start_analysis()
    return jsonify({"ok":True})

@app.route("/api/reset", methods=["POST"])
def reset():
    with lock:
        init_game()
        start_analysis()
    return jsonify({"ok":True})

if __name__ == "__main__":
    init_game()
    start_analysis()
    print("="*50)
    print("  Gen 3 Battle Engine")
    print("  http://localhost:5000")
    print("="*50)
    app.run(host="0.0.0.0", port=5000, debug=False)
