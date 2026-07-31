# app/render/elevation.py
"""Deterministic SVG elevation diagrams rendered from config_code + H + W,
viewed from outside — see select-windows-domain-brief.md. No LLM involved;
this replaces reading a hand sketch once a rep uses config codes."""

import svgwrite

from app.engine.config_codes import ConfigSegment, parse_config_code

CANVAS_WIDTH = 320
CANVAS_HEIGHT = 260
MARGIN = 30
DIM_TEXT_HEIGHT = 30


def render_elevation(config_code: str, height_mm: int, width_mm: int) -> str:
    parsed = parse_config_code(config_code)

    dwg = svgwrite.Drawing(size=(CANVAS_WIDTH, CANVAS_HEIGHT))
    frame_w = CANVAS_WIDTH - 2 * MARGIN
    frame_h = CANVAS_HEIGHT - 2 * MARGIN - DIM_TEXT_HEIGHT
    x0, y0 = MARGIN, MARGIN

    dwg.add(dwg.rect(insert=(x0, y0), size=(frame_w, frame_h), fill="none", stroke="black", stroke_width=2))

    segments = parsed.segments or [ConfigSegment(raw=config_code, product_type="unknown", recognized=False)]
    slice_w = frame_w / len(segments)
    for i, seg in enumerate(segments):
        sx0 = x0 + i * slice_w
        _draw_segment(dwg, seg, sx0, y0, slice_w, frame_h)
        if i > 0:
            dwg.add(dwg.line(start=(sx0, y0), end=(sx0, y0 + frame_h), stroke="black", stroke_width=1))

    dwg.add(dwg.text(f"{width_mm} x {height_mm} mm", insert=(x0, y0 + frame_h + 20), font_size=14))

    return dwg.tostring()


def _draw_segment(dwg: svgwrite.Drawing, seg: ConfigSegment, x0: float, y0: float, w: float, h: float) -> None:
    cx, cy = x0 + w / 2, y0 + h / 2
    x1, y1 = x0 + w, y0 + h

    if seg.fixed:
        dwg.add(dwg.text("F", insert=(cx - 5, cy + 5), font_size=18))
        return

    if not seg.recognized:
        dwg.add(dwg.text("?", insert=(cx - 5, cy + 5), font_size=18, fill="red"))
        return

    if seg.product_type == "awning":
        # hinge at top -> apex top-centre
        apex = (cx, y0)
        _dashed(dwg, (x0, y1), apex)
        _dashed(dwg, (x1, y1), apex)
        return

    if seg.product_type in ("casement", "hinged") and seg.direction in ("L", "R"):
        if seg.direction == "L":
            apex = (x0, cy)
            _dashed(dwg, (x1, y0), apex)
            _dashed(dwg, (x1, y1), apex)
        else:
            apex = (x1, cy)
            _dashed(dwg, (x0, y0), apex)
            _dashed(dwg, (x0, y1), apex)
        return

    if seg.product_type == "double_hung":
        dwg.add(dwg.line(start=(x0, cy), end=(x1, cy), stroke="black", stroke_width=1))
        return

    if seg.product_type in ("sliding", "stacking"):
        panels = seg.panel_count or 2
        for p in range(1, panels):
            px = x0 + w * p / panels
            dwg.add(dwg.line(start=(px, y0), end=(px, y1), stroke="black", stroke_width=1))
        _arrow(dwg, (x0 + w * 0.3, y1 - 10), (x0 + w * 0.7, y1 - 10))
        return

    if seg.product_type == "bi_fold":
        panels = seg.panel_count or 2
        for p in range(1, panels):
            px = x0 + w * p / panels
            dwg.add(
                dwg.line(start=(px, y0), end=(px, y1), stroke="black", stroke_width=1, stroke_dasharray="2,2")
            )
        if seg.direction:
            side_x = x1 if seg.direction == "R" else x0
            _arrow(dwg, (cx, y1 - 10), (side_x, y1 - 10))
        return

    if seg.product_type == "louvre":
        blades = 6
        for b in range(1, blades):
            by = y0 + h * b / blades
            dwg.add(dwg.line(start=(x0, by), end=(x1, by), stroke="black", stroke_width=1))
        return

    dwg.add(dwg.text(seg.product_type, insert=(x0 + 4, cy), font_size=10))


def _dashed(dwg: svgwrite.Drawing, start: tuple[float, float], end: tuple[float, float]) -> None:
    dwg.add(dwg.line(start=start, end=end, stroke="black", stroke_width=1, stroke_dasharray="4,3"))


def _arrow(dwg: svgwrite.Drawing, start: tuple[float, float], end: tuple[float, float]) -> None:
    dwg.add(dwg.line(start=start, end=end, stroke="black", stroke_width=1.5))
    dwg.add(dwg.polygon(points=[end, (end[0] - 5, end[1] - 3), (end[0] - 5, end[1] + 3)], fill="black"))
