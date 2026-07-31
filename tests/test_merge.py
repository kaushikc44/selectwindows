# tests/test_merge.py
import pytest

from app.engine.merge import DimensionConflictError, merge_field_value, resolve_dimension
from app.schemas import DimensionReading, FieldValue


def test_resolve_dimension_returns_none_for_no_readings():
    assert resolve_dimension([]) is None


def test_resolve_dimension_single_reading_passes_through():
    resolved = resolve_dimension([DimensionReading(value_mm=1200, source="ar_overlay")])
    assert resolved.value_mm == 1200
    assert resolved.source == "ar_overlay"


def test_resolve_dimension_form_field_beats_ar_overlay_when_agreeing():
    readings = [
        DimensionReading(value_mm=1200, source="ar_overlay"),
        DimensionReading(value_mm=1210, source="form_field"),  # within 5%
    ]
    resolved = resolve_dimension(readings)
    assert resolved.source == "form_field"
    assert resolved.value_mm == 1210


def test_resolve_dimension_rep_reply_beats_everything():
    readings = [
        DimensionReading(value_mm=1200, source="form_field"),
        DimensionReading(value_mm=1205, source="rep_reply"),
    ]
    resolved = resolve_dimension(readings)
    assert resolved.source == "rep_reply"


def test_resolve_dimension_raises_on_conflict_over_15_percent():
    readings = [
        DimensionReading(value_mm=1000, source="ar_overlay"),
        DimensionReading(value_mm=1200, source="email_body"),  # 20% apart
    ]
    with pytest.raises(DimensionConflictError):
        resolve_dimension(readings)


def test_resolve_dimension_allows_small_disagreement_under_threshold():
    readings = [
        DimensionReading(value_mm=1000, source="ar_overlay"),
        DimensionReading(value_mm=1040, source="email_body"),  # 4% apart, within threshold
    ]
    resolved = resolve_dimension(readings)
    # within tolerance, so no conflict raised; ar_overlay outranks email_body
    # outright (only one ar_overlay reading present — nothing to resolve via
    # multiple readings)
    assert resolved.value_mm == 1000
    assert resolved.source == "ar_overlay"
    assert resolved.multi_reading is False


def test_resolve_dimension_uses_minimum_of_same_tier_readings_within_tolerance():
    # regression: two real AR-overlay photos of the same edge came back
    # 2700mm / 2470mm (~8.5% apart) — well under the old 5% threshold's
    # false-positive rate for a single AR-overlay pair. Resolves to the
    # MINIMUM (not an average) — same trade convention as the paper form's
    # multi-point readings: size to the tightest constraint so the
    # manufactured unit is never too big to fit an imprecise opening.
    readings = [
        DimensionReading(value_mm=2700, source="ar_overlay"),
        DimensionReading(value_mm=2470, source="ar_overlay"),
    ]
    resolved = resolve_dimension(readings)
    assert resolved.value_mm == 2470
    assert resolved.source == "ar_overlay"
    assert resolved.multi_reading is True


def test_resolve_dimension_does_not_blend_across_different_precedence_tiers():
    # a lower-precedence reading must never get blended into a
    # higher-precedence one, even within tolerance — it's simply outranked.
    readings = [
        DimensionReading(value_mm=1000, source="rep_reply"),
        DimensionReading(value_mm=1050, source="ar_overlay"),  # 5% apart
    ]
    resolved = resolve_dimension(readings)
    assert resolved.value_mm == 1000
    assert resolved.source == "rep_reply"
    assert resolved.multi_reading is False


def test_resolve_dimension_identical_same_tier_readings_not_marked_multi_reading():
    # two confirming photos of the same edge agreeing exactly is not
    # "multiple readings resolved" — nothing was blended, flag stays off.
    readings = [
        DimensionReading(value_mm=3470, source="ar_overlay"),
        DimensionReading(value_mm=3470, source="ar_overlay"),
    ]
    resolved = resolve_dimension(readings)
    assert resolved.value_mm == 3470
    assert resolved.multi_reading is False


def test_resolve_dimension_exactly_at_threshold_boundary_does_not_conflict():
    readings = [
        DimensionReading(value_mm=1000, source="ar_overlay"),
        DimensionReading(value_mm=1150, source="ar_overlay"),  # exactly 15% apart
    ]
    resolved = resolve_dimension(readings)
    assert resolved.multi_reading is True
    assert resolved.value_mm == 1000


def test_merge_field_value_picks_highest_precedence_present():
    candidates = [
        FieldValue(value="from email", source="email_body"),
        FieldValue(value="from form", source="form_field"),
    ]
    result = merge_field_value(candidates)
    assert result.value == "from form"
    assert result.source == "form_field"


def test_merge_field_value_skips_missing_candidates():
    candidates = [
        FieldValue(value=None, source="missing"),
        FieldValue(value="Sarah Nguyen", source="email_body"),
    ]
    result = merge_field_value(candidates)
    assert result.value == "Sarah Nguyen"


def test_merge_field_value_all_missing_returns_missing():
    candidates = [FieldValue(value=None, source="missing"), FieldValue(value=None, source="missing")]
    result = merge_field_value(candidates)
    assert result.source == "missing"
    assert result.value is None
