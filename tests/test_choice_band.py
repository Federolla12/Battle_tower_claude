"""
Regression tests: Choice Band locking behaviour.

Each test verifies exactly one of the cases from CHOICE_BAND_PATCH.md.

Helpers
-------
_make_state()   – two-Pokemon team, p1 attacker has Choice Band
_branches()     – classify result distribution by lock / no-lock
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dataclasses import replace
from gen3.state import make_pokemon, make_battle, EMPTY_FIELD, BattleState
from gen3.turn import execute_player_action


# ============================================================
# Helpers
# ============================================================

def _make_attacker(**overrides):
    """Machamp with Choice Band.  Can be further overridden."""
    mon = make_pokemon(
        "Machamp", "Adamant",
        evs={"atk": 252, "hp": 4, "spe": 252},
        ivs={s: 31 for s in "hp atk def spa spd spe".split()},
        moves=["Cross Chop", "Rock Slide", "Toxic", "Earthquake"],
        item="Choice Band", ability="No Guard", level=50,
    )
    for k, v in overrides.items():
        mon = replace(mon, **{k: v})
    return mon


def _make_target(**overrides):
    """Bulky Swampert — hard to KO in one hit from Cross Chop."""
    mon = make_pokemon(
        "Swampert", "Adamant",
        evs={"hp": 252, "def": 252, "spd": 4},
        ivs={s: 31 for s in "hp atk def spa spd spe".split()},
        moves=["Surf", "Earthquake", "Ice Beam", "Protect"],
        item="Lum Berry", ability="Torrent", level=50,
    )
    for k, v in overrides.items():
        mon = replace(mon, **{k: v})
    return mon


def _make_state(p1_mon=None, p2_mon=None):
    """Build a minimal 1v1 BattleState."""
    p1 = p1_mon or _make_attacker()
    p2 = p2_mon or _make_target()
    dummy_p1 = replace(p1, current_hp=0)   # bench slots — fainted
    dummy_p2 = replace(p2, current_hp=0)
    return make_battle([p1, dummy_p1, dummy_p1], [p2, dummy_p2, dummy_p2])


def _branches(dist, player):
    """
    Split a probability distribution into locked / unlocked outcome sets.

    Returns (p_locked, p_unlocked) — probabilities sum to 1.
    """
    p_locked = sum(prob for prob, s in dist
                   if s.active(player).move_locked is not None)
    p_unlocked = sum(prob for prob, s in dist
                     if s.active(player).move_locked is None)
    return p_locked, p_unlocked


# ============================================================
# 1. Normal hit — should lock
# ============================================================

def test_normal_hit_locks():
    """Choice Band + move connects → must lock on all hit branches."""
    state = _make_state()
    action = ("move", "Cross Chop")   # acc=80, guaranteed hit here
    dist = execute_player_action(state, "p1", action)

    p_locked, p_unlocked = _branches(dist, "p1")
    assert p_locked > 0.0, "Expected at least one locked branch"
    # Cross Chop has acc=80 — miss branches must not lock
    # Verify hit branches all lock
    for prob, s in dist:
        if s.active("p1").last_move == "Cross Chop":
            assert s.active("p1").move_locked == "Cross Chop", \
                "Hit branch did not lock Choice Band"


# ============================================================
# 2. Accuracy miss — must NOT lock
# ============================================================

def test_miss_does_not_lock():
    """Choice Band + damaging move miss → move_locked must stay None."""
    # Rock Slide: acc=90 → 10 % miss probability
    state = _make_state()
    action = ("move", "Rock Slide")
    dist = execute_player_action(state, "p1", action)

    for prob, s in dist:
        if s.active("p1").last_move is None:
            # This is a miss branch
            assert s.active("p1").move_locked is None, \
                "Miss branch incorrectly set move_locked"


# ============================================================
# 3. Flinch prevents action — must NOT lock
# ============================================================

def test_flinch_does_not_lock():
    """Choice Band + user flinched → move_locked stays None."""
    p1 = _make_attacker(flinched=True)
    state = _make_state(p1_mon=p1)
    action = ("move", "Cross Chop")
    dist = execute_player_action(state, "p1", action)

    assert len(dist) == 1, "Expected single outcome when flinched"
    assert dist[0][1].active("p1").move_locked is None, \
        "Flinched Pokemon should not lock Choice Band"


# ============================================================
# 4. Full paralysis skip — must NOT lock
# ============================================================

def test_paralysis_skip_does_not_lock():
    """Choice Band + full paralysis roll → locked branch must be < 100%."""
    p1 = _make_attacker(status="paralyze")
    state = _make_state(p1_mon=p1)
    action = ("move", "Cross Chop")
    dist = execute_player_action(state, "p1", action)

    # Paralysis produces a 25% skip branch and a 75% act branch
    p_locked, p_unlocked = _branches(dist, "p1")
    assert p_unlocked > 0.0, "Para-skip branch should be unlocked"
    assert abs(p_locked + p_unlocked - 1.0) < 1e-9, "Probs must sum to 1"


# ============================================================
# 5. Sleep — skipped turn must NOT lock
# ============================================================

def test_sleep_skip_does_not_lock():
    """Choice Band + asleep (status_turns > 1) → cannot act, no lock."""
    p1 = _make_attacker(status="sleep", status_turns=3)
    state = _make_state(p1_mon=p1)
    action = ("move", "Cross Chop")
    dist = execute_player_action(state, "p1", action)

    assert len(dist) == 1, "Sleeping mon should produce a single outcome"
    assert dist[0][1].active("p1").move_locked is None, \
        "Asleep + skipped turn should not lock Choice Band"


# ============================================================
# 6. Freeze (stay frozen) — must NOT lock
# ============================================================

def test_freeze_stay_does_not_lock():
    """Frozen branches where the mon cannot act should not lock."""
    p1 = _make_attacker(status="freeze")
    state = _make_state(p1_mon=p1)
    action = ("move", "Cross Chop")
    dist = execute_player_action(state, "p1", action)

    for prob, s in dist:
        mon = s.active("p1")
        if mon.status == "freeze":
            # Still frozen — did not move
            assert mon.move_locked is None, \
                "Still-frozen branch must not lock Choice Band"


# ============================================================
# 7. Faint before moving — must NOT lock
# ============================================================

def test_faint_before_move_does_not_lock():
    """Dead mon gets no action and no Choice Band lock."""
    p1 = _make_attacker(current_hp=0)
    state = _make_state(p1_mon=p1)
    action = ("move", "Cross Chop")
    dist = execute_player_action(state, "p1", action)

    assert len(dist) == 1
    assert dist[0][1].active("p1").move_locked is None, \
        "Fainted mon should not lock Choice Band"


if __name__ == "__main__":
    tests = [
        test_normal_hit_locks,
        test_miss_does_not_lock,
        test_flinch_does_not_lock,
        test_paralysis_skip_does_not_lock,
        test_sleep_skip_does_not_lock,
        test_freeze_stay_does_not_lock,
        test_faint_before_move_does_not_lock,
    ]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"  PASS  {fn.__name__}")
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
            failed.append(fn.__name__)
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {e}")
            failed.append(fn.__name__)

    print()
    if failed:
        print(f"{len(failed)} test(s) FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print(f"All {len(tests)} tests passed.")
