# Gen 3 Battle Tower Engine

A Stockfish-style Pokémon battle analysis engine for Gen 3 3v3 singles (Battle Tower-style rules).

Given a battle state, it computes the optimal move and win probability for every option, assuming the opponent plays their best counter.

## Setup

Requires Python 3.10+ and GCC.

```bash
# Compile the C rollout simulator (run once)
# Windows (OpenMP):
gcc -O3 -shared -fopenmp -o gen3\rollout.dll gen3\rollout.c

# Linux/Mac (OpenMP):
gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm
```

## Usage

### Command line analysis
```bash
python main.py
# configurable:
python main.py --depth 1 --rollouts 500 --seed 7
```

### Interactive mode (web UI)
```bash
pip install flask
python server.py
```
Then open http://localhost:5000 in your browser.

### Development / tests
```bash
pip install -r requirements-dev.txt
pytest -q
```

### Rollout benchmark
```bash
python scripts/benchmark_rollout.py --sims 100000
```

## Architecture

- **Simultaneous expectiminimax** with maximin action choice.
- **Exact damage arithmetic** — all 16 rolls computed per the Gen 3 formula.
- **C rollout simulator** for leaf node evaluation.
- **Web analysis board** (Flask + vanilla JS) with iterative deepening.

## Accuracy model: exact vs approximate

- **Exact**: damage formula math, type chart, stat formulas, many core move/status/item interactions.
- **Approximate**: some full-state branching details (especially HP-sensitive damage-roll aggregation) and rollout-based leaf evaluation.
- **Practical takeaway**: win% is strong guidance, but not guaranteed cartridge-perfect in every edge case.

### Modules

| File | Role |
|------|------|
| `gen3/damage.py` | Gen 3 damage formula (exact integer math, all 16 rolls) |
| `gen3/types.py` | Type chart + physical/special split by type |
| `gen3/stats.py` | Stat calculator (base stats + nature + EVs/IVs) |
| `gen3/moves.py` | Move definitions |
| `gen3/state.py` | Frozen 3v3 battle state (hashable for transposition table) |
| `gen3/executor.py` | Move execution with probability branching |
| `gen3/turn.py` | Simultaneous move resolution + switch mechanics |
| `gen3/rollout.c` | C extension: fast Monte Carlo rollout simulator |
| `gen3/c_rollout.py` | Python ctypes wrapper for the C extension |
| `gen3/search.py` | Expectiminimax search with maximin |
