# Gen 3 Battle Tower Engine

A Stockfish-style Pokemon battle analysis engine for Gen 3 3v3 singles (Battle Tower rules).

Given a battle state, it computes the optimal move and win probability for every option, assuming the opponent plays their best counter.

## Setup

Requires Python 3.10+ and GCC.

```bash
# Compile the C rollout simulator (run once)
# Windows:
gcc -O3 -shared -o gen3\rollout.dll gen3\rollout.c

# Linux/Mac:
gcc -O3 -shared -fPIC -o gen3/rollout.so gen3/rollout.c -lm
```

## Usage

```bash
python main.py
```

Output:
```
P1 (Skarmory) MOVE ANALYSIS:
Action                    Win%  vs Best Counter
-------------------------------------------------------
Hidden Power            37.0%  (Switch→Weezing) ★
Switch→Snorlax          36.3%  (Substitute)
Toxic                   35.5%  (Switch→Metagross)
Counter                 34.3%  (Switch→Weezing)
Taunt                   34.0%  (Switch→Metagross)
Switch→Gengar           22.2%  (Rock Slide)
```

## Architecture

- **Exact probability search** (depth 2) with simultaneous move resolution
- **C rollout simulator** (~175,000 games/sec) for leaf node evaluation
- **Maximin strategy** — finds the move with the best guaranteed win rate
- **Gen 3 damage formula** verified roll-by-roll against Smogon's ADV calc

### Modules

| File | Role |
|------|------|
| `gen3/damage.py` | Gen 3 damage formula (exact integer math, all 16 rolls) |
| `gen3/types.py` | Type chart + physical/special split by type |
| `gen3/stats.py` | Stat calculator (base stats + nature + EVs/IVs) |
| `gen3/moves.py` | Move definitions for all 24 moves |
| `gen3/state.py` | Frozen 3v3 battle state (hashable for transposition table) |
| `gen3/executor.py` | Move execution with probability branching |
| `gen3/turn.py` | Simultaneous move resolution + switch mechanics |
| `gen3/rollout.c` | C extension: fast Monte Carlo rollout simulator |
| `gen3/c_rollout.py` | Python ctypes wrapper for the C extension |
| `gen3/search.py` | Expectiminimax search with maximin |
