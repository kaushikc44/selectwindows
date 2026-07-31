# tests/test_product_hint.py
from pathlib import Path

from app.engine.product_hint import map_product_hint


def test_bifold_aluminium_recognized():
    product_type, material, config_code = map_product_hint("bi-fold window, aluminium, laundry")
    assert product_type == "bi_fold"
    assert material == "aluminium"


def test_double_hung_timber_recognized():
    product_type, material, _ = map_product_hint("double hung timber window for the bedroom")
    assert product_type == "double_hung"
    assert material == "timber"


def test_none_text_returns_all_unknown():
    assert map_product_hint(None) == ("unknown", "unknown", None)


def test_empty_text_returns_all_unknown():
    assert map_product_hint("") == ("unknown", "unknown", None)


def test_unrecognized_text_falls_back_to_unknown_not_guessed():
    product_type, material, config_code = map_product_hint("something we chatted about on site")
    assert product_type == "unknown"
    assert material == "unknown"
    assert config_code is None


def test_config_code_token_detected_when_present():
    _, _, config_code = map_product_hint("Need a BFW-3 for the laundry, aluminium")
    assert config_code == "BFW-3"


def test_config_code_absent_when_not_mentioned():
    _, _, config_code = map_product_hint("bi-fold window aluminium laundry")
    assert config_code is None


def test_hinged_matches_bare_word_not_just_hinged_door():
    # regression: the missing-info email tells reps to reply with the bare
    # word "hinged" (see app/output/missing_info.py PRODUCT_TYPE_OPTIONS) —
    # the keyword list must accept that exact word, not just "hinged door".
    assert map_product_hint("Hinged is the product type")[0] == "hinged"
    assert map_product_hint("Product type hinged")[0] == "hinged"
    assert map_product_hint("it's a hinged door")[0] == "hinged"


def test_product_hint_module_never_imports_openai():
    text = Path(__file__).parent.parent.joinpath("app/engine/product_hint.py").read_text()
    assert "openai" not in text.lower()
