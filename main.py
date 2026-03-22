"""
Gen 3 Battle Engine - 3v3 Analysis

Setup (run once):
  Windows:  gcc -O3 -shared -o gen3\rollout.dll gen3\rollout.c
  Linux:    gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm

Run:
  python main.py
"""
import sys, os, time, random

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

if __name__ == "__main__":
    random.seed(42)
    state = make_battle([skarmory, gengar, snorlax], [aggron, weezing, metagross])
    engine = SearchEngine(max_depth=2, mc_rollouts=200)
    t = time.time()
    result = engine.analyze(state)
    display_analysis(result, state)
    print(f"  Time: {time.time()-t:.1f}s")
