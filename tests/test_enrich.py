# tests/test_enrich.py
from pathlib import Path

from app.engine.enrich import enrich_item, load_defaults, reveal_depth_for_construction, wind_rating_n_class

DEFAULTS_PATH = Path(__file__).parent.parent / "app" / "engine" / "defaults.yaml"


def _defaults():
    return load_defaults(DEFAULTS_PATH)


def test_defaults_file_is_flagged_placeholder():
    assert _defaults()["placeholder"] is True


def test_known_product_and_material_returns_expected_row():
    result = enrich_item("bi_fold", "aluminium", "medium", _defaults())

    assert result.glass_spec == "double_glazed"
    assert result.safety_glass_required is True
    assert "multi-point lock" in result.hardware
    assert result.labour_hours == 4.0
    assert result.men_required == 2
    assert result.source == "default"
    assert result.unrecognized is False


def test_labour_hours_scale_with_size_band():
    defaults = _defaults()
    small = enrich_item("bi_fold", "aluminium", "small", defaults)
    xl = enrich_item("bi_fold", "aluminium", "xl", defaults)
    assert small.labour_hours < xl.labour_hours


def test_unrecognized_size_band_falls_back_to_medium():
    defaults = _defaults()
    medium = enrich_item("awning", "aluminium", "medium", defaults)
    weird = enrich_item("awning", "aluminium", "some_new_band", defaults)
    assert weird.labour_hours == medium.labour_hours


def test_unrecognized_product_type_falls_back_and_flags():
    result = enrich_item("teleporter", "aluminium", "medium", _defaults())

    assert result.unrecognized is True
    assert result.glass_spec == "single"  # unknown/aluminium row


def test_unrecognized_material_within_known_product_falls_back_and_flags():
    result = enrich_item("bi_fold", "unobtainium", "medium", _defaults())

    assert result.unrecognized is True


def test_wind_rating_placeholder_mapping():
    defaults = _defaults()
    assert wind_rating_n_class("1000", defaults) == "N3"
    assert wind_rating_n_class("unmarked", defaults) == "unmarked"
    assert wind_rating_n_class("not-a-real-rating", defaults) == "unmarked"


def test_reveal_depth_by_construction():
    defaults = _defaults()
    assert reveal_depth_for_construction("cavity_brick", defaults) == 45
    assert reveal_depth_for_construction("timber_frame", defaults) == 28
    assert reveal_depth_for_construction(None, defaults) == "unmarked"
    assert reveal_depth_for_construction("not-a-real-construction", defaults) == "unmarked"
