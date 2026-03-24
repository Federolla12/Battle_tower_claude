from dataclasses import replace

from gen3.state import make_pokemon, make_battle
from gen3.turn import resolve_turn, execute_player_action
from gen3.search import SearchEngine


def _mk_skarmory():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Hidden Power", "Taunt", "Counter", "Toxic"],
        "Leftovers", "Keen Eye",
    )


def _mk_metagross_choice():
    return make_pokemon(
        "Metagross", "Jolly",
        {"atk": 252, "spd": 4, "spe": 252}, {},
        ["Meteor Mash", "Earthquake", "Brick Break", "Explosion"],
        "Choice Band", "Clear Body",
    )


def _mk_aggron():
    return make_pokemon(
        "Aggron", "Impish",
        {"hp": 248, "atk": 8, "def": 252}, {},
        ["Rock Slide", "Substitute", "Focus Punch", "Thunder Wave"],
        "Leftovers", "Sturdy",
    )


def _mk_weezing():
    return make_pokemon(
        "Weezing", "Sassy",
        {"hp": 252, "atk": 4, "spd": 252}, {},
        ["Will-O-Wisp", "Fire Blast", "Sludge Bomb", "Pain Split"],
        "Lum Berry", "Levitate",
    )


def test_speed_tie_branches_order_sensitive_lines():
    # Force a speed tie where order matters: Taunt vs Substitute.
    p1 = _mk_skarmory()
    p2 = _mk_aggron()
    p2 = replace(p2, base_spe=p1.base_spe)
    bench1 = _mk_skarmory()
    bench2 = _mk_aggron()
    state = make_battle([p1, bench1, bench1], [p2, bench2, bench2])

    outcomes = resolve_turn(state, ("move", "Taunt"), ("move", "Substitute"))

    # Tie branching should create outcomes where Substitute is either blocked
    # or already established before Taunt lands.
    p2_subs = {s.active("p2").substitute_hp for _, s in outcomes}
    assert 0 in p2_subs
    assert any(v > 0 for v in p2_subs)

    total_prob = sum(prob for prob, _ in outcomes)
    assert abs(total_prob - 1.0) < 1e-9


def test_analyze_uses_consistent_depth_offset():
    p1 = _mk_skarmory()
    p2 = _mk_skarmory()
    bench1 = _mk_skarmory()
    bench2 = _mk_skarmory()
    state = make_battle([p1, bench1, bench1], [p2, bench2, bench2])

    engine = SearchEngine(max_depth=1, mc_rollouts=1)
    seen_depths = []

    def fake_search(_state, depth=0):
        seen_depths.append(depth)
        return 0.5

    engine.search = fake_search  # monkeypatch on instance
    engine.analyze(state)

    assert seen_depths, "expected analyze() to call search()"
    assert all(d == 1 for d in seen_depths)


def test_choice_band_miss_branch_does_not_lock_move():
    p1 = _mk_metagross_choice()
    p2 = _mk_weezing()
    bench1 = _mk_skarmory()
    bench2 = _mk_skarmory()
    state = make_battle([p1, bench1, bench1], [p2, bench2, bench2])

    outcomes = execute_player_action(state, "p1", ("move", "Meteor Mash"))

    # Meteor Mash has 85% accuracy so we should see both hit and miss branches.
    miss_like = [s for p, s in outcomes if p > 0 and s.active("p1").last_move is None]
    hit_like = [s for p, s in outcomes if p > 0 and s.active("p1").last_move == "Meteor Mash"]

    assert miss_like, "expected at least one miss/no-use branch"
    assert hit_like, "expected at least one successful-use branch"

    assert all(s.active("p1").move_locked is None for s in miss_like)
    assert any(s.active("p1").move_locked == "Meteor Mash" for s in hit_like)


def test_team_parser_warning_shape_is_stable():
    from gen3.team_parser import validate_team

    warnings = validate_team([
        {"species": "Skarmory", "ability": "", "item": "None", "moves": ["Taunt"]},
        {"species": "Skarmory", "ability": "Keen Eye", "item": "Leftovers", "moves": ["Toxic", "Taunt", "Counter", "Hidden Power"]},
        {"species": "Gengar", "ability": "Levitate", "item": "Lum Berry", "moves": ["Psychic", "Ice Punch", "Fire Punch", "Giga Drain"]},
    ])

    # warnings are structured with stable code + human-readable message.
    assert any(w["code"] == "duplicate_species" for w in warnings)
    assert any("Duplicate species" in w["message"] for w in warnings)
    assert any(w["code"] == "missing_ability" for w in warnings)
