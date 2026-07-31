# tests/test_flags.py
from app.engine.enrich import EnrichmentResult
from app.engine.flags import (
    AR_FLAG_MESSAGE,
    ASBESTOS_FLAG_MESSAGE,
    Flag,
    asbestos_flags,
    ar_measurement_flags,
    build_flags,
    compute_readiness_score,
    default_enrichment_flags,
    multi_reading_dimension_flags,
    safety_glass_flags,
)
from app.schemas import DimensionReading, ExtractionInstallation, ExtractionItem


def _item(item_no=1, product_type="bi_fold", height_readings=None, width_readings=None, **overrides):
    base = dict(
        item_no=item_no,
        description_raw="bi-fold window, aluminium",
        product_type=product_type,
        material="aluminium",
        height_mm=1200,
        width_mm=900,
        confidence=0.9,
        height_readings=height_readings or [],
        width_readings=width_readings or [],
    )
    base.update(overrides)
    return ExtractionItem(**base)


def _enrichment(**overrides):
    base = dict(
        glass_spec="single",
        safety_glass_required=False,
        hardware=[],
        energy_u_value=None,
        energy_shgc=None,
        labour_hours=2.0,
        men_required=1,
        unrecognized=False,
    )
    base.update(overrides)
    return EnrichmentResult(**base)


def test_ar_measurement_flag_fires_when_any_item_has_ar_overlay_reading():
    items = [_item(height_readings=[DimensionReading(value_mm=1200, source="ar_overlay")])]
    flags = ar_measurement_flags(items)
    assert len(flags) == 1
    assert flags[0].message == AR_FLAG_MESSAGE


def test_ar_measurement_flag_absent_when_no_ar_source():
    items = [_item(height_readings=[DimensionReading(value_mm=1200, source="form_field")])]
    assert ar_measurement_flags(items) == []


def test_ar_measurement_flag_absent_for_manual_entry_only():
    # A typed-in worker-app dimension (app/api/worker_quotes.py::
    # enter_dimension_manually) must never carry the "AR ±20mm, site-check
    # required" disclaimer — it was never read off an AR photo at all.
    items = [_item(height_readings=[DimensionReading(value_mm=1200, source="manual_entry")])]
    assert ar_measurement_flags(items) == []


def test_asbestos_flag_fires_when_yes():
    installation = ExtractionInstallation(asbestos="yes")
    flags = asbestos_flags(installation)
    assert len(flags) == 1
    assert flags[0].message == ASBESTOS_FLAG_MESSAGE


def test_asbestos_flag_absent_when_no_or_unmarked():
    assert asbestos_flags(ExtractionInstallation(asbestos="no")) == []
    assert asbestos_flags(ExtractionInstallation(asbestos="unmarked")) == []
    assert asbestos_flags(None) == []


def test_safety_glass_flag_fires_for_door_product_types():
    items = [_item(product_type="hinged"), _item(item_no=2, product_type="cedar_entry")]
    flags = safety_glass_flags(items)
    assert len(flags) == 2


def test_safety_glass_flag_absent_for_window_only_product_types():
    items = [_item(product_type="awning"), _item(item_no=2, product_type="double_hung")]
    assert safety_glass_flags(items) == []


def test_safety_glass_flag_fires_for_low_sill_regardless_of_product_type():
    items = [_item(product_type="awning")]
    flags = safety_glass_flags(items, sill_height_mm={1: 400})
    assert len(flags) == 1


def test_safety_glass_flag_absent_for_sliding_window_when_config_code_present():
    # regression: "sliding" alone is ambiguous (shared with sliding doors),
    # but SL2 unambiguously means sliding *window* — no config_code fallback needed.
    items = [_item(product_type="sliding", config_code="SL2")]
    assert safety_glass_flags(items) == []


def test_safety_glass_flag_fires_for_sliding_door_when_config_code_present():
    items = [_item(product_type="sliding", config_code="SD2")]
    flags = safety_glass_flags(items)
    assert len(flags) == 1


def test_safety_glass_flag_absent_for_bifold_window_when_config_code_present():
    items = [_item(product_type="bi_fold", config_code="BFW-4")]
    assert safety_glass_flags(items) == []


def test_safety_glass_flag_fires_for_bifold_door_when_config_code_present():
    items = [_item(product_type="bi_fold", config_code="BFD-4")]
    flags = safety_glass_flags(items)
    assert len(flags) == 1


def test_safety_glass_flag_falls_back_to_product_type_without_config_code():
    # unchanged legacy behavior: no config_code means "sliding"/"bi_fold" are
    # still over-inclusively treated as doors (safer than under-flagging).
    items = [_item(product_type="sliding", config_code=None)]
    flags = safety_glass_flags(items)
    assert len(flags) == 1


def test_safety_glass_flag_unrecognized_config_code_falls_back_to_product_type():
    items = [_item(product_type="sliding", config_code="ZZTOP-9")]
    flags = safety_glass_flags(items)
    assert len(flags) == 1


def test_default_enrichment_flag_one_per_item():
    flags = default_enrichment_flags([(1, _enrichment()), (2, _enrichment())])
    assert len(flags) == 2
    assert "DEFAULT placeholder" in flags[0].message


def test_default_enrichment_flag_notes_unrecognized():
    flags = default_enrichment_flags([(1, _enrichment(unrecognized=True))])
    assert "unrecognized" in flags[0].message


def test_llm_estimate_enrichment_flag_uses_distinct_ai_wording():
    flags = default_enrichment_flags([(1, _enrichment(source="llm_estimate"))])
    assert len(flags) == 1
    assert flags[0].code == "llm_material_estimate"
    assert "AI ESTIMATE" in flags[0].message
    assert "DEFAULT placeholder" not in flags[0].message


def test_build_flags_combines_all_rules():
    items = [_item(height_readings=[DimensionReading(value_mm=1200, source="ar_overlay")])]
    installation = ExtractionInstallation(asbestos="yes")
    flags = build_flags(items, installation, [(1, _enrichment())])

    codes = {f.code for f in flags}
    assert codes == {"ar_measurement", "asbestos", "as1288_safety_glass", "default_spec"}


def test_multi_reading_dimension_flag_fires_when_item_marked():
    items = [_item(dimensions_multi_reading=True)]
    flags = multi_reading_dimension_flags(items)
    assert len(flags) == 1
    assert flags[0].code == "dimensions_multi_reading"
    assert "Item 1" in flags[0].message
    assert "minimum" in flags[0].message
    assert "confirm exact measurement on site" in flags[0].message


def test_multi_reading_dimension_flag_absent_when_not_marked():
    items = [_item(dimensions_multi_reading=False)]
    assert multi_reading_dimension_flags(items) == []


def test_build_flags_includes_multi_reading_dimension_flag():
    items = [_item(dimensions_multi_reading=True)]
    flags = build_flags(items, None, [(1, _enrichment())])
    codes = {f.code for f in flags}
    assert "dimensions_multi_reading" in codes


def test_owner_edit_enrichment_produces_no_flag():
    # Anthony's own materials correction (app/api/owner_quotes.py's edit
    # endpoint) is the highest-trust source there is — unlike llm_estimate/
    # default_spec it needs no "unverified" disclaimer.
    flags = default_enrichment_flags([(1, _enrichment(source="owner_edit"))])
    assert flags == []


def test_compute_readiness_score_no_flags_is_perfect():
    assert compute_readiness_score([]) == 100


def test_compute_readiness_score_subtracts_known_penalties():
    flags = [Flag(code="ar_measurement", message=""), Flag(code="as1288_safety_glass", message="")]
    assert compute_readiness_score(flags) == 100 - 10 - 5


def test_compute_readiness_score_asbestos_is_the_heaviest_penalty():
    assert compute_readiness_score([Flag(code="asbestos", message="")]) == 70


def test_compute_readiness_score_scales_with_flag_count():
    two_multi_reading = [
        Flag(code="dimensions_multi_reading", message=""),
        Flag(code="dimensions_multi_reading", message=""),
    ]
    assert compute_readiness_score(two_multi_reading) == 100 - 10 - 10


def test_compute_readiness_score_clamps_at_zero():
    many_asbestos = [Flag(code="asbestos", message="")] * 10
    assert compute_readiness_score(many_asbestos) == 0


def test_compute_readiness_score_ignores_unknown_flag_codes():
    assert compute_readiness_score([Flag(code="something_new", message="")]) == 100
