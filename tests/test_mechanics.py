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


def _mk_screener():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Reflect", "Light Screen", "Psychic", "Thunderbolt"],
        None, "Keen Eye",
    )


def _mk_seeder():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Leech Seed", "Synthesis", "Razor Leaf", "Reflect"],
        None, "Keen Eye",
    )


def _mk_protector():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Protect", "Endure", "Reflect", "Safeguard"],
        None, "Keen Eye",
    )


def _mk_toxic_user():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Toxic", "Hidden Power", "Taunt", "Counter"],
        None, "Keen Eye",
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


def test_reflect_sets_side_field_turns():
    """Reflect should set reflect_turns=5 on the user's side."""
    screener = _mk_screener()
    skarm = _mk_skarmory()
    state = make_battle([screener, skarm, skarm], [skarm, skarm, skarm])
    outcomes = execute_player_action(state, "p1", ("move", "Reflect"))
    assert outcomes, "expected at least one outcome"
    assert all(s.field_p1.reflect_turns == 5 for _, s in outcomes)


def test_light_screen_sets_side_field_turns():
    """Light Screen should set light_screen_turns=5 on the user's side."""
    screener = _mk_screener()
    skarm = _mk_skarmory()
    state = make_battle([screener, skarm, skarm], [skarm, skarm, skarm])
    outcomes = execute_player_action(state, "p1", ("move", "Light Screen"))
    assert outcomes, "expected at least one outcome"
    assert all(s.field_p1.light_screen_turns == 5 for _, s in outcomes)


def test_leech_seed_drains_seeded_target_and_heals_opponent():
    """Leech Seed should drain 1/8 max HP at EOT and heal opposing active by same amount."""
    seeder = _mk_seeder()
    target = _mk_aggron()
    skarm = _mk_skarmory()
    state = make_battle([seeder, skarm, skarm], [target, skarm, skarm])
    # Lower seeder HP so we can observe healing.
    p1 = state.active("p1")
    state = state.set_active("p1", replace(p1, current_hp=p1.max_hp // 2))

    outcomes = execute_player_action(state, "p1", ("move", "Leech Seed"))
    assert outcomes, "expected outcome from Leech Seed"
    seeded_state = next((s for _, s in outcomes if s.active("p2").leech_seeded), None)
    assert seeded_state is not None, "expected at least one hit branch that applies Leech Seed"

    p1_before = seeded_state.active("p1").current_hp
    p2_before = seeded_state.active("p2").current_hp
    post = apply_end_of_turn(seeded_state)
    p1_after = post.active("p1").current_hp
    p2_after = post.active("p2").current_hp

    expected = max(1, seeded_state.active("p2").max_hp // 8)
    assert p2_before - p2_after == expected
    assert p1_after - p1_before == expected


def test_protect_blocks_incoming_damage_move():
    """Successful Protect should block incoming damaging moves that turn."""
    protector = _mk_protector()
    attacker = _mk_aggron()
    skarm = _mk_skarmory()
    state = make_battle([protector, skarm, skarm], [attacker, skarm, skarm])

    protect_outcomes = execute_player_action(state, "p1", ("move", "Protect"))
    protected_state = next((s for _, s in protect_outcomes if s.active("p1").protected), None)
    assert protected_state is not None, "expected a successful Protect branch"

    hp_before = protected_state.active("p1").current_hp
    hit_outcomes = execute_player_action(protected_state, "p2", ("move", "Earthquake"))
    assert all(s.active("p1").current_hp == hp_before for _, s in hit_outcomes)


def test_endure_prevents_ko_and_leaves_user_at_1hp():
    """Successful Endure should keep the user alive at 1 HP against lethal damage."""
    protector = _mk_protector()
    attacker = _mk_metagross_cband()
    skarm = _mk_skarmory()
    state = make_battle([protector, skarm, skarm], [attacker, skarm, skarm])

    # Put defender into guaranteed-lethal range for Explosion.
    p1 = state.active("p1")
    state = state.set_active("p1", replace(p1, current_hp=10))

    endure_outcomes = execute_player_action(state, "p1", ("move", "Endure"))
    endure_state = next((s for _, s in endure_outcomes if s.active("p1").enduring), None)
    assert endure_state is not None, "expected a successful Endure branch"

    boom_outcomes = execute_player_action(endure_state, "p2", ("move", "Explosion"))
    assert any(s.active("p1").current_hp == 1 for _, s in boom_outcomes)
    assert all(s.active("p1").current_hp >= 1 for _, s in boom_outcomes)


def test_safeguard_blocks_major_status_from_opponent():
    """Safeguard should block opponent-inflicted major status (e.g. Toxic)."""
    protector = _mk_protector()
    toxic_user = _mk_toxic_user()
    skarm = _mk_skarmory()
    state = make_battle([protector, skarm, skarm], [toxic_user, skarm, skarm])

    sg_outcomes = execute_player_action(state, "p1", ("move", "Safeguard"))
    safeguarded = next((s for _, s in sg_outcomes if s.field_p1.safeguard_turns == 5), None)
    assert safeguarded is not None, "expected Safeguard to apply"

    tox_outcomes = execute_player_action(safeguarded, "p2", ("move", "Toxic"))
    assert all(s.active("p1").status is None for _, s in tox_outcomes)


# ============================================================
# Bug fix: Endure guard `current_hp > 1` prevented survival at exactly 1 HP
# ============================================================

def test_endure_at_1hp_blocks_lethal_damage():
    """Endure must work even when the user is already at exactly 1 HP.

    The original code had `if defender.enduring and defender.current_hp > 1:`
    which skipped the cap when HP==1, letting the mon faint.
    """
    protector = _mk_protector()
    attacker = _mk_metagross_cband()
    skarm = _mk_skarmory()
    state = make_battle([protector, skarm, skarm], [attacker, skarm, skarm])

    # Set defender to exactly 1 HP
    p1 = state.active("p1")
    state = state.set_active("p1", replace(p1, current_hp=1))

    endure_outcomes = execute_player_action(state, "p1", ("move", "Endure"))
    endure_state = next((s for _, s in endure_outcomes if s.active("p1").enduring), None)
    assert endure_state is not None, "expected a successful Endure branch"

    boom_outcomes = execute_player_action(endure_state, "p2", ("move", "Explosion"))
    # Every outcome must leave the enduring mon at exactly 1 HP (alive)
    assert all(
        s.active("p1").current_hp == 1 for _, s in boom_outcomes
    ), "Endure at 1 HP must survive any lethal hit"


# ============================================================
# Bug fix: Swagger applied confusion even under Safeguard
# ============================================================

def _mk_swagger_user():
    return make_pokemon(
        "Skarmory", "Impish",
        {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
        ["Swagger", "Taunt", "Counter", "Toxic"],
        None, "Keen Eye",
    )


def test_swagger_still_boosts_atk_under_safeguard():
    """Swagger +2 Atk must apply on hit even when the target has Safeguard active."""
    swagger_user = _mk_swagger_user()
    protector = _mk_protector()
    skarm = _mk_skarmory()
    state = make_battle([swagger_user, skarm, skarm], [protector, skarm, skarm])

    sg_outcomes = execute_player_action(state, "p2", ("move", "Safeguard"))
    safeguarded = next((s for _, s in sg_outcomes if s.field_p2.safeguard_turns == 5), None)
    assert safeguarded is not None

    swag_outcomes = execute_player_action(safeguarded, "p1", ("move", "Swagger"))
    # Filter to hit branches only (Swagger has 90% acc, miss branches have atk_stage=0)
    hit_states = [s for _, s in swag_outcomes if s.active("p2").atk_stage > 0]
    assert hit_states, "expected at least one hit branch for Swagger"
    assert all(
        s.active("p2").atk_stage == 2 for s in hit_states
    ), "Swagger must still grant +2 Atk even under Safeguard"


def test_swagger_confusion_blocked_by_safeguard():
    """Safeguard must block the confusion from Swagger (but not the +2 Atk)."""
    swagger_user = _mk_swagger_user()
    protector = _mk_protector()
    skarm = _mk_skarmory()
    state = make_battle([swagger_user, skarm, skarm], [protector, skarm, skarm])

    sg_outcomes = execute_player_action(state, "p2", ("move", "Safeguard"))
    safeguarded = next((s for _, s in sg_outcomes if s.field_p2.safeguard_turns == 5), None)

    swag_outcomes = execute_player_action(safeguarded, "p1", ("move", "Swagger"))
    assert all(
        not s.active("p2").confused for _, s in swag_outcomes
    ), "Safeguard must block Swagger's confusion"


# ============================================================
# Bug fix: miss branches did not reset protect_consecutive
# ============================================================

def test_protect_consecutive_resets_on_miss():
    """A missed move (not Protect/Endure) must reset the Protect streak counter.

    If a player on a Protect streak fires a status move that misses, the
    consecutive counter was previously preserved on the miss branch, giving the
    next Protect the wrong (lower) success probability.
    """
    protector = _mk_protector()
    toxic_user = _mk_toxic_user()
    skarm = _mk_skarmory()
    state = make_battle([protector, skarm, skarm], [toxic_user, skarm, skarm])

    # Build a state where P2 has used Protect twice (protect_consecutive=2)
    p2 = state.active("p2")
    state = state.set_active("p2", replace(p2, protect_consecutive=2))

    # Use a move with < 100 accuracy so there are miss branches.
    # Toxic has 90% accuracy (or in some implementations uses 85%).
    toxic_outcomes = execute_player_action(state, "p2", ("move", "Toxic"))

    miss_states = [s for _, s in toxic_outcomes if s.active("p2").protect_consecutive > 0]
    assert not miss_states, (
        "A missed non-Protect move must reset protect_consecutive to 0 on all miss branches"
    )
