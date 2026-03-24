# Task: Parallelize the Gen 3 Battle Engine

## Context

Read `HANDOFF.md` in this repo first for full architecture details.

This is a Pokemon Gen 3 3v3 battle analysis engine. It uses expectiminimax search with Monte Carlo rollouts at leaf nodes. The MC rollouts run via a C extension (`gen3/rollout.c`) that does ~175,000 games/sec on a single thread.

**The problem:** The engine only uses ~10% CPU on a modern multi-core machine because everything runs single-threaded. The MC rollouts at leaf nodes are embarrassingly parallel — each rollout is completely independent. The search tree itself also has parallelism at the matrix-cell level.

## What needs to change

### 1. Parallelize the C rollout function (highest impact)

In `gen3/rollout.c`, the `run_rollouts()` function runs `nsim` simulations in a serial loop. This should use threads.

**Approach:** Use OpenMP (simplest) or pthreads. OpenMP is a one-line change:

```c
EXPORT int run_rollouts(State*init, int nsim, unsigned int seed) {
    if(!MV||!NMV) return nsim/2;
    init_tc();
    int wins = 0;

    #pragma omp parallel reduction(+:wins)
    {
        // Each thread gets its own RNG state seeded differently
        unsigned int local_rs = seed ^ (omp_get_thread_num() * 2654435761u);
        
        #pragma omp for schedule(static)
        for(int sim = 0; sim < nsim; sim++) {
            // ... existing simulation code but using local_rs instead of global rs
        }
    }
    return wins;
}
```

**Critical issue:** The current code uses a global `rs` variable for the RNG. This MUST be made thread-local — either pass it through all functions or use `__thread`/thread_local storage. Every function that calls `ri()` or `rf()` currently reads/writes the global `rs`. You need to either:
- Make `rs` thread-local: `static __thread unsigned rs;` (GCC/Clang) 
- Or pass an RNG state pointer through every function (cleaner but more invasive)

The thread-local approach is simplest. Change:
```c
static unsigned rs = 12345;
```
to:
```c
static __thread unsigned rs = 12345;
```

Then each thread's `rs` is independent. Seed it per-thread at the start of `run_rollouts()`.

**Compile with:** `gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm`
Windows: `gcc -O3 -shared -fopenmp -o gen3\rollout.dll gen3\rollout.c`

On the Python side (`gen3/c_rollout.py`), the ctypes call doesn't need to change — OpenMP handles the threading inside C. But Python's GIL won't interfere because ctypes releases the GIL during C function calls.

**Expected speedup:** On an 8-core machine, roughly 6-7× faster rollouts (not perfect 8× due to overhead). This means the MC rollout bottleneck drops from ~800s to ~120s for depth 2, or equivalently you can do 6× more rollouts in the same time for better accuracy.

### 2. Parallelize the search matrix (medium impact)

In `gen3/search.py`, the `analyze()` method builds a payoff matrix by iterating over all (P1 action × P2 action) pairs:

```python
for a1 in actions_p1:
    for a2 in actions_p2:
        outcomes = resolve_turn(state, a1, a2)
        ev = sum(prob * self.search(s, 1) for prob, s in outcomes)
        matrix[(a1, a2)] = ev
```

Each cell `(a1, a2)` is independent and can be computed in parallel. However, `resolve_turn` and `search` are pure Python with frozen dataclasses, so you can't use threading (GIL). Options:

**Option A: `multiprocessing`** — spawn worker processes, each computing a subset of matrix cells. The challenge is that `BattleState` objects need to be serialized/deserialized across process boundaries. Since they're frozen dataclasses, pickle works but adds overhead.

**Option B: `concurrent.futures.ProcessPoolExecutor`** — cleaner API:
```python
from concurrent.futures import ProcessPoolExecutor

def _compute_cell(args):
    state, a1, a2, max_depth, mc_rollouts = args
    engine = SearchEngine(max_depth=max_depth, mc_rollouts=mc_rollouts)
    outcomes = resolve_turn(state, a1, a2)
    ev = sum(prob * engine.search(s, 0) for prob, s in outcomes)
    return (a1, a2, ev)

# In analyze():
with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
    tasks = [(state, a1, a2, self.max_depth, self.mc_rollouts)
             for a1 in actions_p1 for a2 in actions_p2]
    for a1, a2, ev in pool.map(_compute_cell, tasks):
        matrix[(a1, a2)] = ev
```

**Downside:** Each process gets its own transposition table, so TT hits across cells are lost. For depth 1 this barely matters (TT hit rate is already ~0%). For deeper searches it would matter more.

**Option C (recommended): Only parallelize the MC rollouts (step 1 above), keep the search single-threaded.** This is by far the simplest and gives the most benefit. The C rollout is where 95%+ of the time is spent at depth 1+. Making the Python search parallel adds complexity for maybe 10% more speedup.

### 3. Update the server's iterative deepening stages

In `server.py`, the `run_analysis()` function defines analysis stages. After fixing the off-by-one bug (which was already done — `analyze()` now calls `search(s, 0)` instead of `search(s, 1)`), the timing has changed:

- depth 0 = pure rollout (~0.1s)
- depth 1 = 1 turn lookahead (~4s with 200 rollouts)
- depth 2 = 2 turns lookahead (~120s+ currently, ~20-30s with parallel C rollouts)

Update the stages to match the new reality:
```python
stages = [
    (0, 500,  "Quick estimate"),    # ~0.1s
    (1, 200,  "Depth 1"),           # ~4s (or ~1s with parallel rollouts)
    (1, 500,  "Depth 1 refined"),   # ~10s (or ~2s with parallel)
    (2, 100,  "Depth 2"),           # only if parallel rollouts make this <30s
]
```

Also add a timeout mechanism — if a stage takes more than N seconds, skip to reporting the best result so far rather than blocking the UI.

### 4. Increase rollout count now that they're faster

With parallel C rollouts, you can afford many more simulations per leaf. At depth 1 with 8 threads, you could do 1000 rollouts per leaf instead of 200, significantly reducing variance in the win% estimates. This matters because the current results fluctuate by 2-3% between runs at 200 rollouts.

## Files to modify

1. **`gen3/rollout.c`** — Add OpenMP pragmas, make RNG thread-local
2. **`gen3/c_rollout.py`** — No changes needed if using OpenMP (threading is internal to C)
3. **`server.py`** — Update iterative deepening stages, add timeout mechanism
4. **Compilation instructions in README.md** — Add `-fopenmp` flag

## Testing

After changes:
```bash
# Recompile with OpenMP
gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm

# Benchmark rollout speed
python -c "
from gen3.c_rollout import c_rollout
from gen3.state import make_pokemon, make_battle
import time
# ... build state ...
t=time.time()
wp = c_rollout(state, 100000, 42)
print(f'{100000/(time.time()-t):.0f} games/sec')
"
```

Expected: ~1,000,000+ games/sec on 8 cores (vs ~175,000 single-threaded).

## Important: do NOT change

- The `Mon` and `State` struct layouts in rollout.c — they must match `c_rollout.py`'s `CMon`/`CState` exactly
- The `init_moves_data()` interface — Python passes move data at startup
- The frozen dataclass design in Python — it's needed for the transposition table
- The maximin search logic — the game theory is correct
