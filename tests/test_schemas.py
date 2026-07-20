# tests/test_schemas.py
import pytest
from pydantic import ValidationError

from app.schemas import ExtractionResult, PanelIn


def _panel(**overrides):
    base = dict(label="W1", width_mm=1200, height_mm=900, qty=1, glass_type="toughened", confidence=0.9)
    base.update(overrides)
    return base


def test_valid_panel_parses():
    panel = PanelIn(**_panel())
    assert panel.width_mm == 1200
    assert panel.confidence == 0.9


@pytest.mark.parametrize("field,value", [("width_mm", 99), ("width_mm", 6001), ("height_mm", 50)])
def test_dimension_out_of_range_rejected(field, value):
    with pytest.raises(ValidationError):
        PanelIn(**_panel(**{field: value}))


def test_qty_must_be_at_least_one():
    with pytest.raises(ValidationError):
        PanelIn(**_panel(qty=0))


@pytest.mark.parametrize("confidence", [-0.1, 1.1])
def test_confidence_out_of_range_rejected(confidence):
    with pytest.raises(ValidationError):
        PanelIn(**_panel(confidence=confidence))


def test_unknown_glass_type_accepted_by_schema():
    panel = PanelIn(**_panel(glass_type="unknown"))
    assert panel.glass_type == "unknown"


def test_extraction_result_needs_manual_below_threshold():
    result = ExtractionResult(panels=[_panel(confidence=0.5)], notes="")
    assert result.needs_manual is True


def test_extraction_result_ok_above_threshold():
    result = ExtractionResult(panels=[_panel(confidence=0.9)], notes="")
    assert result.needs_manual is False
