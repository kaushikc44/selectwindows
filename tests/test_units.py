# tests/test_units.py
import pytest

from app.engine.units import UnknownUnitError, normalize_to_mm


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        (79, "cm", 790),
        (1.48, "m", 1480),
        (900, "mm", 900),
        (36, "in", 914),  # 36 * 25.4 = 914.4 -> rounds to 914
        (0.9, "M", 900),  # case-insensitive
        (79, " cm ", 790),  # tolerant of whitespace
    ],
)
def test_normalize_to_mm(value, unit, expected):
    assert normalize_to_mm(value, unit) == expected


def test_unknown_unit_raises():
    with pytest.raises(UnknownUnitError):
        normalize_to_mm(79, "furlongs")


def test_engine_module_never_imports_openai():
    import pathlib

    text = pathlib.Path(__file__).parent.parent.joinpath("app/engine/units.py").read_text()
    assert "openai" not in text.lower()
