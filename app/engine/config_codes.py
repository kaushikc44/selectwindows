# app/engine/config_codes.py
"""Deterministic parser for the config-code shorthand vocabulary (see
select-windows-domain-brief.md). An unrecognized code, or an unrecognized
segment of a hyphenated combination, is flagged — never guessed."""

import re
from dataclasses import dataclass, field


@dataclass
class ConfigSegment:
    raw: str
    product_type: str
    panel_count: int | None = None
    direction: str | None = None  # "L" or "R", when the code states a hinge/fold side
    fixed: bool = False  # a fixed (non-opening) lite, e.g. "PIC"
    recognized: bool = True
    # "window" | "door" | "unknown" — the code vocabulary distinguishes these
    # even where product_type doesn't (SL = sliding *window*, SD = sliding
    # *door*; BFW/BFD likewise), so this is the one place that distinction
    # survives. "unknown" for unrecognized/fixed-lite segments.
    category: str = "unknown"


@dataclass
class ParsedConfigCode:
    raw_code: str
    segments: list[ConfigSegment] = field(default_factory=list)

    @property
    def recognized(self) -> bool:
        return bool(self.segments) and all(s.recognized for s in self.segments)

    @property
    def product_type(self) -> str:
        """Only meaningful for a single-segment code; a combination is
        several units side by side, not one product_type."""
        if len(self.segments) == 1:
            return self.segments[0].product_type
        return "unknown"

    @property
    def category(self) -> str:
        """"window" | "door" | "unknown" — only meaningful for a
        single-segment code, same caveat as product_type above."""
        if len(self.segments) == 1:
            return self.segments[0].category
        return "unknown"


def _parse_single(token: str) -> ConfigSegment:
    if token == "AW":
        return ConfigSegment(raw=token, product_type="awning", category="window")
    if token in ("CA-L", "CA-R"):
        return ConfigSegment(raw=token, product_type="casement", direction=token[-1], category="window")
    if token == "DH":
        return ConfigSegment(raw=token, product_type="double_hung", category="window")
    if m := re.fullmatch(r"SL(\d+)", token):
        return ConfigSegment(raw=token, product_type="sliding", panel_count=int(m.group(1)), category="window")
    if token == "LV":
        return ConfigSegment(raw=token, product_type="louvre", category="window")
    if token == "PW":
        return ConfigSegment(raw=token, product_type="powerlouvre", category="window")
    if token == "SS":
        return ConfigSegment(raw=token, product_type="sashless", category="window")
    if token == "GS":
        return ConfigSegment(raw=token, product_type="gas_strut", category="window")
    if m := re.fullmatch(r"BFW-(\d+)", token):
        return ConfigSegment(raw=token, product_type="bi_fold", panel_count=int(m.group(1)), category="window")
    if token in ("HD-L", "HD-R"):
        return ConfigSegment(raw=token, product_type="hinged", direction=token[-1], category="door")
    if m := re.fullmatch(r"SD(\d+)", token):
        return ConfigSegment(raw=token, product_type="sliding", panel_count=int(m.group(1)), category="door")
    if m := re.fullmatch(r"STK-(\d+)", token):
        return ConfigSegment(raw=token, product_type="stacking", panel_count=int(m.group(1)), category="door")
    if m := re.fullmatch(r"BFD-(\d+)(?:\+([LR]))?", token):
        return ConfigSegment(
            raw=token, product_type="bi_fold", panel_count=int(m.group(1)), direction=m.group(2), category="door"
        )
    if token == "CED":
        return ConfigSegment(raw=token, product_type="cedar_entry", category="door")
    if token == "PIC":
        return ConfigSegment(raw=token, product_type="unknown", fixed=True)
    return ConfigSegment(raw=token, product_type="unknown", recognized=False)


def parse_config_code(raw_code: str) -> ParsedConfigCode:
    raw = raw_code.strip().upper()

    whole = _parse_single(raw)
    if whole.recognized:
        return ParsedConfigCode(raw_code=raw_code, segments=[whole])

    tokens = raw.split("-")
    if len(tokens) > 1:
        return ParsedConfigCode(raw_code=raw_code, segments=[_parse_single(t) for t in tokens])

    return ParsedConfigCode(raw_code=raw_code, segments=[whole])
