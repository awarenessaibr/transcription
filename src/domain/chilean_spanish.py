"""Chilean Spanish text post-processing — pure domain logic, no external deps."""
from __future__ import annotations

import re

_CHILEAN_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\bpal otro\b", "pa'l otro"),
    (r"\bpo\b", "po'"),
    (r"\bchiquillos\b", "cabros"),
    (r"\bweon\b", "weón"),
    (r"\bsi po\b", "sí poh"),
    (r"\bvo(s)?\b", "vo'"),
    (r"\bnaiden\b", "naidie"),
]


def post_process_chilean_spanish(text: str) -> str:
    """Apply Chilean Spanish colloquial corrections."""
    for pattern, replacement in _CHILEAN_REPLACEMENTS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
