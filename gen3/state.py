"""
Gen 3 Battle State
==================
Immutable state representation for 3v3 singles.
All dataclasses are frozen for transposition table hashing.
"""

from dataclasses import dataclass, replace
from typing import Optional, Tuple


@dataclass(frozen=True)
class Pokemon:
    """A single Pokemon's full battle state."""
    # Identity
    species: str
    types: Tuple[str, Optional[str]]
    ability: str
    item: Optional[str]
    item_consumed: bool
    moves: Tuple[str, ...]         # move names
    move_locked: Optional[str]     # Choice Band lock

    # Base stats (unmodified)
    max_hp: int
    base_atk: int
    base_def: int
    base_spa: int
    base_spd: int
    base_spe: int

    # Current state
    current_hp: int
    status: Optional[str]          # "burn"|"paralyze"|"poison"|"toxic"|"freeze"|"sleep"
    status_turns: int              # sleep counter, toxic damage counter
    
    # Stat stages (-6 to +6)
    atk_stage: int
    def_stage: int
    spa_stage: int
    spd_stage: int
    spe_stage: int

    # Volatiles (reset on switch)
    substitute_hp: int
    taunt_turns: int
    confused: bool
    confused_turns: int
    flinched: bool                 # reset each turn
    last_move: Optional[str]
    last_damage_taken: int         # for Counter
    last_damage_physical: bool     # was last hit physical?
    protect_consecutive: int       # consecutive Protect uses

    def alive(self) -> bool:
        return self.current_hp > 0

    def effective_speed(self) -> int:
        """Current speed including paralysis and stat stages."""
        from .damage import apply_stage
        spd = apply_stage(self.base_spe, self.spe_stage)
        if self.status == "paralyze":
            spd = spd // 4
        return max(1, spd)

    def effective_atk(self) -> int:
        from .damage import apply_stage
        return apply_stage(self.base_atk, self.atk_stage)

    def effective_def(self) -> int:
        from .damage import apply_stage
        return apply_stage(self.base_def, self.def_stage)

    def effective_spa(self) -> int:
        from .damage import apply_stage
        return apply_stage(self.base_spa, self.spa_stage)

    def effective_spd(self) -> int:
        from .damage import apply_stage
        return apply_stage(self.base_spd, self.spd_stage)


@dataclass(frozen=True)
class FieldSide:
    """Hazards and screens on one side of the field."""
    spikes: int                    # 0-3 layers
    reflect_turns: int             # 0 = inactive
    light_screen_turns: int        # 0 = inactive


@dataclass(frozen=True)
class BattleState:
    """Complete battle state for 3v3 singles."""
    # Teams — tuples of 3 Pokemon each
    team_p1: Tuple[Pokemon, ...]
    team_p2: Tuple[Pokemon, ...]
    # Who's active (index into team tuple)
    active_p1: int
    active_p2: int
    # Field
    field_p1: FieldSide
    field_p2: FieldSide
    weather: Optional[str]         # "sun"|"rain"|"sand"|"hail"
    weather_turns: int
    turn_number: int

    # --- Accessors ---

    def active(self, player: str) -> Pokemon:
        if player == "p1":
            return self.team_p1[self.active_p1]
        return self.team_p2[self.active_p2]

    def get_team(self, player: str):
        return self.team_p1 if player == "p1" else self.team_p2

    def get_active_idx(self, player: str) -> int:
        return self.active_p1 if player == "p1" else self.active_p2

    def opp(self, player: str) -> str:
        return "p2" if player == "p1" else "p1"

    # --- State mutations (return new state) ---

    def set_pokemon(self, player: str, idx: int, mon: Pokemon) -> "BattleState":
        """Replace a Pokemon in a team, return new state."""
        if player == "p1":
            t = self.team_p1
            new_team = t[:idx] + (mon,) + t[idx+1:]
            return replace(self, team_p1=new_team)
        else:
            t = self.team_p2
            new_team = t[:idx] + (mon,) + t[idx+1:]
            return replace(self, team_p2=new_team)

    def set_active(self, player: str, mon: Pokemon) -> "BattleState":
        """Replace the active Pokemon, return new state."""
        idx = self.get_active_idx(player)
        return self.set_pokemon(player, idx, mon)

    def set_field(self, player: str, field: FieldSide) -> "BattleState":
        if player == "p1":
            return replace(self, field_p1=field)
        return replace(self, field_p2=field)

    def is_terminal(self) -> bool:
        """Game over if either team is fully fainted."""
        p1_alive = any(m.alive() for m in self.team_p1)
        p2_alive = any(m.alive() for m in self.team_p2)
        return not p1_alive or not p2_alive

    def winner(self) -> Optional[str]:
        p1_alive = any(m.alive() for m in self.team_p1)
        p2_alive = any(m.alive() for m in self.team_p2)
        if not p2_alive:
            return "p1"
        if not p1_alive:
            return "p2"
        return None

    def alive_bench(self, player: str):
        """Indices of alive, non-active Pokemon on a team."""
        team = self.get_team(player)
        active_idx = self.get_active_idx(player)
        return [i for i, m in enumerate(team)
                if m.alive() and i != active_idx]


# ============================================================
# Builder: Showdown export → BattleState
# ============================================================

def make_pokemon(species: str, nature: str, evs: dict,
                 ivs: dict, moves: list, item: str,
                 ability: str, level: int = 50) -> Pokemon:
    """Build a Pokemon from team builder data."""
    from .stats import compute_all_stats, SPECIES_TYPES
    stats = compute_all_stats(species, nature, evs, ivs, level)
    types = SPECIES_TYPES[species]

    return Pokemon(
        species=species, types=types, ability=ability,
        item=item, item_consumed=False,
        moves=tuple(moves), move_locked=None,
        max_hp=stats["hp"],
        base_atk=stats["atk"], base_def=stats["def"],
        base_spa=stats["spa"], base_spd=stats["spd"],
        base_spe=stats["spe"],
        current_hp=stats["hp"],
        status=None, status_turns=0,
        atk_stage=0, def_stage=0, spa_stage=0,
        spd_stage=0, spe_stage=0,
        substitute_hp=0, taunt_turns=0,
        confused=False, confused_turns=0,
        flinched=False, last_move=None,
        last_damage_taken=0, last_damage_physical=False,
        protect_consecutive=0,
    )


EMPTY_FIELD = FieldSide(spikes=0, reflect_turns=0, light_screen_turns=0)


def make_battle(team1: list[Pokemon], team2: list[Pokemon]) -> BattleState:
    """Create initial battle state from two teams."""
    return BattleState(
        team_p1=tuple(team1), team_p2=tuple(team2),
        active_p1=0, active_p2=0,
        field_p1=EMPTY_FIELD, field_p2=EMPTY_FIELD,
        weather=None, weather_turns=0,
        turn_number=0,
    )
