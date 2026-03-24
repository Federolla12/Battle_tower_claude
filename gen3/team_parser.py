"""
Showdown Team Paste Parser
==========================
Parses Pokemon Showdown export format into structured dicts that can be
fed directly into make_pokemon().

Supported format:
    Skarmory @ Leftovers
    Ability: Keen Eye
    EVs: 252 HP / 232 Def / 24 Spe
    Impish Nature
    IVs: 30 SpA / 30 SpD
    - Hidden Power
    - Taunt
    - Counter
    - Toxic

Teams are 3 Pokemon separated by blank lines.
"""

import re
from typing import TypedDict
from .stats import BASE_STATS, SPECIES_TYPES
from .moves import MOVE_DB
from .natures import NATURES


def parse_showdown_paste(text: str) -> list[dict]:
    """
    Parse a 3-Pokemon Showdown team paste.

    Returns a list of 3 dicts, each with keys:
        species, nature, evs, ivs, moves, item, ability

    Raises ValueError with a descriptive message if validation fails.
    """
    # Split into blocks (separated by blank lines)
    blocks = [b.strip() for b in re.split(r'\n\s*\n', text.strip()) if b.strip()]

    if len(blocks) != 3:
        raise ValueError(
            f"Expected exactly 3 Pokemon (got {len(blocks)}). "
            "Separate each Pokemon with a blank line."
        )

    mons = []
    for i, block in enumerate(blocks, 1):
        try:
            mons.append(_parse_one(block))
        except ValueError as e:
            raise ValueError(f"Pokemon #{i}: {e}") from e

    return mons


def _parse_one(block: str) -> dict:
    """Parse a single Pokemon block."""
    lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
    if not lines:
        raise ValueError("Empty Pokemon block")

    # --- Line 1: Species @ Item (nickname optional) ---
    header = lines[0]
    # Remove parenthetical nickname: "Nickname (Species) @ Item" → "Species @ Item"
    # OR: "Species (Nickname) @ Item" → keep species part
    nickname_re = re.match(r'^(.+?)\s*\(([^)]+)\)\s*(?:@\s*(.+))?$', header)
    simple_re = re.match(r'^([^@(]+?)\s*(?:@\s*(.+))?$', header)

    species = None
    item = None

    if nickname_re:
        # Could be "Nickname (Species) @ Item" format (Showdown sometimes uses this)
        name_part = nickname_re.group(1).strip()
        paren_part = nickname_re.group(2).strip()
        item_part = nickname_re.group(3)
        # The species is usually the part in parens if it matches known species,
        # otherwise the first part
        if paren_part in BASE_STATS:
            species = paren_part
        else:
            species = name_part
        item = item_part.strip() if item_part else None
    elif simple_re:
        species = simple_re.group(1).strip()
        item_part = simple_re.group(2)
        item = item_part.strip() if item_part else None

    if not species:
        raise ValueError(f"Could not parse species from: {lines[0]!r}")

    # Validate species
    if species not in BASE_STATS:
        known = ", ".join(sorted(BASE_STATS.keys()))
        raise ValueError(
            f"Unknown species {species!r}. "
            f"Currently supported: {known}"
        )

    # --- Parse remaining lines ---
    ability = None
    nature = None
    evs = {}
    ivs = {}
    moves = []

    for line in lines[1:]:
        line = line.strip()

        # Move line
        if line.startswith('-'):
            move_name = line.lstrip('- ').strip()
            # Handle Hidden Power: "Hidden Power [Ground]" → "Hidden Power"
            hp_match = re.match(r'Hidden Power\s*\[?(\w+)\]?', move_name, re.I)
            if hp_match:
                move_name = "Hidden Power"
            # Normalize common Showdown format differences
            MOVE_ALIASES = {
                "Softboiled": "Softboiled",
                "Soft Boiled": "Softboiled",
                "SoftBoiled": "Softboiled",
                "Double Edge": "Double-Edge",
                "Morning Sun": "Morning Sun",
                "BrickBreak": "Brick Break",
                "DragonClaw": "Dragon Claw",
                "AerialAce": "Aerial Ace",
                "IcePunch": "Ice Punch",
                "FirePunch": "Fire Punch",
                "ThunderPunch": "Thunderpunch",
                "ThunderWave": "Thunder Wave",
                "SludgeBomb": "Sludge Bomb",
                "PainSplit": "Pain Split",
                "GigaDrain": "Giga Drain",
                "ShadowBall": "Shadow Ball",
                "HyperVoice": "Hyper Voice",
                "DragonDance": "Dragon Dance",
                "SwordsDance": "Swords Dance",
                "CalmMind": "Calm Mind",
                "ConfuseRay": "Confuse Ray",
                "IronTail": "Iron Tail",
                "RockTomb": "Rock Tomb",
                "RockSlide": "Rock Slide",
                "AncientPower": "Ancient Power",
                "SilverWind": "Silver Wind",
                "NightShade": "Night Shade",
                "SeismicToss": "Seismic Toss",
                "WillOWisp": "Will-O-Wisp",
                "Will O Wisp": "Will-O-Wisp",
                "WillowiSp": "Will-O-Wisp",
                "FocusPunch": "Focus Punch",
                "MeteorMash": "Meteor Mash",
                "BodySlam": "Body Slam",
                "FireBlast": "Fire Blast",
                "SleepTalk": "Sleep Talk",
                "SelfDestruct": "Explosion",  # alias
            }
            move_name = MOVE_ALIASES.get(move_name, move_name)
            if move_name not in MOVE_DB:
                known_moves = ", ".join(sorted(MOVE_DB.keys()))
                raise ValueError(
                    f"Unknown move {move_name!r}. "
                    f"Supported moves: {known_moves}"
                )
            moves.append(move_name)
            continue

        # Ability line
        m = re.match(r'^Ability:\s*(.+)$', line, re.I)
        if m:
            ability = m.group(1).strip()
            continue

        # EVs line: "252 HP / 4 Atk / 252 SpD"
        m = re.match(r'^EVs:\s*(.+)$', line, re.I)
        if m:
            evs = _parse_stats(m.group(1))
            continue

        # IVs line
        m = re.match(r'^IVs:\s*(.+)$', line, re.I)
        if m:
            ivs = _parse_stats(m.group(1))
            continue

        # Nature line: "Impish Nature" or "Impish"
        m = re.match(r'^(\w+)\s+Nature$', line, re.I)
        if m:
            nature = m.group(1).capitalize()
            continue

        # Ignore unrecognized lines (level, happiness, etc.)

    # --- Validate ---
    if not moves:
        raise ValueError(f"{species}: No moves found")
    if len(moves) > 4:
        raise ValueError(f"{species}: Too many moves (max 4, got {len(moves)})")
    if len(moves) < 1:
        raise ValueError(f"{species}: Must have at least 1 move")

    if nature is None:
        nature = "Hardy"  # neutral default
    if nature not in NATURES:
        raise ValueError(
            f"{species}: Unknown nature {nature!r}. "
            f"Known: {', '.join(sorted(NATURES.keys()))}"
        )

    # Validate ability (warn but don't crash — just store it)
    # The engine only uses a handful of abilities; unknown ones are silently ignored

    # Validate item — items not in this set are silently dropped (no effect)
    KNOWN_ITEMS = {
        "Leftovers", "Choice Band", "Lum Berry", "Chesto Berry", "Sitrus Berry",
        "Salac Berry", "Petaya Berry", "Liechi Berry", "Apicot Berry", "Ganlon Berry",
        "Shell Bell", "Scope Lens", "Kings Rock", "Focus Band",
        "BrightPowder", "Brightpowder",
        "Black Belt", "Magnet", "Mystic Water", "Charcoal", "Miracle Seed",
        "NeverMeltIce", "Never-Melt Ice", "Soft Sand", "Hard Stone", "Sharp Beak",
        "Poison Barb", "Silver Powder", "SilverPowder", "Spell Tag", "TwistedSpoon",
        "Twisted Spoon", "Silk Scarf", "Metal Coat",
        None,
    }
    if item not in KNOWN_ITEMS:
        # Use None (no item) for truly unknown items — don't crash
        item = None

    return {
        "species": species,
        "nature": nature,
        "evs": evs,
        "ivs": ivs,
        "moves": moves,
        "item": item or "None",
        "ability": ability or "",
    }


def _parse_stats(text: str) -> dict:
    """Parse '252 HP / 4 Atk / 252 SpD' into {'hp': 252, 'atk': 4, 'spd': 252}."""
    STAT_ALIASES = {
        "hp": "hp", "atk": "atk", "def": "def", "spa": "spa",
        "spd": "spd", "spe": "spe",
        "attack": "atk", "defense": "def", "special attack": "spa",
        "special defense": "spd", "speed": "spe",
        "spatk": "spa", "spdef": "spd",
    }
    result = {}
    parts = re.split(r'[/,]', text)
    for part in parts:
        part = part.strip()
        m = re.match(r'^(\d+)\s+(.+)$', part)
        if m:
            val = int(m.group(1))
            stat_raw = m.group(2).strip().lower()
            stat = STAT_ALIASES.get(stat_raw)
            if stat:
                result[stat] = min(252, max(0, val))
    return result


class TeamWarning(TypedDict):
    code: str
    message: str
    species: str


def validate_team(mons: list[dict]) -> list[TeamWarning]:
    """Return non-fatal team warnings in a structured format."""
    warnings: list[TeamWarning] = []
    species_seen = set()
    for mon in mons:
        sp = mon["species"]
        if sp in species_seen:
            warnings.append({
                "code": "duplicate_species",
                "message": f"Duplicate species: {sp}",
                "species": sp,
            })
        species_seen.add(sp)

        if not mon.get("ability"):
            warnings.append({
                "code": "missing_ability",
                "message": f"{sp}: No ability specified — will use empty string",
                "species": sp,
            })

        if mon.get("item") == "None" or not mon.get("item"):
            warnings.append({
                "code": "missing_item",
                "message": f"{sp}: No item (or unknown item) — will have no item",
                "species": sp,
            })

        if len(mon["moves"]) < 4:
            warnings.append({
                "code": "incomplete_moveset",
                "message": f"{sp}: Only {len(mon['moves'])} move(s) specified",
                "species": sp,
            })

    return warnings
