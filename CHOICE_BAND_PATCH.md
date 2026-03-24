# Choice Band patch plan

This note captures the remaining bug in the current Choice Band implementation and the smallest safe fix.

## Problem

The recent refactor moved Choice Band locking closer to move execution, which is an improvement.
However, the lock is still applied too broadly.

### Current behavior

In `gen3/turn.py`:
- `execute_player_action()` applies `_apply_choice_lock()` to every state returned by `execute_single_move()`.
- `_sim_player_action()` also applies `_apply_choice_lock()` to the sampled result from `execute_single_move()`.

This still locks on cases where the move did **not** truly count as a successful move use for Choice Band purposes, including at least:
- accuracy miss
- immunity / no-effect hit
- other no-op returned states from `execute_single_move()`

## Minimal fix

Change the move-execution pipeline so it explicitly reports whether the move should trigger Choice Band lock.

## Recommended design

### 1. Introduce a richer return type for move execution

Instead of only returning:

```python
List[Tuple[float, BattleState]]
```

use:

```python
List[Tuple[float, BattleState, bool]]
```

Where the final boolean is:
- `locks_choice = True` if the move actually counts as being used for Choice Band lock
- `locks_choice = False` otherwise

This should be used only inside the turn-resolution layer if you want to avoid changing every other helper.

### 2. Alternative lower-impact version

If you want a smaller patch with fewer type changes, add a helper in `gen3/executor.py`:

```python
def execute_single_move_with_meta(state, player, move):
    # returns List[Tuple[float, BattleState, bool]]
```

Keep the old `execute_single_move()` as-is for legacy callers if needed.

## Exact locking rule to use

For this engine, the simplest robust rule is:

- `True` when a move was actually executed and was not prevented by:
  - flinch
  - full paralysis
  - sleep skip
  - freeze skip
  - Focus Punch interruption
  - faint-before-moving
- `False` on pure miss branches

For immunities, decide on one rule and use it consistently.

### Practical recommendation

Treat **immunity as locking** if the move was selected and actually used into the target, but it had no effect.
Treat **accuracy miss as not locking**.

That gives behavior that is much closer to expected cartridge semantics than the current implementation.

## Smallest concrete code change

### In `gen3/executor.py`

Add a new function:

```python
def execute_single_move_with_meta(state: BattleState, player: str,
                                  move: MoveDef, allow_sleep_check: bool = True):
    """
    Same as execute_single_move, but returns:
        List[(prob, state, locks_choice)]
    """
```

Then implement these rules:

### Status moves
- successful status move attempt -> `locks_choice=True`
- miss from accuracy branch -> `locks_choice=False`

### Counter / Mirror Coat / similar special handlers
- if the move fails because preconditions are not met -> `locks_choice=True` or `False` depending on intended semantics
- recommended for now: `True` if the move was actually attempted, `False` only on branches where the move never happened

### Damaging moves
- miss branch:
  - return `(1 - hit_prob, state, False)`
- hit / immunity / damage branches:
  - return `(prob, resulting_state, True)`

This avoids the current bug while keeping the rest of the turn logic simple.

## Then update `gen3/turn.py`

### `execute_player_action()`
Replace:

```python
move_results = execute_single_move(s_conf, player, move)
for p_move, s_move in move_results:
    s_move = _apply_choice_lock(s_move, player, action)
    results.append((p_status * p_conf * p_move, s_move))
```

With:

```python
move_results = execute_single_move_with_meta(s_conf, player, move)
for p_move, s_move, locks_choice in move_results:
    if locks_choice:
        s_move = _apply_choice_lock(s_move, player, action)
    results.append((p_status * p_conf * p_move, s_move))
```

### `_sim_player_action()`
Replace the sampled return path with logic that only locks when `locks_choice` is true.

## Why this patch is preferable

- minimal conceptual change
- localizes the fix to the move-execution boundary
- avoids trying to infer move success from final state deltas
- handles miss branches correctly
- preserves your recent improvements to flinch / para / sleep / faint-before-moving behavior

## Regression tests to add

### Must-have
- [ ] Choice Band + damaging move + accuracy miss -> should **not** lock
- [ ] Choice Band + move prevented by flinch -> should **not** lock
- [ ] Choice Band + full paralysis -> should **not** lock
- [ ] Choice Band + asleep and cannot act -> should **not** lock
- [ ] Choice Band + frozen and no thaw -> should **not** lock
- [ ] Choice Band + faint before move -> should **not** lock
- [ ] Choice Band + move connects normally -> should lock

### Decision-point tests
- [ ] Choice Band + target immune -> confirm intended lock behavior
- [ ] Choice Band + Counter fails due to no prior physical hit -> confirm intended lock behavior
- [ ] Choice Band + Focus Punch interrupted -> should **not** lock

## Summary

The current code fixed the timing of Choice Band lock much better than before, but it still locks on miss branches because `execute_single_move()` does not report whether a move actually counted as used.

The cleanest minimal fix is to make move execution return a small metadata flag and apply `_apply_choice_lock()` only on branches where that flag is true.
