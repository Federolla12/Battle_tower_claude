#!/usr/bin/env python3
"""Debug move-effect coverage for every move currently in MOVE_DB.

This script classifies each move as:
- damaging move with no status effect key
- move with secondary effect handler
- status-effect handler
- explicit stub/no-op handler
- unhandled effect (bug)
"""

from __future__ import annotations

import inspect
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gen3 import executor
from gen3.moves import MOVE_DB


def _extract_effect_keys(fn) -> set[str]:
    src = inspect.getsource(fn)
    return set(re.findall(r'(?:if|elif) eff == "([^"]+)"', src))


# Explicit no-op effects documented in execute_status_move.
STUB_EFFECTS: set[str] = {
    "reflect",
    "light_screen",
    "safeguard",
    "attract",
    "protect",
    "endure",
    "baton_pass",
    "destiny_bond",
    "skill_swap",
    "trick",
    "memento",
    "encore",
    "disable",
    "perish_song",
    "trap",
    "follow_me",
    "metronome",
    "role_play",
    "recycle",
    "grudge",
    "spite",
    "torment",
    "imprison",
    "leech_seed",
    "evasion_plus1",
    "acc_minus1",
}

SECONDARY_KEYS = _extract_effect_keys(executor.apply_secondary_effect)
STATUS_KEYS = _extract_effect_keys(executor.execute_status_move)


def classify_move(move_name: str) -> tuple[str, str]:
    move = MOVE_DB[move_name]
    eff = move.effect

    if not eff:
        return "damage_no_effect", "Damaging move with no effect key"
    if eff in SECONDARY_KEYS:
        return "secondary", f"Secondary effect handled: {eff}"
    if eff in STATUS_KEYS:
        return "status", f"Status effect handled: {eff}"
    if eff in STUB_EFFECTS:
        return "stub", f"Explicit stub/no-op: {eff}"
    return "unhandled", f"UNHANDLED effect key: {eff}"


def main() -> int:
    counts: Counter[str] = Counter()
    rows: list[tuple[str, str, str]] = []

    for move_name in sorted(MOVE_DB):
        kind, detail = classify_move(move_name)
        counts[kind] += 1
        rows.append((move_name, kind, detail))

    for move_name, kind, detail in rows:
        print(f"[{kind:16}] {move_name:20} - {detail}")

    print("\nSummary:")
    for key in sorted(counts):
        print(f"  {key:16}: {counts[key]}")

    if counts["unhandled"]:
        print("\nFound unhandled move effects. Please add handler or stub classification.")
        return 1

    print("\nAll moves are classified (handled or explicitly stubbed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
