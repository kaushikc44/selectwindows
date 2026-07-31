# tests/test_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas import DimensionReading, ExtractionHeader, ExtractionItem, ExtractionResultV2, FieldValue


def _item(**overrides):
    base = dict(
        item_no=1,
        room="Laundry",
        qty=1,
        description_raw="bi-fold window, aluminium, laundry",
        product_type="bi_fold",
        material="aluminium",
        height_mm=1200,
        width_mm=900,
        confidence=0.9,
    )
    base.update(overrides)
    return base


def test_valid_item_parses():
    item = ExtractionItem(**_item())
    assert item.height_mm == 1200
    assert item.product_type == "bi_fold"


@pytest.mark.parametrize("field,value", [("height_mm", 99), ("height_mm", 20001), ("width_mm", 50)])
def test_dimension_out_of_range_rejected(field, value):
    with pytest.raises(ValidationError):
        ExtractionItem(**_item(**{field: value}))


def test_large_commercial_dimension_accepted():
    # a summed multi-section opening can legitimately exceed 6000mm now.
    item = ExtractionItem(**_item(width_mm=6060, height_mm=3470))
    assert item.width_mm == 6060


def test_qty_must_be_at_least_one():
    with pytest.raises(ValidationError):
        ExtractionItem(**_item(qty=0))


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValidationError):
        ExtractionItem(**_item(confidence=confidence))


def test_unknown_product_type_and_material_accepted():
    item = ExtractionItem(**_item(product_type="unknown", material="unknown"))
    assert item.product_type == "unknown"
    assert item.material == "unknown"


def test_header_defaults_to_all_unmarked_when_nothing_captured():
    header = ExtractionHeader()
    assert header.client_name is None
    assert header.wind_rating == "unmarked"
    assert header.reveal_28.selected is False
    assert header.reveal_28.species == "unmarked"


def test_needs_manual_true_below_overall_confidence_threshold():
    result = ExtractionResultV2(items=[_item()], overall_confidence=0.5)
    assert result.needs_manual is True


def test_needs_manual_true_when_unreadable_fields_present():
    result = ExtractionResultV2(items=[_item()], overall_confidence=0.9, unreadable_fields=["height_mm"])
    assert result.needs_manual is True


def test_needs_manual_true_for_low_confidence_item():
    result = ExtractionResultV2(items=[_item(confidence=0.4)], overall_confidence=0.9)
    assert result.needs_manual is True


def test_needs_manual_false_when_everything_confident_and_readable():
    result = ExtractionResultV2(items=[_item()], overall_confidence=0.9)
    assert result.needs_manual is False


def test_qty_defaulted_flag_survives_roundtrip():
    item = ExtractionItem(**_item(qty_defaulted=True))
    assert item.qty_defaulted is True


def test_field_value_defaults_to_missing_source():
    fv = FieldValue[str]()
    assert fv.value is None
    assert fv.source == "missing"
    assert fv.confidence is None


def test_field_value_holds_typed_value_and_source():
    fv = FieldValue[str](value="Sarah Nguyen", source="email_body", confidence=0.9)
    assert fv.value == "Sarah Nguyen"
    assert fv.source == "email_body"


def test_field_value_rejects_unknown_source():
    with pytest.raises(ValidationError):
        FieldValue[str](value="x", source="guessed")


def test_dimension_reading_rejects_out_of_range_mm():
    with pytest.raises(ValidationError):
        DimensionReading(value_mm=50, source="ar_overlay")


def test_dimension_reading_defaults_axis_labelled_true():
    reading = DimensionReading(value_mm=1200, source="form_field")
    assert reading.axis_labelled is True


def test_item_height_width_readings_default_empty_and_accept_candidates():
    item = ExtractionItem(
        **_item(
            height_readings=[DimensionReading(value_mm=1200, source="form_field")],
            width_readings=[
                DimensionReading(value_mm=900, source="form_field"),
                DimensionReading(value_mm=790, source="ar_overlay", axis_labelled=False),
            ],
        )
    )
    assert len(item.height_readings) == 1
    assert len(item.width_readings) == 2
    assert item.width_readings[1].axis_labelled is False
