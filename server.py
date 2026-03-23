"""
Gen 3 Battle Engine — Interactive Analysis Server
===================================================
Run: python server.py
Then open http://localhost:5000 in your browser.
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
# Game state (global, protected by lock)
# ============================================================

game_lock = threading.Lock()
game_state = None          # Current BattleState
analysis_result = None     # Latest analysis output
analysis_depth = 0         # Current depth being analyzed
analysis_running = False   # Is the background thread working?
analysis_thread = None
move_history = []          # List of (turn, p1_action, p2_action, state_before)

def build_teams():
    skarmory = make_pokemon("Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Hidden Power", "Taunt", "Counter", "Toxic"], "Leftovers", "Keen Eye")
    gengar = make_pokemon("Gengar", "Timid",
        {"spa": 252, "spd": 4, "spe": 252}, {"atk": 0},
        ["Giga Drain", "Psychic", "Ice Punch", "Fire Punch"], "Lum Berry", "Levitate")
    snorlax = make_pokemon("Snorlax", "Careful",
        {"hp": 252, "atk": 4, "spd": 252}, {},
        ["Rest", "Sleep Talk", "Curse", "Body Slam"], "Chesto Berry", "Thick Fat")
    aggron = make_pokemon("Aggron", "Impish",
        {"hp": 248, "atk": 8, "def": 252}, {},
        ["Rock Slide", "Substitute", "Focus Punch", "Thunder Wave"], "Leftovers", "Sturdy")
    weezing = make_pokemon("Weezing", "Sassy",
        {"hp": 252, "atk": 4, "spd": 252}, {},
        ["Will-O-Wisp", "Fire Blast", "Sludge Bomb", "Pain Split"], "Lum Berry", "Levitate")
    metagross = make_pokemon("Metagross", "Jolly",
        {"atk": 252, "spd": 4, "spe": 252}, {},
        ["Meteor Mash", "Earthquake", "Brick Break", "Explosion"], "Choice Band", "Clear Body")
    return (
        [skarmory, gengar, snorlax],
        [aggron, weezing, metagross],
    )


def init_game():
    global game_state, analysis_result, analysis_depth, move_history
    t1, t2 = build_teams()
    game_state = make_battle(t1, t2)
    analysis_result = None
    analysis_depth = 0
    move_history = []


# ============================================================
# Background analysis (iterative deepening)
# ============================================================

def run_analysis_thread(state):
    """Run iterative deepening analysis in background."""
    global analysis_result, analysis_depth, analysis_running

    analysis_running = True
    try:
        # Stage 1: Quick MC evaluation (depth 0 = pure rollouts)
        with game_lock:
            if game_state is not state:
                return  # State changed, abort

        engine0 = SearchEngine(max_depth=0, mc_rollouts=500)
        random.seed(int(time.time()))
        r0 = engine0.analyze(state)
        with game_lock:
            if game_state is state:
                analysis_result = r0
                analysis_depth = 0

        # Stage 2: Depth 1
        with game_lock:
            if game_state is not state:
                return

        engine1 = SearchEngine(max_depth=1, mc_rollouts=300)
        r1 = engine1.analyze(state)
        with game_lock:
            if game_state is state:
                analysis_result = r1
                analysis_depth = 1

        # Stage 3: Depth 2 (full analysis)
        with game_lock:
            if game_state is not state:
                return

        engine2 = SearchEngine(max_depth=2, mc_rollouts=200)
        r2 = engine2.analyze(state)
        with game_lock:
            if game_state is state:
                analysis_result = r2
                analysis_depth = 2

    finally:
        analysis_running = False


def start_analysis():
    """Start background analysis for current state."""
    global analysis_thread, analysis_result, analysis_depth
    analysis_result = None
    analysis_depth = -1

    state = game_state
    analysis_thread = threading.Thread(target=run_analysis_thread,
                                       args=(state,), daemon=True)
    analysis_thread.start()


# ============================================================
# State serialization
# ============================================================

def serialize_pokemon(mon, is_active=False):
    return {
        "species": mon.species,
        "hp": mon.current_hp,
        "maxHp": mon.max_hp,
        "status": mon.status,
        "statusTurns": mon.status_turns,
        "types": list(mon.types),
        "item": mon.item,
        "itemConsumed": mon.item_consumed,
        "ability": mon.ability,
        "moves": list(mon.moves),
        "moveLocked": mon.move_locked,
        "atkStage": mon.atk_stage,
        "defStage": mon.def_stage,
        "spaStage": mon.spa_stage,
        "spdStage": mon.spd_stage,
        "speStage": mon.spe_stage,
        "substituteHp": mon.substitute_hp,
        "tauntTurns": mon.taunt_turns,
        "isActive": is_active,
        "alive": mon.alive(),
    }


def serialize_state(state):
    p1_team = []
    for i, mon in enumerate(state.team_p1):
        p1_team.append(serialize_pokemon(mon, i == state.active_p1))
    p2_team = []
    for i, mon in enumerate(state.team_p2):
        p2_team.append(serialize_pokemon(mon, i == state.active_p2))

    return {
        "turn": state.turn_number,
        "p1": p1_team,
        "p2": p2_team,
        "weather": state.weather,
        "weatherTurns": state.weather_turns,
        "isTerminal": state.is_terminal(),
        "winner": state.winner(),
    }


def serialize_analysis(result, state):
    if result is None:
        return None

    actions_p1 = result["actions_p1"]
    p1_data = result["p1_analysis"]

    moves = []
    for a in sorted(actions_p1,
                     key=lambda a: p1_data[a]["guaranteed_win_pct"],
                     reverse=True):
        if a[0] == "move":
            name = a[1]
            action_type = "move"
        else:
            team = state.team_p1
            name = f"Switch→{team[a[1]].species}"
            action_type = "switch"

        counter = p1_data[a]["best_opponent_response"]
        if counter[0] == "move":
            counter_name = counter[1]
        else:
            team2 = state.team_p2
            counter_name = f"Switch→{team2[counter[1]].species}"

        moves.append({
            "action": list(a),
            "name": name,
            "type": action_type,
            "winPct": round(p1_data[a]["guaranteed_win_pct"] * 100, 1),
            "counter": counter_name,
            "isBest": a == result["best_move_p1"],
        })

    return {
        "moves": moves,
        "positionValue": round(result["position_value"] * 100, 1),
        "depth": analysis_depth,
        "nodes": result["nodes_searched"],
        "running": analysis_running,
    }


# ============================================================
# API endpoints
# ============================================================

@app.route("/")
def index():
    return send_from_directory("static", "index.html")

@app.route("/api/state")
def get_state():
    with game_lock:
        return jsonify({
            "state": serialize_state(game_state),
            "analysis": serialize_analysis(analysis_result, game_state),
            "history": [{"turn": h[0], "p1": h[1], "p2": h[2]} for h in move_history],
        })

@app.route("/api/play", methods=["POST"])
def play_move():
    """Play a move for P1. Engine picks P2's best response."""
    global game_state, move_history
    data = request.json
    action = tuple(data["action"])  # ["move", "Hidden Power"] or ["switch", 1]
    if action[0] == "switch":
        action = ("switch", int(action[1]))

    with game_lock:
        if game_state.is_terminal():
            return jsonify({"error": "Game is over"}), 400

        # Handle forced switches (active mon fainted)
        if not game_state.active("p1").alive():
            if action[0] != "switch":
                return jsonify({"error": "Must switch — active Pokemon fainted"}), 400
            new_state = execute_switch(game_state, "p1", action[1])
            move_history.append((game_state.turn_number, f"Switch→{game_state.team_p1[action[1]].species}", "—"))
            game_state = new_state
            start_analysis()
            return jsonify({"ok": True})

        if not game_state.active("p2").alive():
            # P2 auto-switches to best option
            bench = game_state.alive_bench("p2")
            if bench:
                new_state = execute_switch(game_state, "p2", bench[0])
                game_state = new_state
            start_analysis()
            return jsonify({"ok": True})

        # Get P2's best response to this specific P1 action
        # Use the analysis result if available
        p2_action = None
        if analysis_result and action in analysis_result["p1_analysis"]:
            p2_action = analysis_result["p1_analysis"][action]["best_opponent_response"]
        else:
            # Fallback: P2 picks first legal action
            p2_actions = get_legal_actions(game_state, "p2")
            p2_action = p2_actions[0]

        # Resolve the turn (sample one outcome)
        outcomes = resolve_turn(game_state, action, p2_action)
        # Pick the most likely outcome for deterministic play
        outcomes.sort(key=lambda x: -x[0])
        new_state = outcomes[0][1]

        # Format names for history
        p1_name = action[1] if action[0] == "move" else f"Switch→{game_state.team_p1[action[1]].species}"
        p2_name = p2_action[1] if p2_action[0] == "move" else f"Switch→{game_state.team_p2[p2_action[1]].species}"

        move_history.append((game_state.turn_number, p1_name, p2_name))
        game_state = new_state

        # Handle post-turn forced switches
        if not game_state.is_terminal():
            if not game_state.active("p2").alive():
                bench = game_state.alive_bench("p2")
                if bench:
                    # P2 auto-switches (engine picks best)
                    engine = SearchEngine(max_depth=0, mc_rollouts=100)
                    best_idx = bench[0]
                    best_val = 2.0
                    for idx in bench:
                        s = execute_switch(game_state, "p2", idx)
                        from gen3.c_rollout import c_rollout
                        val = c_rollout(s, 100)
                        if val < best_val:
                            best_val = val
                            best_idx = idx
                    game_state = execute_switch(game_state, "p2", best_idx)

        start_analysis()
        return jsonify({"ok": True})


@app.route("/api/reset", methods=["POST"])
def reset():
    with game_lock:
        init_game()
        start_analysis()
    return jsonify({"ok": True})


@app.route("/api/undo", methods=["POST"])
def undo():
    """Undo not implemented yet — would need state history."""
    return jsonify({"error": "Not implemented"}), 400


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    init_game()
    start_analysis()
    print("=" * 50)
    print("  Gen 3 Battle Engine — Interactive Analysis")
    print("  Open http://localhost:5000 in your browser")
    print("=" * 50)
    app.run(host="0.0.0.0", port=5000, debug=False)
