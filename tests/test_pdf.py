# tests/test_pdf.py
import json
from decimal import Decimal

import pytest

from app.models import Installation, Item, Material, ProductType, Quote, QuoteHeader, QuoteStatus
from app.output.pdf import PLACEHOLDER_BANNER, _render_html, generate_quote_pdf


def _sample_quote() -> Quote:
    quote = Quote(
        id="quote-1",
        status=QuoteStatus.pending_approval,
        items_subtotal=Decimal("900.00"),
        installation_subtotal=Decimal("150.00"),
        gst_amount=Decimal("105.00"),
        total=Decimal("1155.00"),
        flags=json.dumps([{"code": "asbestos", "message": "SELECT WILL NOT REMOVE"}]),
    )
    quote.header = QuoteHeader(glass="double glazed")
    quote.items.append(
        Item(
            item_no=1,
            room="Laundry",
            qty=1,
            description_raw="bi-fold window, aluminium, laundry",
            product_type=ProductType.bi_fold,
            material=Material.aluminium,
            height_mm=1200,
            width_mm=900,
            confidence=0.9,
            size_band="medium",
            unit_price=Decimal("900.00"),
            line_total=Decimal("900.00"),
            config_code="BFW-3",
        )
    )
    quote.installation = Installation(floor_level="ground")
    return quote


def test_html_contains_placeholder_banner():
    html = _render_html(_sample_quote())
    assert PLACEHOLDER_BANNER in html


def test_html_contains_item_and_totals():
    html = _render_html(_sample_quote())
    assert "bi_fold" in html
    assert "Laundry" in html
    assert "$1155.00" in html
    assert "$105.00" in html


def test_low_confidence_item_flagged_in_row():
    quote = _sample_quote()
    quote.items[0].confidence = 0.4
    html = _render_html(quote)
    row = next(line for line in html.splitlines() if "bi_fold" in line)
    assert "low confidence" in row


def test_html_embeds_elevation_svg_when_config_code_present():
    html = _render_html(_sample_quote())
    assert "<svg" in html


def test_html_has_no_svg_when_config_code_absent():
    quote = _sample_quote()
    quote.items[0].config_code = None
    html = _render_html(quote)
    assert "<svg" not in html


def test_html_contains_flags_section():
    html = _render_html(_sample_quote())
    assert "SELECT WILL NOT REMOVE" in html


def test_html_shows_no_flags_message_when_flags_empty():
    quote = _sample_quote()
    quote.flags = None
    html = _render_html(quote)
    assert "No flags." in html


def test_missing_header_and_installation_render_placeholder_text():
    quote = _sample_quote()
    quote.header = None
    quote.installation = None
    html = _render_html(quote)
    assert "No header data captured" in html
    assert "No installation detail captured" in html


def test_generate_quote_pdf_produces_pdf_bytes():
    try:
        pdf_bytes = generate_quote_pdf(_sample_quote())
    except OSError:
        pytest.skip("WeasyPrint system libraries (Pango/GObject) not installed in this environment")
    assert pdf_bytes.startswith(b"%PDF")


def test_materials_block_absent_when_no_enrichment_persisted():
    html_out = _render_html(_sample_quote())
    assert "materials required" not in html_out.lower()


def test_materials_block_shows_ai_estimate_badge_and_contents():
    quote = _sample_quote()
    quote.items[0].enrichment_json = json.dumps(
        {
            "glass_spec": "6mm single toughened",
            "frame_components": ["aluminium frame extrusion"],
            "hardware": ["multi-point lock", "hinges"],
            "sealant_and_fixings": ["silicone sealant"],
            "notes": "interim estimate only",
            "source": "llm_estimate",
        }
    )
    html_out = _render_html(quote)
    assert "materials required" in html_out.lower()
    assert "AI estimate" in html_out
    assert "6mm single toughened" in html_out
    assert "multi-point lock" in html_out
    assert "silicone sealant" in html_out
    assert "interim estimate only" in html_out


def test_materials_block_shows_default_placeholder_badge():
    quote = _sample_quote()
    quote.items[0].enrichment_json = json.dumps(
        {
            "glass_spec": "single",
            "frame_components": [],
            "hardware": ["multi-point lock"],
            "sealant_and_fixings": [],
            "notes": None,
            "source": "default",
        }
    )
    html_out = _render_html(quote)
    assert "Default placeholder" in html_out
    assert "AI estimate" not in html_out


def test_client_name_with_html_is_escaped_not_injected():
    quote = _sample_quote()
    quote.header.client_name = "<script>alert(1)</script> O'Brien & Sons"
    html_out = _render_html(quote)
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "&amp;" in html_out
