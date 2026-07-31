# tests/test_config_codes.py
from app.engine.config_codes import parse_config_code


def test_awning_bare_code():
    parsed = parse_config_code("AW")
    assert parsed.recognized is True
    assert parsed.product_type == "awning"


def test_casement_hinge_direction():
    left = parse_config_code("CA-L")
    right = parse_config_code("CA-R")
    assert left.segments[0].product_type == "casement"
    assert left.segments[0].direction == "L"
    assert right.segments[0].direction == "R"


def test_double_hung_bare_code():
    assert parse_config_code("DH").product_type == "double_hung"


def test_sliding_window_lite_count():
    parsed = parse_config_code("SL2")
    assert parsed.segments[0].product_type == "sliding"
    assert parsed.segments[0].panel_count == 2


def test_sliding_door_lite_count():
    parsed = parse_config_code("SD3")
    assert parsed.segments[0].product_type == "sliding"
    assert parsed.segments[0].panel_count == 3


def test_bifold_window_panel_count():
    parsed = parse_config_code("BFW-3")
    assert parsed.segments[0].product_type == "bi_fold"
    assert parsed.segments[0].panel_count == 3


def test_bifold_door_panel_count_and_fold_direction():
    parsed = parse_config_code("BFD-3+L")
    seg = parsed.segments[0]
    assert seg.product_type == "bi_fold"
    assert seg.panel_count == 3
    assert seg.direction == "L"


def test_bifold_door_panel_count_without_direction():
    parsed = parse_config_code("BFD-4")
    seg = parsed.segments[0]
    assert seg.panel_count == 4
    assert seg.direction is None


def test_hinged_door_direction():
    assert parse_config_code("HD-L").segments[0].direction == "L"


def test_stacker_door_panel_count():
    parsed = parse_config_code("STK-3")
    assert parsed.segments[0].product_type == "stacking"
    assert parsed.segments[0].panel_count == 3


def test_cedar_entry_bare_code():
    assert parse_config_code("CED").product_type == "cedar_entry"


def test_combination_code_splits_into_segments():
    parsed = parse_config_code("DH-PIC-DH")
    assert len(parsed.segments) == 3
    assert [s.product_type for s in parsed.segments] == ["double_hung", "unknown", "double_hung"]
    assert parsed.segments[1].fixed is True
    assert parsed.recognized is True  # PIC is a recognized "fixed lite" marker, not a failure


def test_unrecognized_code_flagged_not_guessed():
    parsed = parse_config_code("ZZTOP-9")
    assert parsed.recognized is False
    assert parsed.product_type == "unknown"


def test_lowercase_input_normalized():
    assert parse_config_code("aw").product_type == "awning"


def test_sliding_window_vs_door_category_distinguished():
    # SL and SD both map to product_type "sliding" — category is the one
    # place the window/door distinction survives.
    assert parse_config_code("SL2").category == "window"
    assert parse_config_code("SD2").category == "door"


def test_bifold_window_vs_door_category_distinguished():
    assert parse_config_code("BFW-4").category == "window"
    assert parse_config_code("BFD-4").category == "door"


def test_unambiguous_window_codes_categorized():
    for code in ("AW", "CA-L", "DH", "LV", "PW", "SS", "GS"):
        assert parse_config_code(code).category == "window", code


def test_powerlouvre_bare_code():
    assert parse_config_code("PW").product_type == "powerlouvre"


def test_unambiguous_door_codes_categorized():
    for code in ("HD-L", "STK-3", "CED"):
        assert parse_config_code(code).category == "door", code


def test_combination_code_category_unknown():
    assert parse_config_code("DH-PIC-DH").category == "unknown"


def test_unrecognized_code_category_unknown():
    assert parse_config_code("ZZTOP-9").category == "unknown"
