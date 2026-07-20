# tests/test_geometry.py
from decimal import Decimal

import pytest

from app.engine.geometry import apply_waste, line_area_m2, unit_area_m2, validate_dimensions


def test_unit_area_m2_exact():
    assert unit_area_m2(1200, 900) == Decimal("1.080")


def test_line_area_m2_scales_by_qty():
    assert line_area_m2(1200, 900, 2) == Decimal("2.160")


def test_apply_waste_five_percent():
    assert apply_waste(Decimal("2.160"), Decimal("5.0")) == Decimal("2.268")


@pytest.mark.parametrize("width,height", [(99, 900), (1200, 99), (6001, 900), (1200, 6001)])
def test_validate_dimensions_rejects_out_of_range(width, height):
    with pytest.raises(ValueError):
        validate_dimensions(width, height)


def test_validate_dimensions_accepts_boundaries():
    validate_dimensions(100, 6000)


def test_line_area_rejects_qty_below_one():
    with pytest.raises(ValueError):
        line_area_m2(1200, 900, 0)
