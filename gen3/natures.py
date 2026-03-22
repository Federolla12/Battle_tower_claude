"""
Gen 3 Natures — stat multipliers.
"""

# Each nature maps to (boosted_stat, hindered_stat) or None for neutral.
# Stats: "atk", "def", "spa", "spd", "spe"
NATURES = {
    "Hardy":   None,
    "Lonely":  ("atk", "def"),
    "Brave":   ("atk", "spe"),
    "Adamant": ("atk", "spa"),
    "Naughty": ("atk", "spd"),
    "Bold":    ("def", "atk"),
    "Docile":  None,
    "Relaxed": ("def", "spe"),
    "Impish":  ("def", "spa"),
    "Lax":     ("def", "spd"),
    "Timid":   ("spe", "atk"),
    "Hasty":   ("spe", "def"),
    "Serious": None,
    "Jolly":   ("spe", "spa"),
    "Naive":   ("spe", "spd"),
    "Modest":  ("spa", "atk"),
    "Mild":    ("spa", "def"),
    "Quiet":   ("spa", "spe"),
    "Bashful": None,
    "Rash":    ("spa", "spd"),
    "Calm":    ("spd", "atk"),
    "Gentle":  ("spd", "def"),
    "Sassy":   ("spd", "spe"),
    "Careful": ("spd", "spa"),
    "Quirky":  None,
}


def nature_modifier(nature: str, stat: str) -> float:
    """Returns 1.1, 0.9, or 1.0 for the given nature and stat."""
    entry = NATURES.get(nature)
    if entry is None:
        return 1.0
    boosted, hindered = entry
    if stat == boosted:
        return 1.1
    if stat == hindered:
        return 0.9
    return 1.0
