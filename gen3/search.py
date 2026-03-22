"""
Gen 3 Search Engine
====================
Expectiminimax with simultaneous moves and MC rollouts at leaf nodes.

The search builds a payoff matrix of all (P1 action × P2 action) pairs,
computes expected win probability for each cell via recursive search,
then applies maximin to find the optimal safe strategy.
"""

import time
import random
from typing import Dict, List, Tuple, Optional
from .state import BattleState
from .executor import get_legal_actions
from .turn import (
    resolve_turn, simulate_turn_fast, choose_rollout_action, Action
)


class SearchEngine:
    """
    Expectiminimax search for 3v3 Pokemon battles.

    For each position:
    1. Enumerate all (action_p1 × action_p2) joint pairs
    2. For each pair, compute E[win_prob] via recursive search
    3. Build the payoff matrix M[i][j]
    4. Maximin: value = max_i(min_j(M[i][j]))

    At leaf nodes (depth >= max_depth), estimate win probability
    via Monte Carlo rollouts using the fast stochastic simulator.
    """

    def __init__(self, max_depth: int = 4, mc_rollouts: int = 80):
        self.max_depth = max_depth
        self.mc_rollouts = mc_rollouts
        self.transposition_table: Dict[BattleState, float] = {}
        self.nodes_searched = 0
        self.tt_hits = 0

    def search(self, state: BattleState, depth: int = 0) -> float:
        """
        Returns the win probability for P1 from this state,
        assuming both players play optimally (maximin).
        """
        self.nodes_searched += 1

        # Terminal check
        if state.is_terminal():
            return 1.0 if state.winner() == "p1" else 0.0

        # Depth limit → MC rollouts
        if depth >= self.max_depth:
            return self.mc_rollout(state, self.mc_rollouts)

        # Transposition table
        if state in self.transposition_table:
            self.tt_hits += 1
            return self.transposition_table[state]

        # Forced switch: only one player acts
        p1_alive = state.active("p1").alive()
        p2_alive = state.active("p2").alive()
        if not p1_alive or not p2_alive:
            return self._handle_forced_switch(state, depth,
                                              p1_alive, p2_alive)

        # Get legal actions
        actions_p1 = get_legal_actions(state, "p1")
        actions_p2 = get_legal_actions(state, "p2")

        # Maximin with matrix-game pruning
        best_guaranteed = -1.0

        for a1 in actions_p1:
            worst_for_a1 = 2.0

            for a2 in actions_p2:
                outcomes = resolve_turn(state, a1, a2)
                ev = sum(prob * self.search(s, depth + 1)
                         for prob, s in outcomes)

                worst_for_a1 = min(worst_for_a1, ev)

                # Pruning: if P2 has a response making a1 worse than
                # our current best, skip remaining P2 responses
                if worst_for_a1 <= best_guaranteed:
                    break

            best_guaranteed = max(best_guaranteed, worst_for_a1)

        self.transposition_table[state] = best_guaranteed
        return best_guaranteed

    def _handle_forced_switch(self, state: BattleState, depth: int,
                              p1_alive: bool, p2_alive: bool) -> float:
        """Handle forced switch when one mon has fainted."""
        if not p1_alive and not p2_alive:
            # Both fainted simultaneously (Explosion, recoil, etc.)
            # Check remaining teams
            p1_has_bench = any(m.alive() for i, m in enumerate(state.team_p1)
                               if i != state.active_p1)
            p2_has_bench = any(m.alive() for i, m in enumerate(state.team_p2)
                               if i != state.active_p2)
            if not p1_has_bench and not p2_has_bench:
                return 0.5  # True tie
            if not p1_has_bench:
                return 0.0
            if not p2_has_bench:
                return 1.0
            # Both need to switch — treat as simultaneous
            # (simplification: just take average of all switch combos)
            bench_p1 = state.alive_bench("p1")
            bench_p2 = state.alive_bench("p2")
            total = 0.0
            count = 0
            for i in bench_p1:
                for j in bench_p2:
                    from .turn import execute_switch
                    s = execute_switch(state, "p1", i)
                    s = execute_switch(s, "p2", j)
                    total += self.search(s, depth + 1)
                    count += 1
            return total / count if count > 0 else 0.5

        # One player needs to switch
        if not p1_alive:
            switching_player = "p1"
        else:
            switching_player = "p2"

        bench = state.alive_bench(switching_player)
        if not bench:
            # No bench left — this player loses
            return 1.0 if switching_player == "p2" else 0.0

        if switching_player == "p1":
            # P1 switches — P1 wants to maximize
            best = -1.0
            for idx in bench:
                from .turn import execute_switch
                s = execute_switch(state, "p1", idx)
                val = self.search(s, depth + 1)
                best = max(best, val)
            return best
        else:
            # P2 switches — P2 wants to minimize
            worst = 2.0
            for idx in bench:
                from .turn import execute_switch
                s = execute_switch(state, "p2", idx)
                val = self.search(s, depth + 1)
                worst = min(worst, val)
            return worst

    def mc_rollout(self, state: BattleState, n_sims: int) -> float:
        """Run MC rollouts using the C extension for speed."""
        from .c_rollout import c_rollout
        return c_rollout(state, n_sims)

    def analyze(self, state: BattleState) -> dict:
        """
        Full position analysis. Returns the payoff matrix and
        optimal strategy for both players.
        """
        self.transposition_table.clear()
        self.nodes_searched = 0
        self.tt_hits = 0

        actions_p1 = get_legal_actions(state, "p1")
        actions_p2 = get_legal_actions(state, "p2")

        # Build the full payoff matrix
        matrix = {}
        for a1 in actions_p1:
            for a2 in actions_p2:
                outcomes = resolve_turn(state, a1, a2)
                ev = sum(prob * self.search(s, 1)
                         for prob, s in outcomes)
                matrix[(a1, a2)] = ev

        # P1 analysis
        p1_analysis = {}
        for a1 in actions_p1:
            worst = min(matrix[(a1, a2)] for a2 in actions_p2)
            best_response = min(actions_p2,
                                key=lambda a2: matrix[(a1, a2)])
            p1_analysis[a1] = {
                "guaranteed_win_pct": worst,
                "best_opponent_response": best_response,
                "vs_each": {a2: matrix[(a1, a2)] for a2 in actions_p2},
            }

        # P2 analysis
        p2_analysis = {}
        for a2 in actions_p2:
            worst_for_p2 = max(matrix[(a1, a2)] for a1 in actions_p1)
            p2_analysis[a2] = {
                "p1_win_pct_worst_case": worst_for_p2,
            }

        best_a1 = max(actions_p1,
                      key=lambda a: p1_analysis[a]["guaranteed_win_pct"])
        best_a2 = min(actions_p2,
                      key=lambda a: p2_analysis[a]["p1_win_pct_worst_case"])

        return {
            "matrix": matrix,
            "p1_analysis": p1_analysis,
            "p2_analysis": p2_analysis,
            "best_move_p1": best_a1,
            "best_move_p2": best_a2,
            "position_value": p1_analysis[best_a1]["guaranteed_win_pct"],
            "nodes_searched": self.nodes_searched,
            "tt_hits": self.tt_hits,
            "actions_p1": actions_p1,
            "actions_p2": actions_p2,
        }


# ============================================================
# Display
# ============================================================

def display_analysis(result: dict, state: BattleState):
    """Pretty-print the engine analysis."""
    p1 = state.active("p1")
    p2 = state.active("p2")

    print("=" * 76)
    print(f"  POSITION: Turn {state.turn_number}")
    print(f"  P1: ", end="")
    for i, m in enumerate(state.team_p1):
        marker = "►" if i == state.active_p1 else " "
        hp_str = f"{m.current_hp}/{m.max_hp}" if m.alive() else "FAINTED"
        status = f" [{m.status}]" if m.status else ""
        print(f"{marker}{m.species} {hp_str}{status}", end="  ")
    print()
    print(f"  P2: ", end="")
    for i, m in enumerate(state.team_p2):
        marker = "►" if i == state.active_p2 else " "
        hp_str = f"{m.current_hp}/{m.max_hp}" if m.alive() else "FAINTED"
        status = f" [{m.status}]" if m.status else ""
        print(f"{marker}{m.species} {hp_str}{status}", end="  ")
    print()
    if state.weather:
        print(f"  Weather: {state.weather} ({state.weather_turns} turns)")
    print(f"  Nodes: {result['nodes_searched']:,} | TT hits: {result['tt_hits']:,}")
    print("=" * 76)

    actions_p1 = result["actions_p1"]
    actions_p2 = result["actions_p2"]
    p1_analysis = result["p1_analysis"]

    def fmt_action(a):
        if a[0] == "switch":
            return f"→{state.get_team(a[0])[a[1]].species if isinstance(a[1], int) else a[1]}"
        return a[1]

    def fmt_action_full(a, player):
        if a[0] == "switch":
            team = state.get_team(player)
            return f"Switch→{team[a[1]].species}"
        return a[1]

    print(f"\n  P1 ({p1.species}) MOVE ANALYSIS:")
    print(f"  {'Action':<22} {'Win%':>7}  vs Best Counter")
    print(f"  {'-'*55}")

    sorted_actions = sorted(actions_p1,
                            key=lambda a: p1_analysis[a]["guaranteed_win_pct"],
                            reverse=True)
    for a1 in sorted_actions:
        info = p1_analysis[a1]
        name = fmt_action_full(a1, "p1")
        counter = fmt_action_full(info["best_opponent_response"], "p2")
        marker = " ★" if a1 == result["best_move_p1"] else ""
        print(f"  {name:<22} {info['guaranteed_win_pct']:>6.1%}  "
              f"({counter}){marker}")

    print(f"\n  POSITION VALUE: {result['position_value']:.1%} for P1")
    print("=" * 76)
