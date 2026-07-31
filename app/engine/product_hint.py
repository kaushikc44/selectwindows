# app/engine/product_hint.py
"""Deterministic keyword mapping from free text (e.g. an email's
product_hint field, itself an LLM-extracted phrase) onto the fixed
product_type/material taxonomy — same pattern as pricing.py's
map_glass_option. The LLM only ever extracts a phrase; mapping that phrase
to an enum is plain Python, never guessed by the model itself."""

from app.engine.config_codes import parse_config_code

_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "bi_fold": ["bi-fold", "bifold", "bi fold"],
    "double_hung": ["double hung", "double-hung"],
    "casement": ["casement"],
    "awning": ["awning"],
    "sliding": ["sliding", "slider"],
    "louvre": ["louvre", "louver"],
    "powerlouvre": ["powerlouvre", "power louvre"],
    "sashless": ["sashless"],
    "gas_strut": ["gas strut"],
    "stacking": ["stacker", "stacking"],
    "hinged": ["hinged", "hinge door"],
    "cedar_entry": ["cedar entry", "entry door"],
}

_MATERIAL_KEYWORDS: dict[str, list[str]] = {
    "aluminium": ["aluminium", "aluminum", "alum"],
    "timber": ["timber", "wood", "wooden"],
}


def map_product_hint(text: str | None) -> tuple[str, str, str | None]:
    """Returns (product_type, material, config_code). Any part not
    recognized falls back to "unknown" rather than being guessed."""
    if not text:
        return "unknown", "unknown", None

    normalized = text.lower()

    config_code = None
    for token in text.replace(",", " ").split():
        parsed = parse_config_code(token)
        if parsed.recognized and len(parsed.segments) == 1:
            config_code = token.strip().upper()
            break

    product_type = "unknown"
    for candidate, keywords in _PRODUCT_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            product_type = candidate
            break

    material = "unknown"
    for candidate, keywords in _MATERIAL_KEYWORDS.items():
        if any(kw in normalized for kw in keywords):
            material = candidate
            break

    return product_type, material, config_code
