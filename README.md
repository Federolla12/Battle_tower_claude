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

### Modules

| File | Role |
|------|------|
| `gen3/damage.py` | Gen 3 damage formula (exact integer math, all 16 rolls) |
| `gen3/types.py` | Type chart + physical/special split by type |
| `gen3/stats.py` | Stat calculator (base stats + nature + EVs/IVs) |
| `gen3/moves.py` | Move definitions (191 moves) |
| `gen3/state.py` | Frozen 3v3 battle state (hashable for transposition table) |
| `gen3/executor.py` | Move execution with probability branching |
| `gen3/turn.py` | Simultaneous move resolution + switch mechanics |
| `gen3/rollout.c` | C extension: fast Monte Carlo rollout simulator |
| `gen3/c_rollout.py` | Python ctypes wrapper for the C extension |
| `gen3/search.py` | Expectiminimax search with maximin |

---

## Engine accuracy: exact vs approximate vs stub

The engine has three tiers of implementation fidelity. Understanding which tier applies to each mechanic tells you how much to trust the win% for a given position.

### Tier 1 — Exact

These are computed precisely from cartridge math. Win% is fully reliable when the position only involves these.

| Mechanic | Notes |
|---|---|
| Damage formula | All 16 damage rolls, exact integer arithmetic, Gen 3 rounding |
| Type chart | Full Gen 3 table including immunity chains |
| Physical/special split | Gen 3 type-based split (not physical/special category) |
| Stat formula | Base + nature + EVs + IVs at level 50, exact |
| Stat stages | ×2/3/4 etc., applied exactly, capped ±6 |
| Crit rate | 1/16 base; branched explicitly in tree search |
| Status infliction | Burn, Paralyze, Poison, Toxic, Freeze, Sleep — exact type/status immunity checks |
| Paralysis skip | 25% chance; branched explicitly |
| Sleep counter | Decremented per turn; wake-up on turn 0 |
| Freeze thaw | 20% per turn; branched explicitly |
| Toxic counter | Damage = `max_hp × turns / 16`, counter increments EOT |
| EOT effects | Leftovers, burn, poison, toxic, weather damage, screen countdown |
| Hail damage | 1/16 max HP per turn; Ice types immune (Gen 3 rules) |
| Sand damage | 1/16 max HP per turn; Rock/Ground/Steel immune |
| Choice Band | Locks user on hit; not locked on miss/skip/flinch/faint |
| Choice Specs | Same lock rules as Choice Band |
| Lum/Chesto Berry | Consumed immediately on status infliction |
| Sitrus Berry | Heals flat **30 HP** (Gen 3) at ≤50% HP, consumed |
| Salac/Petaya/Liechi Berry | +1 stage at ≤25% HP, consumed |
| Shell Bell | Heals 1/8 of damage dealt per hit |
| Spikes | 1–3 layers; 1/8, 1/6, 1/4 damage on switch-in; Flying/Levitate immune |
| Intimidate | −1 Atk on entry; blocked by Clear Body/Hyper Cutter |
| Natural Cure | Cures status on switch-out |
| Switch mechanics | Volatiles cleared, choice lock reset, entry hazards applied |
| Speed ties | 50/50 branch in tree; both orderings evaluated |

### Tier 2 — Approximate

These are modelled but with simplifications. Win% is good guidance but may be slightly off in HP-sensitive situations.

| Mechanic | Approximation |
|---|---|
| Damage branching | Survive rolls split into two groups (low/high bracket) rather than all 16 distinct outcomes; avoids exponential state explosion |
| MC rollout evaluation | C extension runs stochastic rollouts at leaf nodes; win% at depth limit is an estimate, not exact |
| Sleep Talk | Picks a move uniformly at random from non-Sleep Talk moves; does not model the Gen 3 "cannot pick same move twice" rule |
| Confuse self-hit | Flat 50% chance; exact duration branching (2–5 turns) |
| Flinch | Resolved as a separate branch from the hit; accurate for most cases |
| Recoil/Drain | Applied to averaged damage bracket, not each roll |
| Counter/Mirror Coat | Uses `last_damage_taken` which tracks the averaged bracket, not the exact roll |
| Guts / Hustle | Damage multiplier applied; Hustle accuracy penalty applied |
| BrightPowder | Accuracy reduction applied at move level (−10%) |
| Thick Fat | Halves Fire/Ice damage; exact |
| Serene Grace | Doubles secondary effect chance; exact |
| Shed Skin | 30% chance to cure status per turn (EOT); exact |

### Tier 3 — Stubbed (no-op)

These mechanics are recognised (won't crash) but have no effect in simulation. Positions involving these are less accurate.

| Move / Mechanic | Status |
|---|---|
| Protect / Endure | No-op; always fails silently |
| Attract | No-op; infatuation not tracked |
| Leech Seed | No-op; drain not applied |
| Baton Pass | No-op; staged stats not passed |
| Encore / Disable / Torment | No-op; move restriction not enforced |
| Perish Song | No-op; 3-turn KO not applied |
| Trick / Skill Swap | No-op; items/abilities not swapped |
| Reflect / Light Screen | Field state tracked, screens decrement, but **damage reduction not applied** |
| Safeguard | No-op |
| Substitute damage absorption | Exact — but moves that "fail vs Sub" (e.g. status) are blocked correctly |
| Confusion (via Swagger / Confuse Ray) | Duration and self-hit chance modelled; but the Swagger +2 Atk boost to the target is applied exactly |
| PP tracking | Not tracked; moves never run out |
| Speed Boost | No-op |
| Flash Fire | No-op; Fire moves not absorbed |
| Arena Trap / Shadow Tag | No-op; switching not restricted |
| Wonder Guard | No-op; non-super-effective moves not blocked |
| Synchronize | No-op; status not mirrored |
| Compound Eyes | No-op; accuracy not boosted |
| Huge Power / Pure Power | No-op; Attack not doubled |
| Weather-boosted accuracy | Thunder 100% in rain, Blizzard 100% in hail — not implemented |
| Weather-boosted power | Solar Beam 50% in non-sun, etc. — not implemented |

### Known Gen 3 rules not yet modelled

- **Speed ties**: P1 wins deterministically in fast rollouts (C extension) — only the exact tree branches 50/50
- **OHKO moves**: 30% accuracy implemented; Sturdy blocks correctly
- **Ghost-type Curse**: not implemented (treated as no-op)

---

## Species coverage

35 of the 376 Battle Frontier species are in the engine's stat database. The Battle Frontier set browser shows all 883 sets, but only sets whose species are in the engine can be loaded into a battle.

To add a species: add an entry to `gen3/stats.py` (`BASE_STATS`, `SPECIES_TYPES`) and optionally to `gen3/bf_sets.json`.
