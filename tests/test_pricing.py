# tests/test_pricing.py
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from app.engine.pricing import HardwareInput, PanelInput, load_rules, price_quote, quantize_money

RULES_PATH = Path(__file__).parent.parent / "app" / "engine" / "rules.yaml"


def _rules():
    return load_rules(RULES_PATH)


def test_golden_two_toughened_1200x900_full_breakdown():
    panels = [PanelInput(label="W1", width_mm=1200, height_mm=900, qty=2, glass_type="toughened")]

    result = price_quote(panels, [], _rules())

    assert result.panel_lines[0].area_m2 == Decimal("2.160")
    assert result.glass_subtotal == Decimal("408.24")
    assert result.waste_amount == Decimal("19.44")
    assert result.labour_amount == Decimal("82.40")
    assert result.hardware_subtotal == Decimal("0.00")
    assert result.gst_amount == Decimal("49.06")
    assert result.total == Decimal("539.70")


def test_hardware_lines_priced_from_catalog_inputs_only():
    panels = [PanelInput(label="W1", width_mm=1200, height_mm=900, qty=1, glass_type="clear_float")]
    hardware = [HardwareInput(code="SIL-01", qty=3, unit_price=Decimal("8.50"))]

    result = price_quote(panels, hardware, _rules())

    assert result.hardware_line_totals == [Decimal("25.50")]
    assert result.hardware_subtotal == Decimal("25.50")


def test_minimum_charge_per_panel_applies_to_tiny_panel():
    panels = [PanelInput(label="W1", width_mm=100, height_mm=100, qty=1, glass_type="clear_float")]

    result = price_quote(panels, [], _rules())

    assert result.panel_lines[0].line_total == Decimal("60.00")
    assert result.glass_subtotal == Decimal("60.00")


def test_quantize_money_uses_round_half_up_not_banker_rounding():
    # ROUND_HALF_UP: 2.345 -> 2.35 (banker's rounding / ROUND_HALF_EVEN would give 2.34)
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")
    assert Decimal("2.345").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.35")


def test_gst_is_a_distinct_final_line_applied_after_subtotal():
    panels = [PanelInput(label="W1", width_mm=1200, height_mm=900, qty=1, glass_type="toughened")]
    result = price_quote(panels, [], _rules())

    subtotal = result.glass_subtotal + result.hardware_subtotal + result.labour_amount
    assert result.gst_amount == quantize_money(subtotal * Decimal("10.0") / Decimal("100"))
    assert result.total == subtotal + result.gst_amount


def test_engine_module_never_imports_openai():
    engine_dir = Path(__file__).parent.parent / "app" / "engine"
    for py_file in engine_dir.glob("*.py"):
        text = py_file.read_text()
        assert "openai" not in text.lower(), f"{py_file} must not reference openai/LLM"
