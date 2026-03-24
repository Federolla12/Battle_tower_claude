"""Quick rollout throughput benchmark for the C simulator."""

import argparse
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gen3.state import make_pokemon, make_battle
from gen3.c_rollout import c_rollout


def build_default_state():
    skarmory = make_pokemon("Skarmory", "Impish", {"hp": 252, "def": 232, "spe": 24}, {"spa": 30, "spd": 30},
                            ["Hidden Power", "Taunt", "Counter", "Toxic"], "Leftovers", "Keen Eye")
    gengar = make_pokemon("Gengar", "Timid", {"spa": 252, "spd": 4, "spe": 252}, {"atk": 0},
                          ["Giga Drain", "Psychic", "Ice Punch", "Fire Punch"], "Lum Berry", "Levitate")
    snorlax = make_pokemon("Snorlax", "Careful", {"hp": 252, "atk": 4, "spd": 252}, {},
                           ["Rest", "Sleep Talk", "Curse", "Body Slam"], "Chesto Berry", "Thick Fat")
    aggron = make_pokemon("Aggron", "Impish", {"hp": 248, "atk": 8, "def": 252}, {},
                          ["Rock Slide", "Substitute", "Focus Punch", "Thunder Wave"], "Leftovers", "Sturdy")
    weezing = make_pokemon("Weezing", "Sassy", {"hp": 252, "atk": 4, "spd": 252}, {},
                           ["Will-O-Wisp", "Fire Blast", "Sludge Bomb", "Pain Split"], "Lum Berry", "Levitate")
    metagross = make_pokemon("Metagross", "Jolly", {"atk": 252, "spd": 4, "spe": 252}, {},
                             ["Meteor Mash", "Earthquake", "Brick Break", "Explosion"], "Choice Band", "Clear Body")
    return make_battle([skarmory, gengar, snorlax], [aggron, weezing, metagross])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=100000)
    ap.add_argument("--seed", type=int, default=12345)
    args = ap.parse_args()

    state = build_default_state()
    t0 = time.time()
    winp = c_rollout(state, args.sims, args.seed)
    dt = max(1e-9, time.time() - t0)
    print(f"win%={winp*100:.2f} sims={args.sims} sec={dt:.3f} throughput={args.sims/dt:,.0f}/s")


if __name__ == "__main__":
    main()
