from scripts.debug_moves import classify_move
from gen3.moves import MOVE_DB


def test_every_move_is_classified_for_debugging():
    unhandled = []
    for move_name in sorted(MOVE_DB):
        kind, detail = classify_move(move_name)
        if kind == "unhandled":
            unhandled.append((move_name, detail))

    assert not unhandled, f"Unhandled move effects detected: {unhandled}"
