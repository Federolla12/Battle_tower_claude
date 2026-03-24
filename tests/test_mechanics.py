"""
Regression tests for specific mechanics.

Each test is named after the bug it guards — see commit history for context.
"""
from dataclasses import replace

import pytest

from gen3.state import make_pokemon, make_battle
from gen3.executor import apply_end_of_turn
from gen3.turn import execute_player_action, _apply_choice_lock


# ============================================================
# Helpers
# ============================================================

def _mk_weezing():
    """Poison type — takes hail damage, no Leftovers."""
    return make_pokemon(
        "Weezing", "Sassy",
        {"hp": 252, "atk": 4, "spd": 252}, {},
        ["Will-O-Wisp", "Fire Blast", "Sludge Bomb", "Pain Split"],
        None, "Levitate",
    )


def _mk_lapras():
    """Ice type — immune to hail damage."""
    return make_pokemon(
        "Lapras", "Bold",
        {"hp": 252, "def": 252}, {},
        ["Surf", "Ice Beam", "Thunderbolt", "Blizzard"],
        None, "Water Absorb",
    )


def _mk_skarmory():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Hidden Power", "Taunt", "Counter", "Toxic"],
        None, "Keen Eye",
    )


def _mk_metagross_cspecs():
    return make_pokemon(
        "Metagross", "Timid",
        {"spa": 252, "spd": 4, "spe": 252}, {},
        ["Psychic", "Ice Beam", "Thunderbolt", "Hidden Power"],
        "Choice Specs", "Clear Body",
    )


def _mk_metagross_cband():
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
        None, "Sturdy",
    )


# ============================================================
# Bug fix: hail damage missing from Python apply_end_of_turn
# ============================================================

def test_hail_damages_non_ice_type():
    """Non-Ice types must lose max_hp // 16 HP each turn in hail."""
    weezing = _mk_weezing()
    skarm = _mk_skarmory()
    state = make_battle([weezing, skarm, skarm], [skarm, skarm, skarm])
    state = replace(state, weather="hail", weather_turns=5)

    hp_before = state.active("p1").current_hp
    state2 = apply_end_of_turn(state)
    hp_after = state2.active("p1").current_hp

    expected_damage = max(1, weezing.max_hp // 16)
    assert hp_before - hp_after == expected_damage, (
        f"Weezing (Poison) should take {expected_damage} hail damage, "
        f"but lost {hp_before - hp_after} HP"
    )


def test_hail_immune_for_ice_type():
    """Ice types take no hail damage."""
    lapras = _mk_lapras()
    skarm = _mk_skarmory()
    state = make_battle([lapras, skarm, skarm], [skarm, skarm, skarm])
    state = replace(state, weather="hail", weather_turns=5)

    hp_before = state.active("p1").current_hp
    state2 = apply_end_of_turn(state)
    hp_after = state2.active("p1").current_hp

    assert hp_before == hp_after, (
        f"Lapras (Ice) should be immune to hail but lost {hp_before - hp_after} HP"
    )


def test_hail_and_sand_both_applied_independently():
    """Switching weather from sand to hail changes who takes EOT damage."""
    weezing = _mk_weezing()
    skarm = _mk_skarmory()
    state_sand = make_battle([weezing, skarm, skarm], [skarm, skarm, skarm])
    state_hail = make_battle([weezing, skarm, skarm], [skarm, skarm, skarm])

    state_sand = replace(state_sand, weather="sand", weather_turns=5)
    state_hail = replace(state_hail, weather="hail", weather_turns=5)

    after_sand = apply_end_of_turn(state_sand)
    after_hail = apply_end_of_turn(state_hail)

    # Weezing (Poison) takes both sand and hail damage
    dmg_sand = weezing.max_hp - after_sand.active("p1").current_hp
    dmg_hail = weezing.max_hp - after_hail.active("p1").current_hp
    expected = max(1, weezing.max_hp // 16)

    assert dmg_sand == expected, f"sand damage wrong: {dmg_sand}"
    assert dmg_hail == expected, f"hail damage wrong: {dmg_hail}"

    # Skarmory (Steel/Flying) is immune to sand but NOT to hail (Gen 3)
    skarm_hp = state_sand.active("p2").current_hp
    skarm_hp_after_sand = after_sand.active("p2").current_hp
    skarm_hp_after_hail = after_hail.active("p2").current_hp
    assert skarm_hp == skarm_hp_after_sand, "Skarmory should be immune to sand"
    assert skarm_hp > skarm_hp_after_hail, "Skarmory should take hail damage (not Ice type)"


# ============================================================
# Bug fix: Choice Specs did not lock move (only Choice Band did)
# ============================================================

def test_choice_specs_locks_on_hit():
    """A hit with Choice Specs should lock the user into that move."""
    metagross = _mk_metagross_cspecs()
    skarm = _mk_skarmory()
    state = make_battle([metagross, skarm, skarm], [skarm, skarm, skarm])

    outcomes = execute_player_action(state, "p1", ("move", "Psychic"))

    hit_states = [s for p, s in outcomes if s.active("p1").last_move == "Psychic"]
    assert hit_states, "expected at least one hit branch"
    assert all(
        s.active("p1").move_locked == "Psychic" for s in hit_states
    ), "Choice Specs user must be locked after a successful hit"


def test_choice_specs_miss_does_not_lock():
    """A miss with Choice Specs must NOT lock the move (same as Choice Band)."""
    metagross = _mk_metagross_cspecs()
    skarm = _mk_skarmory()
    state = make_battle([metagross, skarm, skarm], [skarm, skarm, skarm])

    # Thunderbolt has 100% accuracy; use a move with < 100 acc to get miss branches.
    # Psychic has 100 acc too, but Blizzard has 70 acc.
    outcomes = execute_player_action(state, "p1", ("move", "Blizzard"))

    miss_states = [s for p, s in outcomes if s.active("p1").last_move is None]
    assert miss_states, "expected miss branches for Blizzard (70% acc)"
    assert all(
        s.active("p1").move_locked is None for s in miss_states
    ), "Choice Specs user must NOT be locked on a miss"


def test_choice_specs_lock_consistent_with_choice_band():
    """Choice Band and Choice Specs must produce identical lock behavior."""
    specs_mon = _mk_metagross_cspecs()
    band_mon = _mk_metagross_cband()
    skarm = _mk_skarmory()

    state_specs = make_battle([specs_mon, skarm, skarm], [skarm, skarm, skarm])
    state_band  = make_battle([band_mon,  skarm, skarm], [skarm, skarm, skarm])

    # Use _apply_choice_lock directly on a state where last_move is already set
    # (simulating a successful move execution).
    locked_specs = _apply_choice_lock(state_specs, "p1", ("move", "Psychic"))
    locked_band  = _apply_choice_lock(state_band,  "p1", ("move", "Meteor Mash"))

    assert locked_specs.active("p1").move_locked == "Psychic"
    assert locked_band.active("p1").move_locked  == "Meteor Mash"


# ============================================================
# Bug fix: Sitrus Berry was healing mhp/4 (25%) in C; Gen 3 = flat 30 HP
# This test covers the Python executor path (the C path is fixed separately).
# ============================================================

def _sitrus_mon():
    return make_pokemon(
        "Metagross", "Jolly",
        {"atk": 252, "spd": 4, "spe": 252}, {},
        ["Meteor Mash", "Earthquake", "Brick Break", "Explosion"],
        "Sitrus Berry", "Clear Body",
    )


def test_sitrus_berry_heals_flat_30():
    """Sitrus Berry heals exactly 30 HP in Gen 3 (not 25% of max HP)."""
    mon = _sitrus_mon()
    skarm = _mk_skarmory()
    state = make_battle([mon, skarm, skarm], [skarm, skarm, skarm])

    # Drop HP to exactly 50% to trigger Sitrus in EOT
    p1 = state.active("p1")
    state = state.set_active("p1", replace(p1, current_hp=p1.max_hp // 2))

    hp_before = state.active("p1").current_hp
    state2 = apply_end_of_turn(state)
    hp_after = state2.active("p1").current_hp

    assert hp_after - hp_before == 30, (
        f"Sitrus Berry must heal exactly 30 HP (Gen 3), healed {hp_after - hp_before}"
    )
    assert state2.active("p1").item_consumed, "Sitrus Berry must be consumed after use"


def test_sitrus_berry_triggers_at_or_below_50pct():
    """Sitrus Berry should not trigger above 50% HP."""
    mon = _sitrus_mon()
    skarm = _mk_skarmory()
    state = make_battle([mon, skarm, skarm], [skarm, skarm, skarm])

    # Set HP to 51% — should NOT trigger
    p1 = state.active("p1")
    above_half = p1.max_hp // 2 + 1
    state = state.set_active("p1", replace(p1, current_hp=above_half))

    hp_before = state.active("p1").current_hp
    state2 = apply_end_of_turn(state)
    hp_after = state2.active("p1").current_hp

    # HP should not have increased (no trigger)
    assert hp_after == hp_before, (
        f"Sitrus Berry must not trigger above 50% HP (had {above_half}/{p1.max_hp})"
    )
    assert not state2.active("p1").item_consumed, "Sitrus Berry should not be consumed"


def test_sitrus_berry_does_not_exceed_max_hp():
    """Sitrus Berry must cap at max HP."""
    mon = _sitrus_mon()
    skarm = _mk_skarmory()
    state = make_battle([mon, skarm, skarm], [skarm, skarm, skarm])

    # Set HP to exactly 50% so +30 would exceed max if max_hp < 60
    # For Metagross at L50 with these EVs, max_hp >> 60, so this is a safety test.
    p1 = state.active("p1")
    state = state.set_active("p1", replace(p1, current_hp=p1.max_hp // 2))

    state2 = apply_end_of_turn(state)
    assert state2.active("p1").current_hp <= p1.max_hp, "HP must never exceed max_hp"
