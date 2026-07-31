# app/workers/routing.py
"""Classifies each attachment and routes it to the right extractor, then
builds one unified ExtractionResultV2 regardless of which input types were
present. Form-page images (if any) are authoritative and used as-is
(extract_form.py already stamps their dimensions as form_field). Otherwise,
every AR/sketch photo plus the email body text go into one grouped vision
call (extract_ar.py::extract_grouped_readings) that does the room/item
grouping itself — a large opening often needs several photos to capture
every edge (one item, several photos), while a visually distinct opening or
a differently-named room is a separate item. Unit conversion and dimension
conflict detection stay deterministic, scoped per item."""

import logging

from app.ai.extract_ar import extract_grouped_readings
from app.ai.extract_email import extract_email_fields
from app.ai.extract_form import ExtractionOutcome, extract_form
from app.ai.classify import classify_attachment
from app.engine.merge import DimensionConflictError, resolve_dimension
from app.engine.product_hint import map_product_hint
from app.engine.site_conditions import detect_asbestos_mention
from app.engine.units import UnknownUnitError, normalize_to_mm
from app.schemas import DimensionReading, ExtractionHeader, ExtractionInstallation, ExtractionItem, ExtractionResultV2

logger = logging.getLogger(__name__)

FORM_KINDS = {"form_page1", "form_continuation", "form_installation"}
NON_FORM_KINDS = {"ar_measure", "hand_sketch"}


def classify_images(image_payloads: list[tuple[bytes, str]]) -> list[str]:
    return [classify_attachment(image_bytes, mime_type) for image_bytes, mime_type in image_payloads]


class DimensionConflict(Exception):
    def __init__(self, item_index: int, axis: str, readings: list[DimensionReading]):
        self.item_index = item_index
        self.axis = axis
        self.readings = readings
        super().__init__(f"item {item_index} {axis} readings conflict: {readings}")


def _sum_partial_segments(full_readings: list[DimensionReading], partial_readings: list[DimensionReading]) -> list[DimensionReading]:
    """Partial readings are sections of one wider span (e.g. a sliding door
    opening split into a glazed section + a solid infill panel) — they get
    added together deterministically (never by the LLM) into one synthesized
    reading representing the item's true total for that axis, rather than
    being checked for equality against each other like duplicate full
    readings are."""
    if not partial_readings:
        return full_readings
    total_mm = sum(r.value_mm for r in partial_readings)
    confidence = min(r.confidence for r in partial_readings)
    summed = DimensionReading(value_mm=total_mm, source=partial_readings[0].source, confidence=confidence)
    return full_readings + [summed]


def _bucket_readings(pills, source: str) -> tuple[list[DimensionReading], list[DimensionReading]]:
    width_full, height_full, unlabelled_full = [], [], []
    width_partial, height_partial = [], []

    for pill in pills:
        try:
            value_mm = normalize_to_mm(pill.raw_value, pill.raw_unit)
        except UnknownUnitError:
            logger.warning("Reading has unrecognized unit %r, skipping", pill.raw_unit)
            continue
        reading = DimensionReading(value_mm=value_mm, source=source, confidence=pill.confidence)

        if pill.segment == "partial" and pill.axis in ("width", "height"):
            (width_partial if pill.axis == "width" else height_partial).append(reading)
        else:
            # Unlabelled partial readings are too ambiguous to safely sum
            # into either axis — fall through to the full/unlabelled path.
            (width_full if pill.axis == "width" else height_full if pill.axis == "height" else unlabelled_full).append(
                reading
            )

    # Fallback convention when axis is ambiguous: first unlabelled fills
    # width if empty, next fills height if empty. Best-effort, documented
    # limitation — the mandatory AR-measurement flag always fires regardless.
    for reading in unlabelled_full:
        if not width_full:
            width_full.append(reading)
        elif not height_full:
            height_full.append(reading)

    width = _sum_partial_segments(width_full, width_partial)
    height = _sum_partial_segments(height_full, height_partial)
    return width, height


def _add_email_dimension_candidate(candidates: list[DimensionReading], field) -> None:
    """Appends a typed email-body dimension (e.g. "Width: 2400 mm") as a
    low-precedence candidate alongside photo-derived readings. Only called
    for single-item submissions — with several items a shared body-text
    dimension can't be safely attributed to one of them."""
    if field.source == "missing":
        return
    try:
        value_mm = normalize_to_mm(field.value.raw_value, field.value.raw_unit)
    except UnknownUnitError:
        logger.warning("Email-body dimension has unrecognized unit %r, skipping", field.value.raw_unit)
        return
    candidates.append(DimensionReading(value_mm=value_mm, source="email_body", confidence=field.confidence))


def _build_item(
    item_no: int, group, body_text: str, is_single_item: bool, email_fields: dict | None = None
) -> ExtractionItem | None:
    """Runs one grouped-extraction item through the deterministic
    dimension-merge + product-mapping pipeline. Returns None if the item has
    no resolvable width/height. Raises DimensionConflict if that item's own
    readings disagree by more than the merge threshold — this never
    considers readings from a different item, so two genuinely distinct
    openings can no longer spuriously conflict with each other."""
    width_candidates, height_candidates = _bucket_readings(group.readings, group.source_kind)

    if is_single_item and email_fields is not None:
        _add_email_dimension_candidate(width_candidates, email_fields["width"])
        _add_email_dimension_candidate(height_candidates, email_fields["height"])

    try:
        resolved_width = resolve_dimension(width_candidates)
        resolved_height = resolve_dimension(height_candidates)
    except DimensionConflictError as exc:
        axis = "width" if exc.readings is width_candidates else "height"
        raise DimensionConflict(item_no, axis, exc.readings) from exc

    if resolved_width is None or resolved_height is None:
        return None

    # Search across every source that could name this item's product_type,
    # material, or config_code — product_type_hint, the physical-appearance
    # description, and (single-item submissions only) the whole email body —
    # rather than picking just the first non-empty one. A description almost
    # always exists, so an either/or chain would let it permanently shadow
    # body-text details like material ("Aluminium Sliding Door") that the
    # description itself never mentions. With several items, the body text
    # might name a different item's product entirely, so it's excluded there.
    hint_parts = [p for p in (group.product_type_hint, group.description) if p]
    if is_single_item and body_text:
        hint_parts.append(body_text)
    hint_source = " ".join(hint_parts) if hint_parts else None
    product_type, material, config_code = map_product_hint(hint_source)
    confidences = [c.confidence for c in width_candidates + height_candidates if c.confidence is not None]
    confidence = sum(confidences) / len(confidences) if confidences else 0.5

    return ExtractionItem(
        item_no=item_no,
        room=group.room,
        qty=1,
        description_raw=group.description or "(no product description given)",
        product_type=product_type,
        material=material,
        height_mm=resolved_height.value_mm,
        width_mm=resolved_width.value_mm,
        confidence=confidence,
        config_code=config_code,
        dimensions_multi_reading=resolved_width.multi_reading or resolved_height.multi_reading,
        height_readings=height_candidates,
        width_readings=width_candidates,
    )


def build_items_from_grouped_result(
    grouped_items: list, body_text: str
) -> ExtractionResultV2 | None:
    """Returns None if no item had enough data (tier-1 core requirement
    unmet for every group). Raises DimensionConflict — and aborts the whole
    extraction, same as a single-item conflict always has — on the first
    item whose own readings disagree by more than the merge threshold; the
    error correctly names which item triggered it rather than misattributing
    it to a different, unrelated item's readings."""
    is_single_item = len(grouped_items) == 1
    email_fields = extract_email_fields(body_text)
    items = []
    for item_no, group in enumerate(grouped_items, start=1):
        item = _build_item(item_no, group, body_text, is_single_item, email_fields)
        if item is not None:
            items.append(item)

    if not items:
        return None

    asbestos = "yes" if detect_asbestos_mention(email_fields["site_notes"].value) else "unmarked"
    overall_confidence = sum(i.confidence for i in items) / len(items)

    return ExtractionResultV2(
        header=ExtractionHeader(client_name=email_fields["client_name"].value),
        items=items,
        installation=ExtractionInstallation(asbestos=asbestos, notes=email_fields["site_notes"].value or ""),
        overall_confidence=overall_confidence,
    )


def extract_from_attachments(
    image_payloads: list[tuple[bytes, str]], kinds: list[str], body_text: str
) -> ExtractionOutcome:
    form_images = [img for img, kind in zip(image_payloads, kinds) if kind in FORM_KINDS]
    if form_images:
        return extract_form(form_images, body_text)

    non_form_images = [img for img, kind in zip(image_payloads, kinds) if kind in NON_FORM_KINDS]
    grouped = extract_grouped_readings(non_form_images, body_text)

    try:
        result = build_items_from_grouped_result(grouped.items, body_text)
    except DimensionConflict as exc:
        logger.warning("Dimension conflict on item %s %s: %s", exc.item_index, exc.axis, exc.readings)
        return ExtractionOutcome(
            result=None,
            needs_manual=True,
            reason=f"dimension_conflict_item_{exc.item_index}_{exc.axis}",
            conflict_readings=exc.readings,
        )

    if result is None:
        return ExtractionOutcome(result=None, needs_manual=True, reason="insufficient_dimension_data")
    if result.needs_manual:
        return ExtractionOutcome(result=result, needs_manual=True, reason="low_confidence_or_unreadable")
    return ExtractionOutcome(result=result, needs_manual=False)
