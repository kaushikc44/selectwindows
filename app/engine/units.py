# app/engine/units.py
"""Deterministic unit conversion. The LLM extracts raw {value, unit} pairs
from AR-overlay pills etc.; it never converts units itself — that's
arithmetic, and the hard constraint is "LLM extracts and classifies only"."""

_MM_PER_UNIT = {
    "mm": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
}


class UnknownUnitError(ValueError):
    pass


def normalize_to_mm(value: float, unit: str) -> int:
    key = unit.strip().lower()
    if key not in _MM_PER_UNIT:
        raise UnknownUnitError(f"unrecognized unit: {unit!r}")
    return round(value * _MM_PER_UNIT[key])
