# app/engine/geometry.py
from decimal import ROUND_HALF_UP, Decimal

MIN_DIM_MM = 100
MAX_DIM_MM = 6000
AREA_QUANT = Decimal("0.001")


def validate_dimensions(width_mm: int, height_mm: int) -> None:
    for name, value in (("width_mm", width_mm), ("height_mm", height_mm)):
        if not (MIN_DIM_MM <= value <= MAX_DIM_MM):
            raise ValueError(f"{name}={value} out of range [{MIN_DIM_MM}, {MAX_DIM_MM}]")


def unit_area_m2(width_mm: int, height_mm: int) -> Decimal:
    """Area of a single panel in m^2, to 3 decimal places."""
    validate_dimensions(width_mm, height_mm)
    area = Decimal(width_mm) * Decimal(height_mm) / Decimal(1_000_000)
    return area.quantize(AREA_QUANT, rounding=ROUND_HALF_UP)


def line_area_m2(width_mm: int, height_mm: int, qty: int) -> Decimal:
    """Area of qty identical panels in m^2, to 3 decimal places."""
    if qty < 1:
        raise ValueError(f"qty={qty} must be >= 1")
    total = unit_area_m2(width_mm, height_mm) * qty
    return total.quantize(AREA_QUANT, rounding=ROUND_HALF_UP)


def apply_waste(area_m2: Decimal, waste_percent: Decimal) -> Decimal:
    """Inflate an area by a waste percentage, to 3 decimal places."""
    inflated = area_m2 * (Decimal("1") + waste_percent / Decimal("100"))
    return inflated.quantize(AREA_QUANT, rounding=ROUND_HALF_UP)
