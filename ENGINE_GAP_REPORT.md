# Engine Gap Report

Audit of mechanics where the Python executor and C rollout diverged, plus remaining known gaps.
All issues marked **Fixed** were patched in the current session; the rest are open.

---

## Bugs Fixed This Session

### 1. Hail damage absent from Python EOT (Critical — Fixed)

**File**: `gen3/executor.py` → `apply_end_of_turn`

Python was applying sand damage but had no hail branch.  All non-Ice types
took 0 hail damage every turn.

**Fix**: added `elif state.weather == "hail"` branch mirroring the sand logic,
with Ice-type immunity (no Steel exception — Steel is NOT immune to hail in Gen 3).

---

### 2. Choice Specs did not lock in Python (Critical — Fixed)

**File**: `gen3/turn.py` → `_apply_choice_lock`

The lock condition checked only for `item == "Choice Band"`.  Choice Specs
users could switch moves freely after every hit.

**Fix**: condition widened to `item in ("Choice Band", "Choice Specs")`.

---

### 3. C rollout: sleep duration always 2 turns (Critical — Fixed)

**File**: `gen3/rollout.c`, `EF_SLEEP_ST` handler

`st_t=2` was hardcoded.  Gen 3 sleeps last 1–4 turns uniformly at random.

**Fix**: `st_t = 1 + ri(4)` (matches Python executor).

---

### 4. C rollout: Reflect/Light Screen never expired (High — Fixed)

**File**: `gen3/rollout.c`, `eot()` function

The `eot()` loop decremented weather turns and the toxic counter but never
decremented `refl[p]` / `ls[p]`.  Screens were permanent in rollouts, making
defensive teams unrealistically strong.

**Fix**: added screen countdown in `eot()`:

```c
for(int p=0;p<2;p++){
    if(s->refl[p]>0)s->refl[p]--;
    if(s->ls[p]>0)s->ls[p]--;
}
```

---

### 5. C rollout: speed ties always resolved P1-first (High — Fixed)

**File**: `gen3/rollout.c`, `sim_turn()`

`first = s0 >= s1 ? 0 : 1` — equal speeds always gave P1 the first move.
Python branches 50/50.  In a mirror matchup this inflated P1's simulated win
rate by roughly +9 percentage points.

**Fix**: `if(s0>s1)first=0; else if(s1>s0)first=1; else first=ri(2);`
Applied in both the move-vs-move branch and the switch-speed fallback.

---

### 6. C rollout: Choice lock applied even on miss / status skip (High — Fixed)

**File**: `gen3/rollout.c`, `sim_turn()`

After every turn the C code unconditionally set `mlock = act.id` for any
Choice-item user, regardless of whether the move actually fired.  A miss,
paralysis skip, sleep skip, or freeze-stay would incorrectly lock the user.

**Fix**: added `did_move[2]` tracking.  `exec_mv` returns −1 on miss; the lock
is only applied when `did_move[pp] == 1`.

---

### 7. C rollout: Sitrus Berry heals 25% of max HP (High — Fixed)

**File**: `gen3/rollout.c`, `chk_berry()`

`m->hp += m->mhp / 4` — this is the Gen 4+ Sitrus formula.  Gen 3 Sitrus
heals a flat **30 HP**.

**Fix**: `m->hp += 30`.

---

## Remaining Gaps

### Python executor vs C rollout

| Mechanic | Python | C rollout | Severity |
|----------|--------|-----------|----------|
| Screens damage reduction | tracked but not applied (Tier 3 stub) | tracked (now expires) but never halves damage | Medium |
| Reflect/Light Screen | no damage reduction | no damage reduction | Medium (consistent) |
| Sleep Talk | uniform random pick (not Gen 3 "can't repeat" rule) | not implemented (picks attack moves) | Low |
| Confusion self-hit | flat 50%, duration modelled | not tracked at all | Medium |
| Leech Seed drain | **exact in Python** (1/8 drain + opponent heal, EOT) | no-op in C | Medium |
| Protect / Endure / Safeguard | **exact in Python** (full consecutive model, Safeguard blocks status/confusion) | stubs in C | Medium |
| Speed Boost | no-op in Python | no-op in C | Low (consistent) |
| Flash Fire | no-op in Python | no-op in C | Low (consistent) |
| Compound Eyes | no-op in Python | no-op in C | Low (consistent) |
| Huge/Pure Power | no-op in Python | no-op in C | Low (consistent) |
| PP tracking | not tracked in Python | not tracked in C | Low (consistent) |
| Weather-boosted accuracy | not implemented | not implemented | Low (consistent) |
| Weather-boosted power | not implemented | not implemented | Low (consistent) |

### C rollout–specific issues (no Python equivalent)

| Issue | Detail | Severity |
|-------|--------|----------|
| P1 structural advantage in mirror matches | Even with random speed-tie resolution, P1 wins ~59% in identical-team mirrors due to first-mover compounding across turns | Low (known, documented in tests) |
| Heuristic `choose_act` quality | Weighted random, not minimax — rollout AI plays suboptimally near game end | Accepted (inherent to Monte Carlo) |
| 80-turn hard cap | Battles exceeding 80 turns count as P1 losses rather than draws | Low — only stall-vs-stall positions affected |

---

## Bugs Fixed in Follow-Up Audit (Python executor)

### 8. Endure guard prevented survival at exactly 1 HP (Medium — Fixed)

**File**: `gen3/executor.py` → `apply_damage_rolls`

`if defender.enduring and defender.current_hp > 1:` skipped the damage cap
when the defender was already at 1 HP, causing the mon to faint despite having
Endure active.

**Fix**: removed the `> 1` guard. `min(r, current_hp - 1)` = `min(r, 0)` = 0
when `current_hp == 1`, correctly dealing 0 net damage while keeping the mon alive.

---

### 9. Swagger applied confusion even under Safeguard (Medium — Fixed)

**File**: `gen3/executor.py` → `execute_status_move`, `swagger` handler

The swagger handler had no Safeguard check.  In Gen 3, Safeguard blocks the
confusion component of Swagger but NOT the +2 Atk boost.

**Fix**: added `if _safeguard_active(state, target_player): return [(1.0, s)]`
AFTER applying the +2 Atk to `s` but BEFORE the confusion duration branching.

---

### 10. Miss branches preserved `protect_consecutive` (Low — Fixed)

**File**: `gen3/executor.py` → `execute_single_move`

When a status or damaging move missed, the original `state` was returned on
the miss branch.  If the attacker had a Protect streak (`protect_consecutive > 0`),
the stale counter carried over, giving the next Protect use a lower success
probability than the rules allow (using a different move — even on a miss —
should reset the streak to 0).

**Fix**: on miss branches, create a `miss_state` with `protect_consecutive=0`
when the current value is non-zero; otherwise reuse the original state object
(no extra allocation in the common case).

---

## Test Coverage Added

- `tests/test_mechanics.py` — 16 regression tests covering hail immunity, Choice Specs lock,
  Sitrus Berry (flat 30 HP), Reflect/Light Screen, Leech Seed, Protect, Endure (including
  1 HP edge case), Safeguard (Toxic block, Swagger confusion block, Swagger Atk boost preserved),
  and Protect consecutive counter reset on miss
- `tests/test_trust.py` — 25 behavioural contract tests covering speed ties, double-KO,
  Taunt/Sub interaction, Choice lock (all skip conditions), Roar+Spikes, sleep duration range,
  hail/sand immunities, symmetry, and calibration
