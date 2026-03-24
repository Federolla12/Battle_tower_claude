"""
Gen 3 Battle Engine - 3v3 Analysis

Setup (run once):
  Windows:  gcc -O3 -shared -fopenmp -o gen3\rollout.dll gen3\rollout.c
  Linux:    gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm

Run:
  python main.py
"""
import sys, os, time, random, argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen3.state import make_pokemon, make_battle
from gen3.search import SearchEngine, display_analysis

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

def parse_args():
    p = argparse.ArgumentParser(description="Gen 3 Battle Tower CLI analyzer")
    p.add_argument("--depth", type=int, default=2, help="Search depth (default: 2)")
    p.add_argument("--rollouts", type=int, default=200, help="MC rollouts per leaf (default: 200)")
    p.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    random.seed(args.seed)
    state = make_battle([skarmory, gengar, snorlax], [aggron, weezing, metagross])
    engine = SearchEngine(max_depth=args.depth, mc_rollouts=args.rollouts)
    t = time.time()
    result = engine.analyze(state)
    display_analysis(result, state)
    print(f"  Time: {time.time()-t:.1f}s")
