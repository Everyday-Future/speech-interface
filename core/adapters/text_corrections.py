# core/adapters/text_corrections.py
import re

# (pattern, replacement) pairs applied in order
CORRECTIONS = [
    (re.compile(r'\bcircle\s*finder\b', re.IGNORECASE), 'circlefinder'),
]


def apply_corrections(text: str) -> str:
    """Apply autocorrections to transcribed text."""
    if not text:
        return text
    for pattern, replacement in CORRECTIONS:
        text = pattern.sub(replacement, text)
    return text
