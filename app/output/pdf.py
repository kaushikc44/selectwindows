# app/output/pdf.py
from decimal import Decimal

from app.models import HardwareLine, Panel, Quote

ESTIMATED_TAG = "ESTIMATED — review"


def _money(value: Decimal | None) -> str:
    return f"${value:.2f}" if value is not None else "-"


def _panel_row(panel: Panel) -> str:
    flag = " (glass type assumed)" if panel.glass_type_flagged else ""
    return (
        f"<tr><td>{panel.label}</td><td>{panel.width_mm} x {panel.height_mm} mm</td>"
        f"<td>{panel.qty}</td><td>{panel.glass_type.value}{flag}</td>"
        f"<td>{panel.area_m2}</td><td>{_money(panel.line_total)}</td></tr>"
    )


def _hardware_row(line: HardwareLine) -> str:
    tag = f" — <strong>{ESTIMATED_TAG}</strong>" if line.estimated else ""
    return (
        f"<tr><td>{line.code}{tag}</td><td>{line.name}</td><td>{line.qty}</td>"
        f"<td>{_money(line.unit_price)}</td><td>{_money(line.line_total)}</td></tr>"
    )


def _render_html(quote: Quote) -> str:
    panel_rows = "".join(_panel_row(p) for p in quote.panels)
    hardware_rows = "".join(_hardware_row(h) for h in quote.hardware_lines)
    return f"""
    <html><head><style>
        body {{ font-family: sans-serif; font-size: 12px; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 16px; }}
        td, th {{ border: 1px solid #ccc; padding: 4px 8px; text-align: left; }}
        .totals td {{ font-weight: bold; }}
    </style></head><body>
        <h1>Draft Quote {quote.id}</h1>
        <p>Status: {quote.status.value}</p>
        <h2>Panels</h2>
        <table>
            <tr><th>Label</th><th>Size</th><th>Qty</th><th>Glass type</th><th>Area m2</th><th>Line total</th></tr>
            {panel_rows}
        </table>
        <h2>Hardware ({ESTIMATED_TAG} where AI-predicted)</h2>
        <table>
            <tr><th>Code</th><th>Name</th><th>Qty</th><th>Unit price</th><th>Line total</th></tr>
            {hardware_rows}
        </table>
        <h2>Totals</h2>
        <table class="totals">
            <tr><td>Glass subtotal</td><td>{_money(quote.glass_subtotal)}</td></tr>
            <tr><td>Waste</td><td>{_money(quote.waste_amount)}</td></tr>
            <tr><td>Labour</td><td>{_money(quote.labour_amount)}</td></tr>
            <tr><td>Hardware subtotal</td><td>{_money(quote.hardware_subtotal)}</td></tr>
            <tr><td>GST</td><td>{_money(quote.gst_amount)}</td></tr>
            <tr><td>Total</td><td>{_money(quote.total)}</td></tr>
        </table>
        <p>{quote.notes or ""}</p>
    </body></html>
    """


def generate_quote_pdf(quote: Quote) -> bytes:
    from weasyprint import HTML  # imported lazily: needs system Pango/GObject libs

    html = _render_html(quote)
    return HTML(string=html).write_pdf()
