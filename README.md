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

### Command line analysis
```bash
python main.py
```

### Interactive mode (web UI)
```bash
pip install flask
python server.py
```
Then open http://localhost:5000 in your browser. You'll see:
- **Eval bar** — win probability updating in real-time as analysis deepens
- **Team display** — HP bars, status conditions, stat changes, items
- **Move analysis** — click any move to play it; engine picks the opponent's best counter
- **Move history** — full log of each turn

The analysis runs iterative deepening in the background: instant rough estimate → depth 1 → depth 2, with the UI updating at each stage.

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

- **Probability-tree search** (depth 2) with simultaneous move resolution
- **Exact damage arithmetic** — all 16 rolls computed per the Gen 3 formula, verified against Smogon's ADV calc
- **KO-threshold branching** — roll sets that produce a KO vs. those that don't are kept as separate branches; survive rolls are split at the median into a low-damage and a high-damage bracket
- **C rollout simulator** (~175,000 games/sec) for leaf node evaluation
- **Maximin strategy** — finds the move with the best guaranteed win rate

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
