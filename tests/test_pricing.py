# tests/test_pricing.py
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.engine.pricing import (
    InstallationInput,
    ItemInput,
    price_installation,
    price_item,
    price_quote,
    quantize_money,
    size_band,
    validate_dimensions,
)
from app.engine.pricing import load_rules as _load_rules

RULES_PATH = Path(__file__).parent.parent / "app" / "engine" / "rules.yaml"


def _rules():
    return _load_rules(RULES_PATH)


def test_rules_file_is_flagged_as_placeholder():
    assert _rules()["placeholder"] is True


def test_size_band_picks_smallest_matching_band():
    band, multiplier = size_band(900, 900, _rules())
    assert band == "small"
    assert multiplier == Decimal("0.8")


def test_size_band_uses_larger_of_height_width():
    band, _ = size_band(1200, 1600, _rules())  # width 1600 pushes into "large"
    assert band == "large"


@pytest.mark.parametrize("width,height", [(99, 900), (1200, 99), (20001, 900), (1200, 20001)])
def test_validate_dimensions_rejects_out_of_range(width, height):
    with pytest.raises(ValueError):
        validate_dimensions(width, height)


def test_validate_dimensions_accepts_boundaries():
    validate_dimensions(100, 20000)


def test_validate_dimensions_accepts_large_commercial_opening():
    # a summed multi-section commercial opening (see _sum_partial_segments)
    # can legitimately exceed the old 6000mm single-window ceiling.
    validate_dimensions(6060, 3470)


def test_price_item_bi_fold_aluminium_medium_no_glass_hint():
    item = ItemInput(item_no=1, product_type="bi_fold", material="aluminium", height_mm=1200, width_mm=900, qty=1)
    line = price_item(item, glass_option="single", rules=_rules())
    assert line.size_band == "medium"
    assert line.unit_price == Decimal("900.00")
    assert line.line_total == Decimal("900.00")


def test_price_item_scales_with_qty():
    item = ItemInput(item_no=1, product_type="awning", material="aluminium", height_mm=900, width_mm=900, qty=3)
    line = price_item(item, glass_option="single", rules=_rules())
    assert line.unit_price == Decimal("360.00")  # 450 base * 0.8 small-band multiplier
    assert line.line_total == Decimal("1080.00")


def test_price_item_unknown_product_and_material_fall_back():
    item = ItemInput(item_no=1, product_type="not_a_real_type", material="not_a_real_material", height_mm=900, width_mm=900, qty=1)
    line = price_item(item, glass_option="single", rules=_rules())
    assert line.unit_price == Decimal("440.00")  # unknown/unknown base 550 * 0.8


def test_glass_multiplier_applies_on_top_of_base():
    item = ItemInput(item_no=1, product_type="awning", material="aluminium", height_mm=1200, width_mm=900, qty=1)
    line = price_item(item, glass_option="double_glazed", rules=_rules())
    assert line.unit_price == Decimal("585.00")  # 450 * 1.0 (medium) * 1.3


def test_price_installation_with_no_detail_charges_only_base_fee():
    fee = price_installation(None, item_count=2, rules=_rules())
    assert fee == Decimal("300.00")  # 150 * 2 items


def test_price_installation_adds_floor_level_brick_and_scaffold():
    installation = InstallationInput(floor_level="2nd", brick_removal_m2=3, scaffold="yes")
    fee = price_installation(installation, item_count=1, rules=_rules())
    assert fee == Decimal("1100.00")  # 150 base + 200 floor + 450 brick(150*3) + 300 scaffold


def test_price_installation_ignores_unmarked_floor_level():
    installation = InstallationInput(floor_level="unmarked", scaffold="unmarked")
    fee = price_installation(installation, item_count=1, rules=_rules())
    assert fee == Decimal("150.00")


def test_price_installation_adds_hoist_and_brick_saw_equipment_fees():
    installation = InstallationInput(hoist="yes", brick_saw="yes")
    fee = price_installation(installation, item_count=1, rules=_rules())
    assert fee == Decimal("670.00")  # 150 base + 400 hoist + 120 brick saw


def test_price_installation_ignores_no_for_equipment_hire():
    installation = InstallationInput(scaffold="no", hoist="no", brick_saw="no")
    fee = price_installation(installation, item_count=1, rules=_rules())
    assert fee == Decimal("150.00")


@pytest.mark.parametrize(
    "product_type,material,unit_price,total",
    [
        ("bi_fold", "aluminium", "900.00", "1155.00"),
        ("awning", "aluminium", "450.00", "660.00"),
        ("casement", "aluminium", "480.00", "693.00"),
        ("double_hung", "timber", "850.00", "1100.00"),
        ("stacking", "aluminium", "1200.00", "1485.00"),
    ],
)
def test_golden_pricing_per_product_type_medium_single_glazed(product_type, material, unit_price, total):
    items = [
        ItemInput(item_no=1, product_type=product_type, material=material, height_mm=1200, width_mm=900, qty=1)
    ]
    result = price_quote(items, installation=None, glass_text=None, rules=_rules())

    assert result.item_lines[0].unit_price == Decimal(unit_price)
    assert result.total == Decimal(total)


def test_price_quote_full_breakdown_with_gst():
    items = [ItemInput(item_no=1, product_type="bi_fold", material="aluminium", height_mm=1200, width_mm=900, qty=1)]
    result = price_quote(items, installation=None, glass_text=None, rules=_rules())

    assert result.items_subtotal == Decimal("900.00")
    assert result.installation_subtotal == Decimal("150.00")
    assert result.gst_amount == Decimal("105.00")
    assert result.total == Decimal("1155.00")


def test_price_quote_maps_header_glass_text_to_multiplier():
    items = [ItemInput(item_no=1, product_type="awning", material="aluminium", height_mm=1200, width_mm=900, qty=1)]
    result = price_quote(items, installation=None, glass_text="double glazed throughout", rules=_rules())

    assert result.item_lines[0].unit_price == Decimal("585.00")


def test_quantize_money_uses_round_half_up_not_banker_rounding():
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")
    assert Decimal("2.345").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.35")


def test_gst_is_a_distinct_final_line_applied_after_subtotal():
    items = [ItemInput(item_no=1, product_type="sliding", material="timber", height_mm=1200, width_mm=900, qty=1)]
    result = price_quote(items, installation=None, glass_text=None, rules=_rules())

    subtotal = result.items_subtotal + result.installation_subtotal
    assert result.gst_amount == quantize_money(subtotal * Decimal("10.0") / Decimal("100"))
    assert result.total == subtotal + result.gst_amount


def test_engine_module_never_imports_openai():
    engine_dir = Path(__file__).parent.parent / "app" / "engine"
    for py_file in engine_dir.glob("*.py"):
        text = py_file.read_text()
        assert "openai" not in text.lower(), f"{py_file} must not reference openai/LLM"
