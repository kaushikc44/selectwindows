# app/workers/pipeline.py
import logging

from sqlalchemy.orm import Session

from app.ai.extract import ExtractionOutcome, extract_panels
from app.ai.hardware import load_catalog, predict_hardware
from app.config import settings
from app.engine.pricing import HardwareInput, PanelInput, load_rules, price_quote
from app.models import GlassType, HardwareLine, Panel, Quote, QuoteStatus
from app.output.approval import build_approval_links, send_approval_email
from app.output.pdf import generate_quote_pdf
from app.workers.persist import create_quote_with_attachment, log_event

logger = logging.getLogger(__name__)


def run_extraction(db: Session, quote: Quote, image_bytes: bytes, content_type: str) -> ExtractionOutcome:
    outcome = extract_panels(image_bytes, mime_type=content_type)
    log_event(db, quote.id, "extraction", outcome.reason or "ok")

    if outcome.result is None:
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"extraction failed: {outcome.reason}"
        return outcome

    for p in outcome.result.panels:
        db.add(
            Panel(
                quote_id=quote.id,
                label=p.label,
                width_mm=p.width_mm,
                height_mm=p.height_mm,
                qty=p.qty,
                glass_type=GlassType(p.glass_type),
                confidence=p.confidence,
                glass_type_flagged=p.glass_type_flagged,
            )
        )
    quote.notes = outcome.result.notes
    db.flush()

    if outcome.needs_manual:
        quote.status = QuoteStatus.needs_manual
    return outcome


def run_hardware_prediction(db: Session, quote: Quote, panels) -> list:
    catalog = load_catalog(settings.CATALOG_PATH)
    predicted = predict_hardware(panels, catalog)
    for line in predicted:
        db.add(
            HardwareLine(
                quote_id=quote.id,
                code=line.code,
                name=line.name,
                qty=line.qty,
                unit_price=line.unit_price,
                line_total=line.unit_price * line.qty,
                estimated=True,
            )
        )
    db.flush()
    return predicted


def run_pricing(db: Session, quote: Quote, panels, predicted_hardware) -> None:
    rules = load_rules(settings.RULES_PATH)
    panel_inputs = [
        PanelInput(label=p.label, width_mm=p.width_mm, height_mm=p.height_mm, qty=p.qty, glass_type=p.glass_type)
        for p in panels
    ]
    hardware_inputs = [
        HardwareInput(code=h.code, qty=h.qty, unit_price=h.unit_price) for h in predicted_hardware
    ]
    pricing = price_quote(panel_inputs, hardware_inputs, rules)

    for panel_row, panel_line in zip(quote.panels, pricing.panel_lines):
        panel_row.area_m2 = panel_line.area_m2
        panel_row.line_total = panel_line.line_total
    for hardware_row, total in zip(quote.hardware_lines, pricing.hardware_line_totals):
        hardware_row.line_total = total

    quote.glass_subtotal = pricing.glass_subtotal
    quote.waste_amount = pricing.waste_amount
    quote.labour_amount = pricing.labour_amount
    quote.hardware_subtotal = pricing.hardware_subtotal
    quote.gst_amount = pricing.gst_amount
    quote.total = pricing.total
    quote.status = QuoteStatus.priced
    log_event(db, quote.id, "priced")


def send_for_approval(db: Session, quote: Quote) -> None:
    approve_url, reject_url, approve_token, reject_token = build_approval_links(quote.id)
    quote.approve_token = approve_token
    quote.reject_token = reject_token

    pdf_bytes = generate_quote_pdf(quote)
    send_approval_email(quote, pdf_bytes, approve_url, reject_url)

    quote.status = QuoteStatus.pending_approval
    log_event(db, quote.id, "approval_email_sent")


def process_quote_pipeline(
    db: Session, *, from_address: str, email_message_id: str, storage_path: str, content_type: str, filename: str
) -> str:
    quote = create_quote_with_attachment(
        db,
        from_address=from_address,
        email_message_id=email_message_id,
        storage_path=storage_path,
        content_type=content_type,
        filename=filename,
    )
    try:
        with open(storage_path, "rb") as f:
            image_bytes = f.read()

        outcome = run_extraction(db, quote, image_bytes, content_type)
        if quote.status == QuoteStatus.needs_manual:
            return quote.id

        predicted_hardware = run_hardware_prediction(db, quote, outcome.result.panels)
        run_pricing(db, quote, outcome.result.panels, predicted_hardware)
        send_for_approval(db, quote)
    except Exception as exc:  # noqa: BLE001 - pipeline must never crash the worker
        logger.exception("Unhandled error processing quote %s", quote.id)
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"{quote.notes or ''}\npipeline error: {exc}".strip()
        log_event(db, quote.id, "pipeline_error", str(exc))
    return quote.id
