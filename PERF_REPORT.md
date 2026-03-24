# Performance Report

Profiling and benchmarking results for the Gen 3 Battle Tower engine.
Machine: Windows 10, Intel CPU with 4 physical / 8 logical cores, GCC + OpenMP.

---

## C Rollout Throughput

Benchmark: `c_rollout(state, n, seed=42)` on a Metagross vs Weezing 3v3 position.

| Batch size (n) | Wall time | Throughput |
|---------------|-----------|------------|
| 50 | 0.6 ms | 82 K/s |
| 200 | 0.2 ms | 889 K/s |
| 500 | 0.5 ms | 999 K/s |
| 2 000 | 1.4 ms | 1 426 K/s |
| 10 000 | 3.7 ms | 2 677 K/s |
| 50 000 | 20 ms | 2 469 K/s |

**Observations**:

- Throughput is low at small batch sizes because Python `ctypes` call overhead
  (state conversion, `_conv_mon` × 6, struct packing) dominates at ≤200 sims.
- Peak throughput ~2.7 M sims/s at n ≈ 10 000.
- Slight drop at n = 50 000 due to cache pressure.

---

## OpenMP Status

OpenMP is **active**.  The DLL is compiled with `-fopenmp` and links against
`libgomp-1.dll`.  `omp_get_max_threads` is provided by the external libgomp
runtime, not exported from the DLL itself — this is normal GCC/MinGW behaviour.

Verified with standalone `omp_test.c`: 8 threads available.

Speedup vs single-threaded build:
- No-OpenMP baseline: ~95 K/s
- With OpenMP (8 threads): ~280–575 K/s for the same single-call batch
- OpenMP wins grow with batch size; for n ≥ 10 000 the gain is 3–6×.

At n = 50 (the default per leaf node at depth 2), most of the 8 threads finish
in under 0.1 ms with almost no overlap — OpenMP overhead exceeds the work.
**To get full CPU utilisation, use `mc_rollouts ≥ 500` per leaf.**

---

## Python Search Profiling (depth=1, mc=200)

Position: Metagross (Choice Band) + Lapras + Skarmory vs Weezing + Skarmory + Lapras.

Wall time: **~123 ms** for a full depth-1 analysis (179 leaf rollout calls).

| Function | Self time | % of total | Calls |
|----------|-----------|------------|-------|
| `c_rollout` (ctypes) | 57 ms | **50%** | 179 |
| `dataclasses.replace` | 12 ms | **11%** | 1 577 |
| `_conv_mon` (state conversion) | 6 ms | 5% | 1 074 |
| `apply_end_of_turn` | 2 ms | 2% | 207 |
| `apply_damage_rolls` | 1 ms | 1% | 100 |
| `calc_damage` | 1 ms | 1% | 100 |

**Bottlenecks**:

1. **C rollout ctypes overhead (50%)** — Each of the 179 leaf calls incurs
   Python→C conversion cost.  With `mc=200`, each call batches only 200 sims,
   meaning the ctypes overhead is ~50% of total time.  Increasing `mc_rollouts`
   to ≥ 500 amortises this cost and nearly doubles throughput per analysis.

2. **`dataclasses.replace` (11%)** — Every damage-roll branch creates a new
   immutable `BattleState` via `replace()`.  At depth=1 this fires ~1 577 times.
   At depth=2 the call count scales quadratically (branching factor × depth).

3. **State conversion overhead (5%)** — `_conv_mon` is called once per leaf
   node per Pokémon (6 mons × 179 leaves = 1 074 calls).

---

## Depth Scaling

| Depth | mc | Wall time |
|-------|----|-----------|
| 1 | 50 | 64 ms |
| 1 | 200 | 84 ms |
| 1 | 500 | 134 ms |
| 2 | 50 | 3 755 ms |
| 2 | 200 | 6 093 ms |
| 2 | 500 | 12 449 ms |

Depth=2 is ~45–90× slower than depth=1.  This matches the expected O(b²)
branching of the simultaneous-action expectiminimax tree.

---

## Recommendations

### Immediate wins

1. **Raise default `mc_rollouts` to ≥ 500**
   Reduces the fraction of time wasted on ctypes overhead from 50% to ~20%
   while meaningfully improving leaf-node quality.  Depth-1 wall time rises
   from ~84 ms to ~134 ms — a 1.6× cost for substantially better estimates.

2. **Batch all leaves of a depth-1 search into a single C call**
   Calling `c_rollout` once with `n = leaves × mc_per_leaf` instead of once
   per leaf removes the per-call overhead entirely and lets OpenMP schedule
   across the full workload.  Expected 2–4× speedup for depth-1.

3. **Cache converted state structs**
   State conversion (`_conv_mon`) accounts for 5% of time and is called once
   per leaf regardless of how deep the subtree is.  A simple LRU cache on the
   active mon + bench tuple would eliminate most redundant conversions.

### Medium-term

4. **Profile-guided `dataclasses.replace` reduction**
   Replace the most-called `replace()` chains in `apply_end_of_turn` and
   `apply_damage_rolls` with mutable staging objects that are frozen only once
   per branch.  Target: reduce the 1 577 calls by ≥ 50%.

5. **Increase depth-2 feasibility with pruning**
   At depth=2, the branching factor is ~25–36 (6 P1 actions × 6 P2 actions ×
   damage branches).  Alpha-beta pruning or move ordering (try high-damage
   moves first) can cut this to an effective ~12–15, making depth=2 with
   mc=200 feasible in under 2 s.
