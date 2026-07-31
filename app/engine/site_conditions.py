# app/engine/site_conditions.py
"""Deterministic keyword detection over free text the rep actually wrote —
not an LLM guess, a literal substring check on text the model already
extracted verbatim (e.g. email_body site_notes)."""

# Phrases stating asbestos is NOT present — checked before the bare keyword
# so "no asbestos present" isn't mistaken for a positive mention. Not
# exhaustive (this is a keyword check, not an LLM), but covers the common
# ways a rep actually writes this.
_NEGATION_PHRASES = (
    "no asbestos",
    "not asbestos",
    "asbestos free",
    "asbestos-free",
    "without asbestos",
    "free of asbestos",
    "no known asbestos",
    "asbestos has been removed",
    "asbestos already removed",
)


def detect_asbestos_mention(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.lower()
    if "asbestos" not in lowered:
        return False
    return not any(phrase in lowered for phrase in _NEGATION_PHRASES)
