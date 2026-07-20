# tests/test_pdf.py
from decimal import Decimal

import pytest

from app.models import GlassType, HardwareLine, Panel, Quote, QuoteStatus
from app.output.pdf import ESTIMATED_TAG, _render_html, generate_quote_pdf


def _sample_quote() -> Quote:
    quote = Quote(
        id="quote-1",
        status=QuoteStatus.pending_approval,
        glass_subtotal=Decimal("408.24"),
        hardware_subtotal=Decimal("25.50"),
        labour_amount=Decimal("82.40"),
        waste_amount=Decimal("19.44"),
        gst_amount=Decimal("49.06"),
        total=Decimal("539.70"),
    )
    quote.panels.append(
        Panel(
            label="W1",
            width_mm=1200,
            height_mm=900,
            qty=2,
            glass_type=GlassType.toughened,
            confidence=0.95,
            area_m2=Decimal("2.160"),
            line_total=Decimal("408.24"),
        )
    )
    quote.hardware_lines.append(
        HardwareLine(
            code="SIL-CLEAR",
            name="Clear silicone sealant",
            qty=3,
            unit_price=Decimal("8.50"),
            line_total=Decimal("25.50"),
            estimated=True,
        )
    )
    return quote


def test_html_contains_estimated_tag_on_ai_hardware_line():
    html = _render_html(_sample_quote())
    assert ESTIMATED_TAG in html
    assert "SIL-CLEAR" in html


def test_html_contains_gst_and_total_values():
    html = _render_html(_sample_quote())
    assert "$49.06" in html
    assert "$539.70" in html


def test_non_estimated_hardware_line_has_no_estimated_tag():
    quote = _sample_quote()
    quote.hardware_lines[0].estimated = False
    html = _render_html(quote)
    row = next(line for line in html.splitlines() if "SIL-CLEAR" in line)
    assert ESTIMATED_TAG not in row


def test_generate_quote_pdf_produces_pdf_bytes():
    try:
        pdf_bytes = generate_quote_pdf(_sample_quote())
    except OSError:
        pytest.skip("WeasyPrint system libraries (Pango/GObject) not installed in this environment")
    assert pdf_bytes.startswith(b"%PDF")
