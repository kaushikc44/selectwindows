# tests/test_elevation.py
import re
from pathlib import Path

from app.render.elevation import render_elevation


def test_render_module_never_imports_openai():
    render_dir = Path(__file__).parent.parent / "app" / "render"
    for py_file in render_dir.glob("*.py"):
        text = py_file.read_text()
        assert "openai" not in text.lower(), f"{py_file} must not reference openai/LLM"


def _lines(svg: str) -> list[dict]:
    return [
        {k: v for k, v in re.findall(r'(\w[\w-]*)="([^"]*)"', tag)}
        for tag in re.findall(r"<line [^>]*/>", svg)
    ]


def test_svg_is_well_formed_and_contains_dimensions():
    svg = render_elevation("AW", height_mm=900, width_mm=1200)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "1200 x 900 mm" in svg


def test_awning_apex_points_top_centre():
    svg = render_elevation("AW", height_mm=900, width_mm=1200)
    lines = _lines(svg)
    assert len(lines) == 2
    xs2 = {line["x2"] for line in lines}
    ys2 = {line["y2"] for line in lines}
    assert xs2 == {"160.0"}  # both dashed lines converge on the same x (apex)
    assert ys2 == {"30"}  # apex is at the top (y0)


def test_casement_left_apex_is_on_left_edge():
    svg = render_elevation("CA-L", height_mm=900, width_mm=1200)
    lines = _lines(svg)
    xs2 = {line["x2"] for line in lines}
    assert xs2 == {"30.0"}  # left edge (x0)


def test_casement_right_apex_is_on_right_edge():
    svg = render_elevation("CA-R", height_mm=900, width_mm=1200)
    lines = _lines(svg)
    xs2 = {line["x2"] for line in lines}
    assert xs2 == {"290.0"}  # right edge (x1)


def test_sliding_window_sl2_has_one_divider_and_an_arrow():
    svg = render_elevation("SL2", height_mm=900, width_mm=1200)
    # one vertical panel divider line (no dasharray) + one arrow line + polygon arrowhead
    assert svg.count("polygon") == 1
    plain_lines = [line for line in _lines(svg) if "stroke-dasharray" not in line]
    assert len(plain_lines) == 2  # divider + arrow shaft


def test_bifold_door_3_panel_has_two_dashed_dividers():
    svg = render_elevation("BFD-3", height_mm=900, width_mm=1200)
    dashed = [line for line in _lines(svg) if line.get("stroke-dasharray") == "2,2"]
    assert len(dashed) == 2  # 3 panels -> 2 dividers


def test_double_hung_has_one_midline_divider():
    svg = render_elevation("DH", height_mm=900, width_mm=1200)
    lines = _lines(svg)
    assert len(lines) == 1
    assert lines[0]["y1"] == lines[0]["y2"] == "115.0"  # horizontal midline


def test_combination_code_renders_all_segments():
    svg = render_elevation("DH-PIC-DH", height_mm=900, width_mm=1200)
    assert svg.count(">F<") == 1  # the fixed PIC segment
    # 2 internal segment-boundary dividers + 1 DH midline each side = 2 boundaries + 2 midlines
    assert svg.count("<line") >= 4


def test_unrecognized_code_renders_question_mark_not_crash():
    svg = render_elevation("ZZTOP-9", height_mm=900, width_mm=1200)
    assert ">?<" in svg
