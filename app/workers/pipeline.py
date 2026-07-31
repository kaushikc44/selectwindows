# app/workers/pipeline.py
import json
import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.approval_agent import check_against_lessons
from app.ai.enrich_materials import generate_material_estimate
from app.ai.extract_email import extract_email_fields
from app.config import settings
from app.engine.enrich import EnrichmentResult, enrich_item, load_defaults
from app.engine.flags import DOOR_PRODUCT_TYPES, Flag, build_flags, compute_readiness_score
from app.engine.pricing import InstallationInput, ItemInput, load_rules, price_quote
from app.engine.product_hint import map_product_hint
from app.models import (
    Attachment,
    Installation,
    Item,
    LearnedLesson,
    Material,
    ProductType,
    Quote,
    QuoteHeader,
    QuoteStatus,
)
from app.output.approval import build_approval_links, send_approval_email
from app.output.missing_info import send_dimension_conflict_retry_request, send_missing_info_request
from app.output.needs_manual_notice import send_needs_manual_notice
from app.output.pdf import generate_quote_pdf
from app.schemas import CONFIDENCE_THRESHOLD, DimensionReading, ExtractionResultV2
from app.workers.persist import create_quote_with_attachments, log_event, set_attachment_kinds
from app.workers.routing import ExtractionOutcome, classify_images, extract_from_attachments

logger = logging.getLogger(__name__)

CRITICAL_TIER2_FIELDS = ["product_type", "client_name"]

# Marker stored in Quote.awaiting_info_fields (in place of a list of missing
# tier-2 field names) when a quote is waiting on a dimension-conflict retry
# rather than a missing product_type/client_name — process_reply_pipeline
# branches on this to rebuild and re-extract instead of merging fields.
DIMENSION_CONFLICT_MARKER = "dimension_conflict"


@dataclass
class _FlagItemView:
    item_no: int
    product_type: str
    height_readings: list[DimensionReading]
    width_readings: list[DimensionReading]
    config_code: str | None = None
    dimensions_multi_reading: bool = False


def _flag_item_views(items: list[Item]) -> list[_FlagItemView]:
    views = []
    for item in items:
        provenance = json.loads(item.field_provenance) if item.field_provenance else {}
        views.append(
            _FlagItemView(
                item_no=item.item_no,
                product_type=item.product_type.value,
                height_readings=[DimensionReading(**r) for r in provenance.get("height_readings", [])],
                width_readings=[DimensionReading(**r) for r in provenance.get("width_readings", [])],
                config_code=item.config_code,
                dimensions_multi_reading=item.dimensions_multi_reading,
            )
        )
    return views


def run_classification(quote: Quote, image_payloads: list[tuple[bytes, str]]) -> list[str]:
    quote.status = QuoteStatus.classifying
    kinds = classify_images(image_payloads)
    set_attachment_kinds(quote, kinds)
    return kinds


def _low_confidence_reason(result: ExtractionResultV2) -> str:
    """Explains exactly which ExtractionResultV2.needs_manual condition
    fired — used to compose the needs_manual notice so the owner sees why a
    quote stalled instead of an unrelated field like installation notes."""
    reasons = []
    if result.overall_confidence < CONFIDENCE_THRESHOLD:
        reasons.append(f"overall confidence {result.overall_confidence:.2f} below {CONFIDENCE_THRESHOLD}")
    if result.unreadable_fields:
        reasons.append(f"unreadable fields: {', '.join(result.unreadable_fields)}")
    for item in result.items:
        if item.confidence < CONFIDENCE_THRESHOLD:
            reasons.append(f"item {item.item_no} confidence {item.confidence:.2f} below {CONFIDENCE_THRESHOLD}")
    return "; ".join(reasons) if reasons else "low_confidence_or_unreadable"


def run_extraction(
    db: Session, quote: Quote, image_payloads: list[tuple[bytes, str]], kinds: list[str], body_text: str
) -> ExtractionOutcome:
    outcome = extract_from_attachments(image_payloads, kinds, body_text)
    log_event(db, quote.id, "extraction", outcome.reason or "ok")

    if outcome.result is None:
        if outcome.reason and outcome.reason.startswith("dimension_conflict_") and outcome.conflict_readings:
            send_dimension_conflict_retry(db, quote, outcome.conflict_readings)
            return outcome
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"extraction failed: {outcome.reason}"
        return outcome

    result = outcome.result
    header = result.header
    quote.header = QuoteHeader(
        client_name=header.client_name,
        client_address=header.client_address,
        contact_name=header.contact_name,
        phone=header.phone,
        email=header.email,
        job_no=header.job_no,
        rep=header.rep,
        date=header.date,
        delivery_address=header.delivery_address,
        colour=header.colour,
        glass=header.glass,
        wind_rating=header.wind_rating,
        water_rating=header.water_rating,
        vent_locks=header.vent_locks,
        acoustic_seals=header.acoustic_seals,
        sump_sills=header.sump_sills,
        reveal_28_selected=header.reveal_28.selected,
        reveal_28_species=header.reveal_28.species,
        reveal_28_defin=header.reveal_28.defin,
        reveal_45_selected=header.reveal_45.selected,
        reveal_45_species=header.reveal_45.species,
        reveal_45_defin=header.reveal_45.defin,
    )

    installation = result.installation
    quote.installation = Installation(
        building_type=installation.building_type,
        construction=installation.construction,
        remove_existing=installation.remove_existing,
        floor_level=installation.floor_level,
        brick_removal_m2=installation.brick_removal_m2,
        scaffold=installation.scaffold,
        hoist=installation.hoist,
        brick_saw=installation.brick_saw,
        men_reqd=installation.men_reqd,
        time_estimate_hrs=installation.time_estimate_hrs,
        asbestos=installation.asbestos,
        notes=installation.notes,
    )

    for item in result.items:
        db.add(
            Item(
                quote_id=quote.id,
                item_no=item.item_no,
                room=item.room,
                qty=item.qty,
                description_raw=item.description_raw,
                product_type=ProductType(item.product_type),
                material=Material(item.material),
                height_mm=item.height_mm,
                width_mm=item.width_mm,
                screen=item.screen,
                confidence=item.confidence,
                config_code=item.config_code,
                dimensions_multi_reading=item.dimensions_multi_reading,
                field_provenance=json.dumps(
                    {
                        "height_readings": [r.model_dump() for r in item.height_readings],
                        "width_readings": [r.model_dump() for r in item.width_readings],
                    }
                ),
            )
        )

    quote.overall_confidence = result.overall_confidence
    quote.unreadable_fields = json.dumps(result.unreadable_fields)
    quote.notes = installation.notes or ""

    if outcome.needs_manual:
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"{quote.notes}\nneeds_manual: {_low_confidence_reason(result)}".strip()
        db.flush()
        return outcome

    db.flush()

    quote.status = QuoteStatus.extracted
    return outcome


def missing_critical_fields(quote: Quote) -> list[str]:
    missing = []
    if not quote.items or all(i.product_type == ProductType.unknown for i in quote.items):
        missing.append("product_type")
    if quote.header is None or not quote.header.client_name:
        missing.append("client_name")
    return missing


def send_awaiting_info(db: Session, quote: Quote, missing_fields: list[str]) -> None:
    message_id = send_missing_info_request(quote, missing_fields)
    quote.awaiting_info_message_id = message_id
    quote.awaiting_info_fields = json.dumps(missing_fields)
    quote.status = QuoteStatus.awaiting_info
    log_event(db, quote.id, "awaiting_info_sent", ",".join(missing_fields))


def send_dimension_conflict_retry(db: Session, quote: Quote, readings: list[DimensionReading]) -> None:
    message_id = send_dimension_conflict_retry_request(quote, readings)
    quote.awaiting_info_message_id = message_id
    quote.awaiting_info_fields = json.dumps([DIMENSION_CONFLICT_MARKER])
    quote.status = QuoteStatus.awaiting_info
    log_event(db, quote.id, "dimension_conflict_retry_sent")


def run_pricing(db: Session, quote: Quote) -> None:
    rules = load_rules(settings.RULES_PATH)

    item_inputs = [
        ItemInput(
            item_no=item.item_no,
            product_type=item.product_type.value,
            material=item.material.value,
            height_mm=item.height_mm,
            width_mm=item.width_mm,
            qty=item.qty,
        )
        for item in quote.items
    ]
    installation_input = None
    if quote.installation is not None:
        installation_input = InstallationInput(
            floor_level=quote.installation.floor_level,
            brick_removal_m2=quote.installation.brick_removal_m2,
            scaffold=quote.installation.scaffold,
            hoist=quote.installation.hoist,
            brick_saw=quote.installation.brick_saw,
        )
    glass_text = quote.header.glass if quote.header is not None else None

    pricing = price_quote(item_inputs, installation_input, glass_text, rules)

    for item_row in quote.items:
        line = pricing.item_lines_by_no.get(item_row.item_no)
        if line is not None:
            item_row.size_band = line.size_band
            item_row.unit_price = line.unit_price
            item_row.line_total = line.line_total

    quote.items_subtotal = pricing.items_subtotal
    quote.installation_subtotal = pricing.installation_subtotal
    quote.gst_amount = pricing.gst_amount
    quote.total = pricing.total
    quote.status = QuoteStatus.priced
    log_event(db, quote.id, "priced")


def _enrich_item_via_llm_or_default(item: Item, defaults: dict) -> EnrichmentResult:
    """Tries the interim LLM material estimate first (product_type is known,
    so DeepSeek can make a plausible guess) — falls back to the deterministic
    YAML lookup unchanged on any failure. safety_glass_required/energy/labour
    stay off the LLM estimate: those are operational/scheduling numbers the
    user asked to keep out of scope for the AI guess, not "materials"."""
    product_type = item.product_type.value
    material = item.material.value
    size_band = item.size_band or "medium"

    estimate = generate_material_estimate(product_type, material, size_band)
    if estimate is None:
        return enrich_item(product_type, material, size_band, defaults)

    fallback = enrich_item(product_type, material, size_band, defaults)
    return EnrichmentResult(
        glass_spec=estimate.glass_spec,
        safety_glass_required=product_type in DOOR_PRODUCT_TYPES,
        hardware=estimate.hardware,
        energy_u_value=None,
        energy_shgc=None,
        labour_hours=fallback.labour_hours,
        men_required=fallback.men_required,
        unrecognized=False,
        source="llm_estimate",
        frame_components=estimate.frame_components,
        sealant_and_fixings=estimate.sealant_and_fixings,
        notes=estimate.notes,
    )


def run_enrichment_and_flags(db: Session, quote: Quote) -> None:
    defaults = load_defaults(settings.DEFAULTS_PATH)
    items_with_enrichment = [
        (item.item_no, _enrich_item_via_llm_or_default(item, defaults)) for item in quote.items
    ]
    for item, (_, enrichment) in zip(quote.items, items_with_enrichment):
        item.enrichment_json = json.dumps(asdict(enrichment))
    sill_height_mm = {item.item_no: item.sill_height_mm for item in quote.items if item.sill_height_mm is not None}
    flags = build_flags(_flag_item_views(quote.items), quote.installation, items_with_enrichment, sill_height_mm)
    quote.flags = json.dumps([{"code": f.code, "message": f.message} for f in flags])
    log_event(db, quote.id, "enriched")


def _enrichment_from_stored_json(item: Item) -> EnrichmentResult:
    """Reconstructs an EnrichmentResult from what's already on the item —
    never calls the LLM. Used by recompute_pricing_and_flags so that
    re-running flags after an owner edit (app/api/owner_quotes.py) can
    never silently overwrite Anthony's own materials correction with a
    fresh AI guess."""
    if not item.enrichment_json:
        return EnrichmentResult(
            glass_spec="",
            safety_glass_required=False,
            hardware=[],
            energy_u_value=None,
            energy_shgc=None,
            labour_hours=0.0,
            men_required=1,
            unrecognized=True,
        )
    return EnrichmentResult(**json.loads(item.enrichment_json))


def recompute_pricing_and_flags(db: Session, quote: Quote) -> None:
    """Refreshes pricing/flags/readiness_score after Anthony edits a quote
    (app/api/owner_quotes.py's edit endpoint) — reuses run_pricing
    unchanged, and rebuilds flags from each item's ALREADY-STORED
    enrichment_json rather than re-running the LLM materials estimate
    (see _enrichment_from_stored_json), so an edit never clobbers a
    manual materials correction. agent_notes (the learning-agent lesson
    match) is intentionally left as-is — that only gets re-checked at
    actual (re)submission, not on every edit — only the deterministic,
    flags-driven component of readiness_score is refreshed here."""
    original_status = quote.status
    run_pricing(db, quote)  # has the side effect of setting status = priced
    quote.status = original_status

    items_with_enrichment = [(item.item_no, _enrichment_from_stored_json(item)) for item in quote.items]
    sill_height_mm = {item.item_no: item.sill_height_mm for item in quote.items if item.sill_height_mm is not None}
    flags = build_flags(_flag_item_views(quote.items), quote.installation, items_with_enrichment, sill_height_mm)
    quote.flags = json.dumps([{"code": f.code, "message": f.message} for f in flags])

    existing_notes = json.loads(quote.agent_notes) if quote.agent_notes else []
    quote.readiness_score = _score_readiness(quote, existing_notes)

    log_event(db, quote.id, "owner_edit_recomputed")


def _notify_if_needs_manual(db: Session, quote: Quote) -> None:
    """Sends one internal notice to the owner whenever a pipeline run ends
    in needs_manual — a rep's submission the system correctly declines to
    auto-resolve should never be silently invisible. A failure here must
    never overwrite the quote's real outcome, only get logged."""
    if quote.status != QuoteStatus.needs_manual:
        return
    try:
        send_needs_manual_notice(quote, quote.notes or "unspecified")
        log_event(db, quote.id, "needs_manual_notice_sent")
    except Exception as exc:  # noqa: BLE001 - a notification failure must not mask the real outcome
        logger.exception("Failed to send needs_manual notice for quote %s", quote.id)
        log_event(db, quote.id, "needs_manual_notice_failed", str(exc))


# Flat penalty applied to the deterministic baseline (compute_readiness_score)
# when the learning agent found a matching past correction — signals a known-
# problem pattern is present, on top of whatever flags already say.
_LESSON_MATCH_PENALTY = 20


def _score_readiness(quote: Quote, notes: list[str]) -> int:
    stored_flags = json.loads(quote.flags) if quote.flags else []
    flags = [Flag(code=f["code"], message=f["message"]) for f in stored_flags]
    baseline = compute_readiness_score(flags)
    return max(0, baseline - (_LESSON_MATCH_PENALTY if notes else 0))


def _run_approval_agent_check(db: Session, quote: Quote) -> None:
    """Computes quote.agent_notes and quote.readiness_score once, right
    before Anthony's queue would show this quote — a failure here must
    never block the approval email, only leave both unset (see
    check_against_lessons' own all-failures-return-[] contract, this is an
    extra outer guard for anything else, e.g. a bad DB query)."""
    try:
        lessons = list(db.scalars(select(LearnedLesson)))
        notes = check_against_lessons(quote, lessons)
        quote.agent_notes = json.dumps(notes)
        quote.readiness_score = _score_readiness(quote, notes)
    except Exception:  # noqa: BLE001 - agent notes are a nice-to-have, never a blocker
        logger.exception("Approval-agent lesson check failed for quote %s", quote.id)


def send_for_approval(db: Session, quote: Quote) -> None:
    approve_url, reject_url, approve_token, reject_token = build_approval_links(quote.id)
    quote.approve_token = approve_token
    quote.reject_token = reject_token

    pdf_bytes = generate_quote_pdf(quote)
    send_approval_email(quote, pdf_bytes, approve_url, reject_url)

    quote.status = QuoteStatus.pending_approval
    log_event(db, quote.id, "approval_email_sent")
    _run_approval_agent_check(db, quote)


def process_worker_submission_pipeline(db: Session, quote: Quote) -> None:
    """Runs the shared back half of the pipeline (pricing → enrichment →
    approval) for a worker-app submission. Unlike process_quote_pipeline,
    there's no extraction step here — the worker-quotes API
    (app/api/worker_quotes.py) already validated every item has resolved
    dimensions before calling this, so it goes straight to pricing."""
    try:
        run_pricing(db, quote)
        run_enrichment_and_flags(db, quote)
        send_for_approval(db, quote)
    except Exception as exc:  # noqa: BLE001 - pipeline must never crash the worker
        logger.exception("Unhandled error processing worker submission %s", quote.id)
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"{quote.notes or ''}\npipeline error: {exc}".strip()
        log_event(db, quote.id, "pipeline_error", str(exc))

    _notify_if_needs_manual(db, quote)


def process_quote_pipeline(
    db: Session,
    *,
    from_address: str,
    email_message_id: str,
    body_text: str,
    images: list,
) -> str:
    quote = create_quote_with_attachments(
        db, from_address=from_address, email_message_id=email_message_id, images=images, body_text=body_text
    )
    try:
        image_payloads: list[tuple[bytes, str]] = []
        for image in images:
            with open(image.storage_path, "rb") as f:
                image_payloads.append((f.read(), image.content_type))

        kinds = run_classification(quote, image_payloads)
        run_extraction(db, quote, image_payloads, kinds, body_text)

        if quote.status not in (QuoteStatus.needs_manual, QuoteStatus.awaiting_info):
            missing = missing_critical_fields(quote)
            if missing:
                send_awaiting_info(db, quote, missing)
            else:
                run_pricing(db, quote)
                run_enrichment_and_flags(db, quote)
                send_for_approval(db, quote)
    except Exception as exc:  # noqa: BLE001 - pipeline must never crash the worker
        logger.exception("Unhandled error processing quote %s", quote.id)
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"{quote.notes or ''}\npipeline error: {exc}".strip()
        log_event(db, quote.id, "pipeline_error", str(exc))

    _notify_if_needs_manual(db, quote)
    return quote.id


def _rebuild_image_payloads(quote: Quote) -> list[tuple[bytes, str]]:
    payloads = []
    for attachment in quote.attachments:
        with open(attachment.storage_path, "rb") as f:
            payloads.append((f.read(), attachment.content_type))
    return payloads


def _process_dimension_conflict_reply(db: Session, quote: Quote, body_text: str, images: list) -> None:
    """A dimension conflict aborts extraction before any item is persisted,
    so there's nothing to merge — this folds any new photo the rep attached
    into the quote's attachments, combines the original email text with the
    rep's correction, and re-runs classification + extraction from scratch
    exactly as if it were a fresh submission."""
    for image in images:
        quote.attachments.append(
            Attachment(
                email_message_id=quote.awaiting_info_message_id or "",
                filename=image.filename,
                content_type=image.content_type,
                storage_path=image.storage_path,
            )
        )
    db.flush()

    image_payloads = _rebuild_image_payloads(quote)
    combined_body_text = "\n".join(t for t in (quote.original_body_text, body_text) if t)

    quote.awaiting_info_message_id = None
    quote.awaiting_info_fields = None
    log_event(db, quote.id, "dimension_conflict_reply_received")

    kinds = run_classification(quote, image_payloads)
    run_extraction(db, quote, image_payloads, kinds, combined_body_text)

    if quote.status not in (QuoteStatus.needs_manual, QuoteStatus.awaiting_info):
        missing = missing_critical_fields(quote)
        if missing:
            send_awaiting_info(db, quote, missing)
        else:
            run_pricing(db, quote)
            run_enrichment_and_flags(db, quote)
            send_for_approval(db, quote)


def process_reply_pipeline(db: Session, quote: Quote, body_text: str, images: list | None = None) -> None:
    """Merges a rep's reply to a missing-info request back into the quote
    and continues the pipeline, or asks again if still incomplete."""
    try:
        missing = json.loads(quote.awaiting_info_fields or "[]")

        if missing == [DIMENSION_CONFLICT_MARKER]:
            _process_dimension_conflict_reply(db, quote, body_text, images or [])
        else:
            email_fields = extract_email_fields(body_text)

            if "client_name" in missing and email_fields["client_name"].value:
                if quote.header is None:
                    quote.header = QuoteHeader()
                quote.header.client_name = email_fields["client_name"].value

            if "product_type" in missing and email_fields["product_hint"].value:
                product_type, material, config_code = map_product_hint(email_fields["product_hint"].value)
                for item in quote.items:
                    if product_type != "unknown" and item.product_type == ProductType.unknown:
                        item.product_type = ProductType(product_type)
                    if material != "unknown" and item.material == Material.unknown:
                        item.material = Material(material)
                    if config_code and not item.config_code:
                        item.config_code = config_code

            log_event(db, quote.id, "rep_reply_merged")

            still_missing = missing_critical_fields(quote)
            if still_missing:
                send_awaiting_info(db, quote, still_missing)
            else:
                quote.status = QuoteStatus.extracted
                quote.awaiting_info_message_id = None
                quote.awaiting_info_fields = None
                run_pricing(db, quote)
                run_enrichment_and_flags(db, quote)
                send_for_approval(db, quote)
    except Exception as exc:  # noqa: BLE001 - pipeline must never crash the worker
        logger.exception("Unhandled error processing reply for quote %s", quote.id)
        quote.status = QuoteStatus.needs_manual
        quote.notes = f"{quote.notes or ''}\nreply pipeline error: {exc}".strip()
        log_event(db, quote.id, "pipeline_error", str(exc))

    _notify_if_needs_manual(db, quote)
