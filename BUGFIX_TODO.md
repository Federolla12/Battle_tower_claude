# Bugfix TODO

This file tracks the highest-priority bugs, mechanics mismatches, and follow-up improvements identified during the code review.

## Priority 0 — correctness bugs affecting engine output

- [x] Fix **speed tie handling** in `gen3/turn.py`
  - Current behavior always gives equal-speed ties to P1.
  - This biases evaluations and breaks symmetry.
  - Required fix:
    - exact search: branch tie order with 50/50 probability
    - MC rollout: sample tie order randomly

- [x] Fix **double-KO forced switch evaluation** in `gen3/search.py`
  - Current behavior averages all P1/P2 switch combinations when both active mons faint and both players still have bench Pokémon.
  - This should be treated as a simultaneous adversarial choice, not a random average.
  - Required fix:
    - build a switch matrix for `(switch_p1, switch_p2)`
    - solve using the same maximin/minimax logic used for move selection

- [x] Fix **Taunt through Substitute** in `gen3/executor.py`
  - Current code blocks `Taunt` if the target has a Substitute.
  - Inline comment already notes this is wrong.
  - Update the mechanic to match intended Gen 3 behavior.

- [x] Fix **Choice Band lock application** in `gen3/turn.py`
  - Current code applies choice lock from the selected action after the turn, even if the move never actually executed.
  - Bad cases include flinch, full paralysis, sleep skip, freeze skip, faint-before-moving, Focus Punch fail.
  - Required fix:
    - only lock when the move is actually used successfully

## Priority 1 — mechanics mismatches / search-model issues

- [x] Fix **forced-switch entry effects** for `Roar` / `Whirlwind` in `gen3/executor.py`
  - Current implementation directly changes active index and explicitly skips entry effects.
  - This is inconsistent with the rest of the engine if switch-in hazards/effects are modeled.
  - Apply switch-in processing consistently (Spikes, weather abilities, Intimidate, etc. as applicable to your ruleset).

- [x] Revisit **Sleep Clause** in `gen3/executor.py`
  - Current engine prevents sleep if another Pokémon on the target team is already asleep.
  - README describes this as a **Battle Tower rules** engine, so this may be the wrong ruleset.
  - Decision: Battle Tower rules — Sleep Clause removed.

- [x] Fix **search depth semantics** in `gen3/search.py`
  - `analyze()` currently resolves a root joint action and then calls `search(s, 0)` on the resulting state.
  - This makes depth accounting inconsistent between root and recursive nodes.
  - Fixed: `analyze()` now calls `search(s, 1)` so depth is counted consistently.

- [ ] Revisit **damage branching approximation** in `gen3/executor.py`
  - Current model branches mainly on KO vs survive, then averages surviving rolls.
  - This affects:
    - berry thresholds
    - recoil/drain amounts
    - Counter / Mirror Coat
    - end-of-turn survival
    - exact HP-sensitive lines
  - Either:
    - increase fidelity for more roll breakpoints, or
    - document clearly that this is an approximation

## Priority 2 — documentation / trustworthiness fixes

- [ ] Update README and comments to distinguish **exact** vs **approximate** mechanics
  - Current wording can overstate exactness.
  - Recommended wording:
    - exact Gen 3 damage arithmetic
    - approximate full-state branching in some cases
    - MC rollouts for leaf evaluation

- [ ] Mark move support by status in `gen3/moves.py`
  - Add a way to distinguish:
    - exact support
    - simplified/approximate support
    - stub/no-op support
  - This will make UI and team validation more transparent.

- [ ] Surface warnings in the UI when teams contain simplified or stubbed moves
  - Prevent users from assuming a move is fully implemented just because it exists in the move DB.

## Priority 3 — code quality / maintainability

- [ ] Audit comments that disagree with code
  - Example: `Taunt` + Substitute comment in `gen3/executor.py`
  - Make comments reflect actual implemented behavior.

- [ ] Reduce duplicated rules checks split across action generation and execution
  - Examples: Taunt legality and same-turn execution checks.
  - Keep duplicated logic only where absolutely necessary for turn-order correctness.

- [ ] Consider caching / memoization improvements
  - cache resolved joint-action outcomes
  - memoize legal actions per state where useful
  - separate evaluation caching strategy if rollout counts vary

## Follow-up testing checklist

- [ ] Add regression tests for equal-speed tie positions
- [ ] Add regression tests for double-KO into forced switches
- [ ] Add regression tests for Taunt vs Substitute
- [ ] Add regression tests for Choice Band + flinch / paralysis / faint-before-moving
- [ ] Add regression tests for Roar / Whirlwind into Spikes
- [ ] Add regression tests for sleep rules based on intended format
- [ ] Add regression tests for HP-threshold interactions affected by averaged damage rolls

## Nice-to-have improvements

- [ ] Make ruleset configurable (Battle Tower vs competitive clauses)
- [ ] Expose approximation level in UI / CLI output
- [ ] Add an "engine limitations" section to README
- [ ] Add per-move mechanic coverage notes for Battle Frontier set support

## Summary

Most important fixes to do first:

1. speed ties
2. simultaneous forced switches after double KO
3. Taunt through Substitute
4. Choice Band lock timing
5. forced-switch entry effects
6. clarity around exact vs approximate mechanics
