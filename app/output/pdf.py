# app/output/pdf.py
import html
import json
from decimal import Decimal

from app.models import Installation, Item, Quote, QuoteHeader
from app.render.elevation import render_elevation

PLACEHOLDER_BANNER = "DRAFT — placeholder pricing, not a final customer quote"


def _money(value: Decimal | None) -> str:
    return f"${value:.2f}" if value is not None else "-"


def _text(value: str | None) -> str:
    return html.escape(value) if value else "unmarked"


def _esc(value: str | None) -> str:
    return html.escape(value) if value else ""


def _header_rows(header: QuoteHeader | None) -> str:
    if header is None:
        return "<tr><td colspan='2' class='empty'>No header data captured</td></tr>"
    fields = [
        ("Client", header.client_name),
        ("Address", header.client_address),
        ("Contact", header.contact_name),
        ("Phone", header.phone),
        ("Email", header.email),
        ("Job No", header.job_no),
        ("Rep", header.rep),
        ("Colour", header.colour),
        ("Glass", header.glass),
        ("Wind rating", header.wind_rating),
        ("Water rating", header.water_rating),
    ]
    populated = [(label, value) for label, value in fields if value]
    if not populated:
        return "<tr><td colspan='2' class='empty'>No header fields captured from this submission</td></tr>"
    return "".join(f"<tr><th>{label}</th><td>{_esc(value)}</td></tr>" for label, value in populated)


def _elevation_cell(item: Item) -> str:
    if not item.config_code:
        return "<td class='elev empty'>—</td>"
    svg = render_elevation(item.config_code, item.height_mm, item.width_mm)
    return f"<td class='elev'>{svg}</td>"


def _item_row(item: Item) -> str:
    low_confidence = item.confidence < 0.7
    flag = " <span class='low-conf'>(low confidence)</span>" if low_confidence else ""
    row_class = " class='low-conf-row'" if low_confidence else ""
    config_note = f" <span class='muted'>({_esc(item.config_code)})</span>" if item.config_code else ""
    return (
        f"<tr{row_class}><td class='num'>{item.item_no}</td><td>{_text(item.room)}</td>"
        f"<td>{_esc(item.product_type.value)}{config_note}</td>"
        f"<td>{_esc(item.material.value)}</td>"
        f"<td class='num'>{item.height_mm} &times; {item.width_mm}&nbsp;mm<br><span class='muted'>{_esc(item.size_band) or '-'}</span></td>"
        f"<td class='num'>{item.qty}</td><td class='num'>{_money(item.unit_price)}</td>"
        f"<td class='num'>{_money(item.line_total)}{flag}</td>{_elevation_cell(item)}</tr>"
    )


def _materials_block(item: Item) -> str:
    if not item.enrichment_json:
        return ""
    enrichment = json.loads(item.enrichment_json)
    source = enrichment.get("source", "default")
    glass_spec = enrichment.get("glass_spec")
    hardware = enrichment.get("hardware") or []
    frame_components = enrichment.get("frame_components") or []
    sealant_and_fixings = enrichment.get("sealant_and_fixings") or []
    notes = enrichment.get("notes")

    parts: list[str] = []
    if glass_spec:
        parts.append(f"<div class='mat-row'><span class='mat-k'>Glass</span><span class='mat-v'>{_esc(glass_spec)}</span></div>")
    if frame_components:
        parts.append(
            f"<div class='mat-row'><span class='mat-k'>Frame</span>"
            f"<span class='mat-v'>{_esc(', '.join(frame_components))}</span></div>"
        )
    if hardware:
        parts.append(
            f"<div class='mat-row'><span class='mat-k'>Hardware</span>"
            f"<span class='mat-v'>{_esc(', '.join(hardware))}</span></div>"
        )
    if sealant_and_fixings:
        parts.append(
            f"<div class='mat-row'><span class='mat-k'>Sealant &amp; fixings</span>"
            f"<span class='mat-v'>{_esc(', '.join(sealant_and_fixings))}</span></div>"
        )

    if not parts:
        return ""

    if source == "llm_estimate":
        badge = "<span class='mat-badge mat-badge-ai'>AI estimate — unverified</span>"
    else:
        badge = "<span class='mat-badge mat-badge-default'>Default placeholder</span>"

    note_html = f"<div class='mat-note'>{_esc(notes)}</div>" if notes else ""

    return (
        f"<div class='materials'><div class='materials-head'>"
        f"Item {item.item_no} materials required {badge}</div>{''.join(parts)}{note_html}</div>"
    )


def _flags_section(quote: Quote) -> str:
    if not quote.flags:
        return "<p class='empty'>No flags.</p>"
    flags = json.loads(quote.flags)
    if not flags:
        return "<p class='empty'>No flags.</p>"
    rows = "".join(f"<li><strong>{_esc(f['code'])}</strong> — {_esc(f['message'])}</li>" for f in flags)
    return f"<ul class='flags'>{rows}</ul>"


def _installation_rows(installation: Installation | None) -> str:
    if installation is None:
        return "<tr><td colspan='2' class='empty'>No installation detail captured</td></tr>"
    fields = [
        ("Building type", installation.building_type),
        ("Construction", installation.construction),
        ("Remove existing", installation.remove_existing),
        ("Floor level", installation.floor_level),
        ("Brick removal (m2)", installation.brick_removal_m2),
        ("Scaffold", installation.scaffold),
        ("Asbestos", installation.asbestos),
        ("Notes", installation.notes),
    ]
    populated = [(label, value) for label, value in fields if value]
    if not populated:
        return "<tr><td colspan='2' class='empty'>No installation fields captured from this submission</td></tr>"
    return "".join(f"<tr><th>{label}</th><td>{_esc(str(value))}</td></tr>" for label, value in populated)


def _render_html(quote: Quote) -> str:
    header_rows = _header_rows(quote.header)
    item_rows = "".join(_item_row(i) for i in quote.items)
    materials_blocks = "".join(_materials_block(i) for i in quote.items)
    installation_rows = _installation_rows(quote.installation)
    flags_section = _flags_section(quote)

    return f"""
    <html><head><meta charset="utf-8"><style>
        @page {{ size: A4; margin: 22mm 18mm; }}
        * {{ box-sizing: border-box; }}
        body {{
            font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
            font-size: 10.5px;
            color: #1c232b;
            line-height: 1.45;
        }}
        h1, h2 {{ font-family: Georgia, "Times New Roman", serif; }}
        .letterhead {{
            display: flex; justify-content: space-between; align-items: flex-end;
            border-bottom: 2.5px solid #1c232b; padding-bottom: 10px; margin-bottom: 4px;
        }}
        .letterhead .wordmark {{ font-size: 16px; font-weight: bold; letter-spacing: 0.02em; }}
        .letterhead .wordmark .sub {{ font-family: Helvetica, Arial, sans-serif; font-weight: normal;
            font-size: 8.5px; letter-spacing: 0.08em; text-transform: uppercase; color: #5c6773; }}
        .letterhead .meta {{ text-align: right; font-size: 9px; color: #5c6773; }}
        .letterhead .meta .qid {{ font-family: "Courier New", monospace; font-size: 9px; color: #1c232b; }}
        .status-pill {{
            display: inline-block; margin-top: 3px; padding: 2px 9px; border-radius: 9px;
            font-size: 8px; font-weight: bold; letter-spacing: 0.04em; text-transform: uppercase;
            background: #eef2f5; color: #2f6f7e; border: 1px solid #b9d4d8;
        }}
        .banner {{
            background: #f6e2c4; color: #8a4b0f; border: 1px solid #e0ac5e;
            padding: 6px 12px; font-weight: bold; font-size: 9.5px;
            margin: 10px 0 18px; border-radius: 4px;
        }}
        h2.section {{
            font-size: 10px; font-weight: bold; letter-spacing: 0.08em; text-transform: uppercase;
            color: #5c6773; border-bottom: 1px solid #d8dde1; padding-bottom: 4px;
            margin: 20px 0 8px;
        }}
        table {{ width: 100%; border-collapse: collapse; }}
        .kv-table th {{
            width: 110px; text-align: left; font-weight: normal; color: #5c6773;
            padding: 4px 10px 4px 0; vertical-align: top; font-size: 9.5px;
        }}
        .kv-table td {{ padding: 4px 0; vertical-align: top; }}
        .kv-table tr {{ border-bottom: 1px solid #eef0f2; }}
        .empty {{ color: #909aa3; font-style: italic; }}

        table.items {{ margin-top: 4px; }}
        table.items th {{
            text-align: left; font-size: 8.5px; letter-spacing: 0.04em; text-transform: uppercase;
            color: #5c6773; font-weight: bold; padding: 0 8px 6px 0; border-bottom: 1.5px solid #1c232b;
        }}
        table.items td {{ padding: 8px 8px 8px 0; border-bottom: 1px solid #eef0f2; vertical-align: top; }}
        table.items .num {{ font-variant-numeric: tabular-nums; }}
        table.items td.elev {{ width: 90px; text-align: center; }}
        table.items td.elev svg {{ width: 78px; height: auto; }}
        .muted {{ color: #909aa3; font-size: 9px; }}
        .low-conf {{ color: #b3261e; font-size: 8.5px; font-weight: bold; }}
        tr.low-conf-row {{ background: #fdf3f2; }}

        .materials {{
            border: 1px dashed #b7a7d9; background: #f4f1fa; border-radius: 5px;
            padding: 8px 12px; margin: 6px 0 12px;
        }}
        .materials-head {{ font-size: 9px; font-weight: bold; color: #5f4f9c; margin-bottom: 5px; }}
        .mat-badge {{
            display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 8px;
            font-size: 7.5px; font-weight: bold; letter-spacing: 0.03em; text-transform: uppercase;
        }}
        .mat-badge-ai {{ background: #5f4f9c; color: #fff; }}
        .mat-badge-default {{ background: #d8dde1; color: #3f474e; }}
        .mat-row {{ display: block; font-size: 9px; padding: 1px 0; }}
        .mat-k {{ display: inline-block; width: 90px; color: #5c6773; }}
        .mat-v {{ color: #1c232b; }}
        .mat-note {{ margin-top: 5px; font-size: 8.5px; font-style: italic; color: #6a6275; }}

        ul.flags {{ list-style: none; padding: 0; margin: 4px 0; }}
        ul.flags li {{
            border: 1px solid #e6c37a; background: #fdf6e8; border-radius: 4px;
            padding: 6px 10px; margin-bottom: 6px; font-size: 9.5px;
        }}
        ul.flags li strong {{ color: #8a4b0f; }}

        .totals {{ margin-top: 4px; width: 260px; margin-left: auto; }}
        .totals td {{ padding: 3px 0; font-size: 10px; }}
        .totals td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
        .totals tr.grand td {{ border-top: 2px solid #1c232b; font-weight: bold; font-size: 12px; padding-top: 6px; }}

        .notes {{ margin-top: 18px; padding-top: 8px; border-top: 1px solid #d8dde1;
            font-size: 9px; color: #5c6773; font-style: italic; }}
    </style></head><body>
        <div class="letterhead">
            <div class="wordmark">Select Window Installations<div class="sub">Brookvale, Sydney</div></div>
            <div class="meta">Draft Quote<br><span class="qid">{quote.id}</span>
                <br><span class="status-pill">{_esc(quote.status.value)}</span></div>
        </div>
        <div class="banner">{PLACEHOLDER_BANNER}</div>

        <h2 class="section">Header</h2>
        <table class="kv-table">{header_rows}</table>

        <h2 class="section">Items</h2>
        <table class="items">
            <tr><th>#</th><th>Room</th><th>Product</th><th>Material</th><th>Size</th>
            <th>Qty</th><th>Unit&nbsp;price</th><th>Line&nbsp;total</th><th>Elevation</th></tr>
            {item_rows}
        </table>
        {materials_blocks}

        <h2 class="section">Installation</h2>
        <table class="kv-table">{installation_rows}</table>

        <h2 class="section">Flags</h2>
        {flags_section}

        <h2 class="section">Totals</h2>
        <table class="totals">
            <tr><td>Items subtotal</td><td class="num">{_money(quote.items_subtotal)}</td></tr>
            <tr><td>Installation subtotal</td><td class="num">{_money(quote.installation_subtotal)}</td></tr>
            <tr><td>GST</td><td class="num">{_money(quote.gst_amount)}</td></tr>
            <tr class="grand"><td>Total</td><td class="num">{_money(quote.total)}</td></tr>
        </table>

        <div class="notes">{_esc(quote.notes) or ""}</div>
    </body></html>
    """


def generate_quote_pdf(quote: Quote) -> bytes:
    from weasyprint import HTML  # imported lazily: needs system Pango/GObject libs

    html_str = _render_html(quote)
    return HTML(string=html_str).write_pdf()
