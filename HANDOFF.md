# Gen 3 Battle Tower Engine — Development Handoff

## Repo
https://github.com/Federolla12/Battle_tower_claude

## What This Is

A Stockfish-style Pokemon battle analysis engine for Gen 3 3v3 singles (Battle Tower rules). Given a battle state, it computes the optimal move and win probability for every option, assuming the opponent plays their best counter (maximin strategy).

It includes a web UI (Flask + vanilla JS) where the user controls both sides — like a chess analysis board — with engine evaluation running in the background.

## How to Run

```bash
git clone https://github.com/Federolla12/Battle_tower_claude.git
cd Battle_tower_claude
gcc -O3 -shared -fopenmp -o gen3/rollout.dll gen3/rollout.c   # Windows
# or: gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm   # Linux
pip install flask
python server.py   # opens http://localhost:5000
# or: python main.py   # CLI analysis only
```

### Current status notes

- Speed ties are now modeled as 50/50 order branches in exact search and randomized in stochastic rollout flow.
- `/api/resolve` now samples outcomes by probability (legacy endpoint kept for compatibility).
- Background analysis has timeout protection to avoid wedging the UI if deep stages run too long.

## Architecture

### Module map (actual, not planned)

```
Battle_tower_claude/
├── main.py                 # CLI entry point (hardcoded teams, runs analysis, prints results)
├── server.py               # Flask web server (interactive UI, background analysis thread)
├── requirements.txt        # flask
├── static/
│   └── index.html          # Single-page web UI (vanilla JS, no framework)
└── gen3/
    ├── __init__.py
    ├── types.py             # 18×18 type chart, Gen 3 physical/special split by type
    ├── natures.py           # 25 natures with stat multipliers
    ├── stats.py             # Gen 3 stat formula (lv50), base stats for 6 species
    ├── damage.py            # Exact Gen 3 damage formula, all 16 rolls, verified vs Smogon calc
    ├── moves.py             # 24 move definitions (base power, accuracy, effects, flags)
    ├── state.py             # Frozen dataclasses: Pokemon, FieldSide, BattleState + builder
    ├── executor.py          # Move execution with probability branching, secondary effects, EOT
    ├── turn.py              # Simultaneous move resolution, speed ordering, flinch, switches
    ├── fast_rollout.py      # Python fast stochastic simulator (bypasses probability branching)
    ├── rollout.c            # C extension: full battle simulator (~175K games/sec)
    ├── c_rollout.py         # Python ctypes wrapper for rollout.c
    └── search.py            # Expectiminimax with maximin, matrix-game pruning, MC rollouts
```

### How the engine works

The search is **expectiminimax over simultaneous moves**. Pokemon is not alternating-turn like chess — both players choose actions at the same time, then speed determines execution order.

**Turn node structure:**
1. Enumerate all (P1 action × P2 action) joint pairs. With 4 moves + 2 switches per side, this is up to 6×6 = 36 pairs.
2. For each pair, call `resolve_turn()` which returns a probability distribution `[(prob, new_state), ...]` accounting for accuracy, crits, damage rolls (KO-threshold branching only), secondary effects, paralysis skip, etc.
3. For each resulting state, recurse to get the expected win probability.
4. Build the payoff matrix M[i][j] = E[P1 win probability | P1 plays i, P2 plays j].
5. Apply **maximin**: P1's value = max_i(min_j(M[i][j])). This gives the guaranteed win probability assuming the opponent plays their best counter.

**At leaf nodes** (depth >= max_depth), win probability is estimated via Monte Carlo rollouts using the C extension (~175,000 complete games per second).

**Matrix-game pruning**: While building the payoff matrix, if P2 already has a response that makes P1's current move worse than P1's best found so far, skip remaining P2 responses for that P1 move. This is the simultaneous-move analog of alpha-beta pruning.

**Transposition table**: Keyed on the full BattleState (which is frozen/hashable). Value is depth-independent because we always search to terminal or use MC rollouts.

### Data flow for a single analysis

```
SearchEngine.analyze(state)
  → for each (a1, a2) in actions_p1 × actions_p2:
      → resolve_turn(state, a1, a2)
          → determine_order(state, a1, a2)  # speed, priority
          → execute_player_action(state, first_player, first_action)
              → check_can_move()  # para/sleep/freeze
              → execute_single_move()
                  → calc_damage() from damage.py  # all 16 rolls
                  → KO-threshold branching
                  → apply_secondary_effect()  # burn/para/flinch/etc
          → flinch branching
          → execute_player_action(state, second_player, second_action)
          → apply_end_of_turn()  # leftovers, burn damage, toxic, etc
      → returns [(prob, new_state), ...]
      → ev = Σ prob × search(new_state, depth+1)
  → maximin over the matrix
  → returns position value + best move + full analysis
```

### The C extension (rollout.c)

A complete reimplementation of the battle simulator in C for Monte Carlo rollouts. Uses mutable structs (no allocation per turn), xorshift32 RNG, and a smart-random action selection policy.

**Why C?** The Python simulator with frozen dataclasses does ~360 games/sec. The C version does ~175,000 games/sec (480× faster). This is critical because each leaf node evaluation requires 200+ rollouts.

**C struct layout** (must match `c_rollout.py` exactly):
```c
typedef struct {
    int t1, t2, ab, item, item_c;
    int mv[4], mlock;
    int mhp, hp, atk, def, spa, spd, spe;
    int st, st_t;
    int as, ds, sas, sds, ss;      // stat stages (atk, def, spa, spd, spe)
    int sub, taunt, flinch, ldmg, lphys;
} Mon;

typedef struct {
    Mon team[2][3];
    int act[2];
    int weath, weath_t, refl[2], ls[2], spk[2], turn;
} State;
```

**Enum mappings** between Python strings and C ints are defined in `c_rollout.py` (TYPE_MAP, STATUS_MAP, ITEM_MAP, ABILITY_MAP, MOVE_MAP). When adding new Pokemon/moves, both the C enums and the Python mapping dicts must be updated.

**Compiling:**
- Windows: `gcc -O3 -shared -fopenmp -o gen3/rollout.dll gen3/rollout.c`
- Linux: `gcc -O3 -shared -fPIC -fopenmp -o gen3/rollout.so gen3/rollout.c -lm`
- The `EXPORT` macro handles `__declspec(dllexport)` on Windows.

### The web UI (server.py + static/index.html)

**server.py** is a Flask app with these endpoints:
- `GET /api/state` — returns serialized game state, legal actions for both players, analysis results, battle log
- `POST /api/resolve` — takes `{p1: ["move","Hidden Power"], p2: ["move","Rock Slide"]}`, resolves the turn by sampling outcome probability, starts background analysis
- `POST /api/switch` — forced switch after KO: `{player: "p1", idx: 2}`
- `POST /api/undo` — pops state_history stack
- `POST /api/reset` — reinitializes game

**Background analysis thread** runs iterative deepening: depth 0 (instant) → depth 1 (~0.1s) → depth 2 (~4s) → depth 2 with 500 rollouts (~9s). The frontend polls `/api/state` every 500ms and updates the eval bar as each stage completes.

**index.html** is a single-file vanilla JS app. Both sides are player-controlled (chess analysis style). The user selects a P1 move and a P2 move, then clicks "Resolve Turn". Win percentages from the engine are shown on P1's move buttons.

## What's Implemented

### Gen 3 mechanics
- Exact damage formula (verified roll-by-roll against Smogon's ADV damage calculator)
- Level 50 stat calculation (verified against Showdown)
- Modifier order: base → weather → crit → STAB → type effectiveness → random roll (verified)
- Gen 3 physical/special split by TYPE (not by move)
- All 18 type interactions
- 25 natures with correct stat modifiers
- Stat stages -6 to +6 with correct multipliers

### Moves (24 total, covering both test teams)
| Move | Type | BP | Effect |
|------|------|----|--------|
| Hidden Power (Ground) | Ground | 70 | — |
| Taunt | Dark | 0 | Blocks status moves 2 turns |
| Counter | Fighting | 0 | Reflects 2× physical damage, -5 priority |
| Toxic | Poison | 0 | Badly poisons (85% acc) |
| Giga Drain | Grass | 60 | Drains 50% of damage dealt |
| Psychic | Psychic | 90 | 10% SpD -1 |
| Ice Punch | Ice | 75 | 10% freeze |
| Fire Punch | Fire | 75 | 10% burn |
| Rest | Psychic | 0 | Full heal, sleep 2 turns |
| Sleep Talk | Normal | 0 | Use random move while asleep |
| Curse | ??? | 0 | +1 Atk, +1 Def, -1 Spe (non-Ghost) |
| Body Slam | Normal | 85 | 30% paralyze |
| Rock Slide | Rock | 75 | 30% flinch, 90% acc |
| Substitute | Normal | 0 | Create sub (25% max HP) |
| Focus Punch | Fighting | 150 | -3 priority, fails if hit |
| Thunder Wave | Electric | 0 | Paralyze (blocked by Ground, Sub) |
| Will-O-Wisp | Fire | 0 | Burn (75% acc, blocked by Fire, Sub) |
| Fire Blast | Fire | 120 | 10% burn, 85% acc |
| Sludge Bomb | Poison | 90 | 30% poison |
| Pain Split | Normal | 0 | Average both Pokemon's HP |
| Meteor Mash | Steel | 100 | 20% Atk +1 self, 85% acc |
| Earthquake | Ground | 100 | — |
| Brick Break | Fighting | 75 | Breaks Reflect/Light Screen |
| Explosion | Normal | 250 | User faints, halves target's Def |

### Items (4)
- **Leftovers**: 1/16 max HP recovery end of turn
- **Choice Band**: 1.5× Attack, locked into one move until switch
- **Lum Berry**: Auto-cures any status (consumed)
- **Chesto Berry**: Auto-cures sleep (consumed)

### Abilities (5)
- **Keen Eye**: No accuracy reduction (passive, rarely relevant)
- **Levitate**: Ground immunity
- **Thick Fat**: Halves Fire/Ice damage (applied as power halving)
- **Sturdy**: Prevents OHKO moves (not relevant with these moves)
- **Clear Body**: Blocks opponent stat drops

### Status conditions
- **Burn**: Halves Attack, 1/8 max HP damage end of turn
- **Paralyze**: Speed ÷4, 25% chance to skip turn
- **Poison**: 1/8 max HP damage end of turn
- **Toxic**: 1/16 × N max HP damage end of turn (N increases each turn)
- **Freeze**: 20% chance to thaw each turn, otherwise skip
- **Sleep**: Skip turns, counter decrements (Gen 3: 1-3 turns, Rest = 2 turns)

### Battle mechanics
- Simultaneous move selection (both players choose before resolution)
- Speed-based move order (priority brackets, then speed stat, including paralysis)
- Flinch (only works if attacker is faster)
- Focus Punch interruption (fails if hit before executing)
- Taunt blocking status moves (including mid-turn — if Taunt lands first, the slower mon's status move fails)
- Choice Band move lock (resets on switch)
- Substitute (blocks status moves except Taunt, absorbs damage)
- Spikes damage on switch-in (1/8, 1/6, 1/4 for 1/2/3 layers; Flying and Levitate immune)
- Volatile clearing on switch (stat stages, substitute, taunt, confusion reset)
- End-of-turn order: weather damage → Leftovers → burn → poison → toxic → screen/taunt countdown → weather countdown

### Test teams (hardcoded in main.py and server.py)

**Team 1 (P1):**
```
Skarmory @ Leftovers | Keen Eye | Impish | 252 HP / 232 Def / 24 Spe
- Hidden Power [Ground] / Taunt / Counter / Toxic

Gengar @ Lum Berry | Levitate | Timid | 252 SpA / 4 SpD / 252 Spe (0 Atk IV)
- Giga Drain / Psychic / Ice Punch / Fire Punch

Snorlax @ Chesto Berry | Thick Fat | Careful | 252 HP / 4 Atk / 252 SpD
- Rest / Sleep Talk / Curse / Body Slam
```

**Team 2 (P2):**
```
Aggron @ Leftovers | Sturdy | Impish | 248 HP / 8 Atk / 252 Def
- Rock Slide / Substitute / Focus Punch / Thunder Wave

Weezing @ Lum Berry | Levitate | Sassy | 252 HP / 4 Atk / 252 SpD
- Will-O-Wisp / Fire Blast / Sludge Bomb / Pain Split

Metagross @ Choice Band | Clear Body | Jolly | 252 Atk / 4 SpD / 252 Spe
- Meteor Mash / Earthquake / Brick Break / Explosion
```

**Stats at level 50 (verified against Smogon calc):**
```
Pokemon      HP   Atk   Def   SpA   SpD   Spe
Skarmory    172   100   207    54    90    93
Gengar      135    63    80   182    96   178
Snorlax     267   131    85    76   178    50
Aggron      176   131   255    72    80    70
Weezing     172   111   140   105   134    72
Metagross   155   187   150   103   111   134
```

## Known Issues & Bugs

1. **Damage branching remains an approximation in some lines.** The engine tracks KO-sensitive and representative damage branches for tractability, so some HP-threshold edge cases are simplified.

2. **The web UI can get stuck** if the analysis thread crashes or takes too long. The polling continues but no new analysis appears. Need error handling and timeouts.

3. **`fast_rollout.py` is unused** since the C extension replaced it. Can be removed, but keeping it as a fallback if the .so/.dll isn't compiled.

4. **No PP tracking.** Moves have unlimited uses. In very long Battle Tower games, PP stalling could be relevant.

5. **Sleep mechanics may be slightly off.** Gen 3 sleep counter behavior (when exactly you wake up, whether you can act on the wake-up turn) has edge cases that need verification.

6. **Counter tracks "last damage taken" but resets each turn.** If a move like Substitute absorbs damage, Counter correctly sees 0 physical damage. However, multi-hit scenarios within a turn aren't handled.

7. **No broad regression test suite yet.** Several high-risk mechanics are implemented but need dedicated automated tests to prevent future regressions.

## What's NOT Implemented (Planned for v2)

### Mechanics
- **Trapping** (Shadow Tag, Arena Trap, Magnet Pull) — prevents switching
- **Baton Pass** — switch while passing stat changes
- **Sleep Clause** — standard competitive rule: only one mon per team can be put to sleep
- **Two-turn moves** (Fly, Dig, Dive) — semi-invulnerable turn + attack turn
- **Confusion** — 50% self-hit, implemented in state but not in executor
- **Protect/Detect** — blocks all attacks, fails at 1/N if repeated
- **Encore** — locks opponent into their last move
- **Rapid Spin** — removes hazards
- **Spikes** (the move) — laying entry hazards. The *damage on switch-in* is implemented, but no Pokemon on the test teams has the move Spikes.
- **Whirlwind/Roar** — force random switch
- **Pursuit** — doubles damage on switching target
- **Contact ability triggers** (Static 30% para, Flame Body 30% burn, Rough Skin 1/16 recoil)
- **Intimidate** — -1 Atk on switch-in
- **Weather-setting abilities** (Sand Stream, Drizzle)
- **More items** (Sitrus Berry partial, Salac/Petaya/Liechi, Focus Band, Brightpowder, Shell Bell, type-boosting items)

### Engine
- **Deeper search** — depth 3 takes ~60s currently. The C rollout is fast enough but the Python search layer is the bottleneck (resolve_turn returns probability distributions with frozen dataclasses). Porting the search loop to C or Cython would enable depth 4-5.
- **Mixed strategy Nash equilibrium** — was prototyped in the 1v1 engine using scipy.optimize.linprog. Not integrated into the 3v3 engine. Would tell you the optimal randomization over moves (e.g., "use HP Ground 60% of the time, Taunt 40%").
- **Move ordering for pruning** — currently orders attacking moves first. Could use killer move heuristic or history heuristic from the transposition table.
- **Iterative deepening within the search** — currently each depth level is a separate SearchEngine instance. Could share the TT across depths for better pruning.

### Data
- **Full Pokedex** — only 6 species are defined in stats.py. Expanding to all 386 Gen 3 Pokemon requires importing data from Showdown's pokedex.
- **More moves** — only 24 moves are defined. Need ~100-150 for competitive coverage.
- **Team input parsing** — currently teams are hardcoded. Should parse Showdown export format directly.
- **Arbitrary team support** — the C extension hardcodes the 24 move IDs as enums. Adding new moves requires updating both the C code and the Python mapping.

### UI
- **The web UI needs work.** It was built quickly and has rough edges. The user wants something more like Pokemon Showdown's interface.
- **No damage calc display** — would be useful to show damage ranges when hovering over moves
- **No type effectiveness indicators** on move buttons
- **No animation** for HP changes, status application, etc.
- **Team editor** — currently both teams are hardcoded. Should allow pasting Showdown exports.
- **Mid-game state editor** — manually set HP, status, stat stages for analysis

## Key Design Decisions & Rationale

1. **Maximin over simultaneous moves, not alternating minimax.** Pokemon is simultaneous — both players choose before knowing the opponent's choice. This means the game tree has a 2D branching factor (N×M) per turn, not alternating plies. The maximin strategy (best guaranteed win rate assuming opponent plays optimally) is the correct solution concept for 2-player zero-sum simultaneous games.

2. **MC rollouts at leaves instead of static evaluation.** A static eval function (HP ratio, type matchups, etc.) can't capture complex interactions like "burn now, win later" or "sacrifice one mon to sweep with another." Rollouts automatically discover these win conditions by playing thousands of random games. The tradeoff is speed, which the C extension solves.

3. **KO-threshold branching for damage rolls.** Instead of branching on all 16 damage rolls (which would explode the tree), we only branch when some rolls KO and others don't. If all rolls survive, we use the average damage. If all rolls KO, it's a guaranteed KO. This dramatically reduces branching while preserving KO-accuracy in the search.

4. **Frozen dataclasses for state.** All state objects are immutable and hashable, enabling the transposition table. The tradeoff is performance (Python's `dataclasses.replace()` is slow for 30+ fields), which is why the C extension exists for rollouts.

5. **Level 50 (Battle Tower rules).** All stat calculations are at level 50 with the Gen 3 formula. The damage formula was verified roll-by-roll against Smogon's ADV damage calculator (screenshots compared).

6. **Gen 3 damage formula modifier order.** Verified empirically: base → weather → crit → STAB → type effectiveness → random roll. The random roll is LAST. This was discovered by comparing computed rolls against Smogon calc outputs — the initial implementation had STAB/type after the random roll, which produced different integer rounding.

## Performance Benchmarks

| Operation | Speed |
|-----------|-------|
| C rollout (full 3v3 game) | ~175,000 games/sec |
| Python rollout (full 3v3 game) | ~360 games/sec |
| resolve_turn (one turn, probability distribution) | ~200/sec |
| Search depth 0 (pure rollouts, 300 sims) | ~0.1s |
| Search depth 1 (200 rollouts/leaf) | ~0.1s |
| Search depth 2 (200 rollouts/leaf) | ~4s |
| Search depth 2 (500 rollouts/leaf) | ~9s |
| Search depth 3 (100 rollouts/leaf) | ~60s |

## How to Add a New Pokemon

1. **`gen3/stats.py`**: Add base stats to `BASE_STATS` dict and types to `SPECIES_TYPES`
2. **`gen3/moves.py`**: Add any new moves with `_m()` helper (defines type, power, accuracy, effect, etc.)
3. **`gen3/executor.py`**: If the move has a new effect type, add handling in `apply_secondary_effect()` or `execute_status_move()`
4. **`gen3/rollout.c`**: Add new move enum entry, update `init_mv()`, add effect handling in `exec_dmg()`/`exec_st()`
5. **`gen3/c_rollout.py`**: Add entries to `MOVE_MAP`, `ABILITY_MAP`, `ITEM_MAP` as needed
6. **Recompile**: `gcc -O3 -shared -o gen3/rollout.dll gen3/rollout.c`

## How to Add a New Ability/Item

Same pattern: define in Python (`executor.py` for game logic, `moves.py`/`state.py` for data), then mirror in C (`rollout.c` enums and logic), update the Python↔C mapping (`c_rollout.py`), and recompile.
