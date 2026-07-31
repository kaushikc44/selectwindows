# app/api/worker_quotes.py
"""Structured, photo-per-field quote submission for the worker app — the
replacement intake path for app/ingest/poller.py's email pipeline. Every
field the worker enters is picked from the same enums/Literals already
used by the pipeline (ProductType, Material, ExtractionHeader,
ExtractionInstallation) rather than free text, and each dimension gets its
own dedicated photo, so the backend is TOLD the axis instead of inferring
it — see app/ai/extract_ar_field.py.

The shared back half of the pipeline (pricing, enrichment, PDF, approval)
is untouched and reused via app/workers/pipeline.py::process_worker_submission_pipeline."""

import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.extract_ar_field import extract_single_reading
from app.auth import get_current_worker
from app.db import get_db
from app.engine.merge import DimensionConflictError, resolve_dimension
from app.models import (
    ApprovalComment,
    Attachment,
    AttachmentKind,
    Installation,
    Item,
    Material,
    ProductType,
    Quote,
    QuoteStatus,
    Worker,
)
from app.render.elevation import render_elevation
from app.schemas import (
    RESCHEDULE_REASON_LABELS,
    DimensionReading,
    ExtractionHeader,
    ExtractionInstallation,
    RescheduleReason,
)
from app.workers.persist import log_event
from app.workers.tasks import process_worker_submission

router = APIRouter(prefix="/worker/quotes", tags=["worker-quotes"])

# Separate from `router` because it's not scoped to a specific quote —
# just a stateless rendering utility the ConfigCodePicker calls as the
# worker taps through the type/panel-count/direction picker, replacing the
# paper form's hand-drawn configuration grid with a live preview.
preview_router = APIRouter(prefix="/worker", tags=["worker-quotes"])

STORAGE_DIR = Path("data/attachments")

# Placeholder dimensions for a shape-only preview, before real measurements
# exist — render_elevation only uses height_mm/width_mm for the printed
# "W x H mm" label, never for the drawn shape itself, so these never affect
# what the worker is actually confirming (the configuration, not the size).
_PREVIEW_HEIGHT_MM = 1200
_PREVIEW_WIDTH_MM = 900


class ElevationPreviewResponse(BaseModel):
    svg: str


@preview_router.get("/elevation-preview", response_model=ElevationPreviewResponse)
def elevation_preview(config_code: str, worker: Worker = Depends(get_current_worker)) -> dict:
    svg = render_elevation(config_code, _PREVIEW_HEIGHT_MM, _PREVIEW_WIDTH_MM)
    return {"svg": svg}


# --- request/response shapes -----------------------------------------------


class PropertyDetailsRequest(BaseModel):
    """The tradie's on-site half of what used to be a single create-draft
    step (Phase F: Sales now creates the bare customer header — see
    app/api/sales_quotes.py — before any of this exists). Reuses
    ExtractionHeader/ExtractionInstallation wholesale for convenience, but
    only the compliance/property fields on `header` are ever applied —
    client_name/address/phone/email/job_no (Sales's fields) are always
    ignored here, even if a caller supplies them, so this can never
    accidentally overwrite what Sales entered."""

    header: ExtractionHeader = Field(default_factory=ExtractionHeader)
    installation: ExtractionInstallation = Field(default_factory=ExtractionInstallation)


class NewItemRequest(BaseModel):
    product_type: ProductType
    material: Material
    room: str | None = None
    qty: int = Field(default=1, ge=1)
    screen: Literal["yes", "no", "unmarked"] = "unmarked"
    config_code: str | None = None
    # Drives the AS1288 mandatory safety-glass flag for low-sill glazing —
    # a plain fact about the opening, entered directly, no photo/resolution.
    sill_height_mm: int | None = None


class NewItemResponse(BaseModel):
    item_id: str
    item_no: int


class PhotoUploadResponse(BaseModel):
    resolved: bool
    value_mm: int | None = None
    multi_reading: bool = False
    # Set only when resolved is False, explaining why — "unreadable" (no
    # relevant pill found in the photo) or "conflict" (disagrees with an
    # earlier reading for this field by more than the tolerance) — the app
    # shows a retake prompt either way.
    reason: Literal["unreadable", "conflict"] | None = None
    conflict_values_mm: list[int] | None = None


class ManualDimensionRequest(BaseModel):
    field: Literal["width", "height"]
    value_mm: int = Field(ge=100, le=20000)


class SubmitResponse(BaseModel):
    quote_id: str
    status: str


class ResubmitRequest(BaseModel):
    note: str | None = None


class MissedVisitRequest(BaseModel):
    reason: RescheduleReason
    other_detail: str | None = None


class ReferencePhotoResponse(BaseModel):
    attachment_id: str
    filename: str


class QuoteSummary(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    created_at: str
    total: str | None = None
    scheduled_date: str | None = None


class ItemSummary(BaseModel):
    item_id: str
    item_no: int
    product_type: str
    material: str
    room: str | None = None
    config_code: str | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    sill_height_mm: int | None = None
    line_total: str | None = None


class QuoteFlag(BaseModel):
    code: str
    message: str


class CommentOut(BaseModel):
    id: str
    author: str
    body: str
    action: str | None = None
    created_at: str


class QuoteDetail(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    total: str | None = None
    scheduled_date: str | None = None
    flags: list[QuoteFlag] = Field(default_factory=list)
    items: list[ItemSummary]
    # Anthony's review thread (app/api/owner_quotes.py) — populated once a
    # quote has been through at least one review round; empty for a fresh
    # draft.
    comments: list[CommentOut] = Field(default_factory=list)


# --- helpers -----------------------------------------------------------------


def _get_owned_quote(quote_id: str, worker: Worker, db: Session) -> Quote:
    """No status restriction — for read-only access to any of the tradie's
    own quotes, draft or already submitted. Mutation endpoints use
    _get_owned_draft_quote below instead, which additionally requires
    draft status. Scoped to assigned_tradie_id (Phase F: jobs are created
    by Sales and assigned to a tradie) — not created_by_worker_id, which
    now records the Sales rep who created the job, not the tradie doing
    the work."""
    quote = db.get(Quote, quote_id)
    if quote is None or quote.assigned_tradie_id != worker.id:
        raise HTTPException(status_code=404, detail="quote not found")
    return quote


def _get_owned_draft_quote(quote_id: str, worker: Worker, db: Session) -> Quote:
    quote = _get_owned_quote(quote_id, worker, db)
    if quote.status != QuoteStatus.draft:
        raise HTTPException(status_code=409, detail=f"quote is in status {quote.status.value}, not draft")
    return quote


def _get_owned_editable_quote(quote_id: str, worker: Worker, db: Session) -> Quote:
    """draft/scheduled (still being filled in on-site) or a
    changes_requested quote the tradie is fixing after an owner review
    comment (see app/api/owner_quotes.py) — all mutable states.
    submit_quote/resubmit_quote each still separately require their own
    specific starting status."""
    quote = _get_owned_quote(quote_id, worker, db)
    if quote.status not in (QuoteStatus.draft, QuoteStatus.scheduled, QuoteStatus.changes_requested):
        raise HTTPException(status_code=409, detail=f"quote is in status {quote.status.value}, not editable")
    return quote


def _submission_problems(quote: Quote) -> list[str]:
    problems = []
    if quote.header is None or not quote.header.client_name:
        problems.append("client name is required")
    if not quote.items:
        problems.append("at least one item is required")
    for item in quote.items:
        if item.height_mm is None or item.width_mm is None:
            problems.append(f"item {item.item_no} is missing a resolved width and/or height")
    return problems


def _get_owned_item(quote: Quote, item_id: str, db: Session) -> Item:
    item = db.get(Item, item_id)
    if item is None or item.quote_id != quote.id:
        raise HTTPException(status_code=404, detail="item not found")
    return item


def _save_photo(upload: UploadFile, content: bytes) -> Path:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    original_name = upload.filename or "photo.jpg"
    unique_name = f"{uuid.uuid4().hex}_{Path(original_name).name}"
    path = STORAGE_DIR / unique_name
    path.write_bytes(content)
    return path


# --- endpoints -----------------------------------------------------------------


@router.post("/{quote_id}/property-details", response_model=SubmitResponse)
def set_property_details(
    quote_id: str,
    body: PropertyDetailsRequest,
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    """The tradie's on-site completion of a Sales-created job (Phase F) —
    fills in the compliance/property fields (colour, glass, ratings, reveal
    linings) and installation detail that Sales didn't supply, then moves a
    freshly `scheduled` quote into `draft` so the rest of the flow
    (add_item/submit/etc.) proceeds exactly as it did before Sales existed.
    Deliberately never touches header.client_name/address/phone/email/
    job_no/rep/date/delivery_address — those are Sales's fields, set once
    at creation (see app/api/sales_quotes.py) and never overwritten here."""
    quote = _get_owned_editable_quote(quote_id, worker, db)
    if quote.header is None:
        raise HTTPException(status_code=500, detail="quote has no header — cannot set property details")

    header = body.header
    quote.header.colour = header.colour
    quote.header.glass = header.glass
    quote.header.wind_rating = header.wind_rating
    quote.header.water_rating = header.water_rating
    quote.header.vent_locks = header.vent_locks
    quote.header.acoustic_seals = header.acoustic_seals
    quote.header.sump_sills = header.sump_sills
    quote.header.reveal_28_selected = header.reveal_28.selected
    quote.header.reveal_28_species = header.reveal_28.species
    quote.header.reveal_28_defin = header.reveal_28.defin
    quote.header.reveal_45_selected = header.reveal_45.selected
    quote.header.reveal_45_species = header.reveal_45.species
    quote.header.reveal_45_defin = header.reveal_45.defin

    installation = body.installation
    # Mutate in place rather than reassigning to a new Installation() —
    # reassigning a one-to-one relationship to a brand-new row while an old
    # one still exists doesn't guarantee delete-before-insert ordering
    # within the same flush, and hits installations.quote_id's UNIQUE
    # constraint if this endpoint is ever called twice on the same quote
    # (e.g. the tradie re-opens Property Details before moving on).
    if quote.installation is None:
        quote.installation = Installation(quote_id=quote.id)
    quote.installation.building_type = installation.building_type
    quote.installation.construction = installation.construction
    quote.installation.remove_existing = installation.remove_existing
    quote.installation.floor_level = installation.floor_level
    quote.installation.brick_removal_m2 = installation.brick_removal_m2
    quote.installation.scaffold = installation.scaffold
    quote.installation.hoist = installation.hoist
    quote.installation.brick_saw = installation.brick_saw
    quote.installation.men_reqd = installation.men_reqd
    quote.installation.time_estimate_hrs = installation.time_estimate_hrs
    quote.installation.asbestos = installation.asbestos
    quote.installation.notes = installation.notes

    if quote.status == QuoteStatus.scheduled:
        quote.status = QuoteStatus.draft

    log_event(db, quote.id, "worker_property_details_set", worker.id)
    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value}


@router.post("/{quote_id}/missed", response_model=SubmitResponse)
def report_missed_visit(
    quote_id: str,
    body: MissedVisitRequest,
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    """The tradie's "Couldn't Complete This Visit" action — the other half
    of the Phase F scheduling loop, alongside
    app/api/sales_quotes.py::reschedule_job. Only valid from `scheduled`
    (a job already being worked on has, by definition, not been missed)."""
    quote = _get_owned_quote(quote_id, worker, db)
    if quote.status != QuoteStatus.scheduled:
        raise HTTPException(
            status_code=409, detail=f"quote is in status {quote.status.value}, not scheduled"
        )

    reason_text = RESCHEDULE_REASON_LABELS[body.reason]
    if body.reason == "other" and body.other_detail:
        reason_text = f"{reason_text}: {body.other_detail}"

    quote.status = QuoteStatus.missed
    db.add(ApprovalComment(quote_id=quote.id, author="tradie", body=reason_text, action="missed_visit"))
    log_event(db, quote.id, "worker_reported_missed_visit", body.reason)
    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value}


@router.post("/{quote_id}/items", response_model=NewItemResponse)
def add_item(
    quote_id: str,
    body: NewItemRequest,
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_owned_editable_quote(quote_id, worker, db)

    item_no = len(quote.items) + 1
    item = Item(
        quote_id=quote.id,
        item_no=item_no,
        room=body.room,
        qty=body.qty,
        description_raw=f"{body.material.value} {body.product_type.value.replace('_', ' ')}"
        + (f", {body.room}" if body.room else ""),
        product_type=body.product_type,
        material=body.material,
        screen=body.screen,
        config_code=body.config_code,
        sill_height_mm=body.sill_height_mm,
        confidence=1.0,  # structured picker entry, not a guess — refined once dimensions resolve
    )
    db.add(item)
    log_event(db, quote.id, "worker_item_added", f"item {item_no}")
    db.commit()
    return {"item_id": item.id, "item_no": item_no}


@router.post("/{quote_id}/items/{item_id}/photos", response_model=PhotoUploadResponse)
def upload_dimension_photo(
    quote_id: str,
    item_id: str,
    field: Literal["width", "height"] = Form(...),
    photo: UploadFile = File(...),
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_owned_editable_quote(quote_id, worker, db)
    item = _get_owned_item(quote, item_id, db)

    content = photo.file.read()
    path = _save_photo(photo, content)
    db.add(
        Attachment(
            quote_id=quote.id,
            item_id=item.id,
            dimension_field=field,
            email_message_id=f"app:{quote.id}:{item.id}:{field}",
            filename=path.name,
            content_type=photo.content_type or "image/jpeg",
            storage_path=str(path),
        )
    )

    reading = extract_single_reading(content, photo.content_type or "image/jpeg", field)
    if reading is None:
        db.commit()
        return {"resolved": False, "reason": "unreadable"}

    result = _add_reading_and_resolve(
        item, field, DimensionReading(value_mm=reading.value_mm, source="ar_overlay", confidence=reading.confidence)
    )
    db.commit()
    return result


@router.post("/{quote_id}/items/{item_id}/dimensions", response_model=PhotoUploadResponse)
def enter_dimension_manually(
    quote_id: str,
    item_id: str,
    body: ManualDimensionRequest,
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    """Typed-in alternative to upload_dimension_photo — same candidate/merge
    machinery, just skipping the photo/extraction step. source="manual_entry"
    ranks above ar_overlay in app/engine/merge.py's SOURCE_PRECEDENCE (a
    deliberate typed measurement outranks an AR estimate), and never carries
    the AR ±20mm site-check flag (app/engine/flags.py::ar_measurement_flags
    only flags an ar_overlay reading)."""
    quote = _get_owned_editable_quote(quote_id, worker, db)
    item = _get_owned_item(quote, item_id, db)

    result = _add_reading_and_resolve(
        item, body.field, DimensionReading(value_mm=body.value_mm, source="manual_entry", confidence=1.0)
    )
    db.commit()
    return result


@router.post("/{quote_id}/items/{item_id}/reference-photos", response_model=ReferencePhotoResponse)
def upload_reference_photo(
    quote_id: str,
    item_id: str,
    photo: UploadFile = File(...),
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    """General "+ Add Photo" capture for an opening — context/condition
    photos, not a measurement. No extraction runs on these; unlike
    upload_dimension_photo, a worker can attach as many as they like."""
    quote = _get_owned_editable_quote(quote_id, worker, db)
    item = _get_owned_item(quote, item_id, db)

    content = photo.file.read()
    path = _save_photo(photo, content)
    attachment = Attachment(
        quote_id=quote.id,
        item_id=item.id,
        kind=AttachmentKind.site_photo,
        email_message_id=f"app:{quote.id}:{item.id}:reference",
        filename=path.name,
        content_type=photo.content_type or "image/jpeg",
        storage_path=str(path),
    )
    db.add(attachment)
    db.commit()
    return {"attachment_id": attachment.id, "filename": attachment.filename}


@router.get("/{quote_id}/items/{item_id}/reference-photos", response_model=list[ReferencePhotoResponse])
def list_reference_photos(
    quote_id: str, item_id: str, worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)
) -> list[dict]:
    quote = _get_owned_quote(quote_id, worker, db)
    item = _get_owned_item(quote, item_id, db)
    photos = db.scalars(
        select(Attachment)
        .where(Attachment.item_id == item.id, Attachment.kind == AttachmentKind.site_photo)
        .order_by(Attachment.received_at)
    )
    return [{"attachment_id": p.id, "filename": p.filename} for p in photos]


@router.post("/{quote_id}/submit", response_model=SubmitResponse)
def submit_quote(
    quote_id: str, worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)
) -> dict:
    quote = _get_owned_draft_quote(quote_id, worker, db)

    problems = _submission_problems(quote)
    if problems:
        raise HTTPException(status_code=422, detail=problems)

    quote.status = QuoteStatus.extracted
    log_event(db, quote.id, "worker_submitted", worker.id)
    db.commit()

    process_worker_submission.delay(quote.id)
    return {"quote_id": quote.id, "status": quote.status.value}


@router.post("/{quote_id}/resubmit", response_model=SubmitResponse)
def resubmit_quote(
    quote_id: str,
    body: ResubmitRequest,
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    """The other half of the owner review loop (app/api/owner_quotes.py):
    after Anthony sends a quote back with request_changes, the tradie fixes
    it (add_item/upload_dimension_photo/etc. now accept changes_requested
    via _get_owned_editable_quote) and calls this to send it back to his
    queue. Re-runs the same pricing/enrichment/approval pipeline as the
    original submit, since something about the quote may have changed."""
    quote = _get_owned_quote(quote_id, worker, db)
    if quote.status != QuoteStatus.changes_requested:
        raise HTTPException(
            status_code=409, detail=f"quote is in status {quote.status.value}, not changes_requested"
        )

    problems = _submission_problems(quote)
    if problems:
        raise HTTPException(status_code=422, detail=problems)

    if body.note:
        db.add(ApprovalComment(quote_id=quote.id, author="tradie", body=body.note))

    quote.status = QuoteStatus.extracted
    log_event(db, quote.id, "worker_resubmitted", worker.id)
    db.commit()

    process_worker_submission.delay(quote.id)
    return {"quote_id": quote.id, "status": quote.status.value}


@router.get("", response_model=list[QuoteSummary])
def list_my_quotes(worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)) -> list[dict]:
    """The tradie's own job history (any status) — for the app's Job List
    screen. Deliberately scoped to assigned_tradie_id (Phase F: jobs are
    created by Sales and assigned to a tradie — see
    app/api/sales_quotes.py): unlike the public GET /quotes/{id} (used for
    approve/reject-link access, no ownership concept there), this must
    never leak another tradie's jobs."""
    quotes = db.scalars(
        select(Quote).where(Quote.assigned_tradie_id == worker.id).order_by(Quote.created_at.desc())
    )
    return [
        {
            "quote_id": q.id,
            "status": q.status.value,
            "client_name": q.header.client_name if q.header else None,
            "created_at": q.created_at.isoformat(),
            "total": str(q.total) if q.total is not None else None,
            "scheduled_date": q.scheduled_date,
        }
        for q in quotes
    ]


@router.get("/{quote_id}", response_model=QuoteDetail)
def get_my_quote(
    quote_id: str, worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)
) -> dict:
    """Full detail for one of the worker's own quotes, including items with
    their current dimension state — lets the app resume a half-finished
    draft after a restart instead of only living in DraftContext memory."""
    quote = _get_owned_quote(quote_id, worker, db)
    return {
        "quote_id": quote.id,
        "status": quote.status.value,
        "client_name": quote.header.client_name if quote.header else None,
        "total": str(quote.total) if quote.total is not None else None,
        "scheduled_date": quote.scheduled_date,
        "flags": json.loads(quote.flags) if quote.flags else [],
        "items": [
            {
                "item_id": item.id,
                "item_no": item.item_no,
                "product_type": item.product_type.value,
                "material": item.material.value,
                "room": item.room,
                "config_code": item.config_code,
                "width_mm": item.width_mm,
                "height_mm": item.height_mm,
                "sill_height_mm": item.sill_height_mm,
                "line_total": str(item.line_total) if item.line_total is not None else None,
            }
            for item in quote.items
        ],
        "comments": [
            {
                "id": c.id,
                "author": c.author,
                "body": c.body,
                "action": c.action,
                "created_at": c.created_at.isoformat(),
            }
            for c in quote.approval_comments
        ],
    }


@preview_router.get("/attachments/{attachment_id}")
def get_attachment(
    attachment_id: str, worker: Worker = Depends(get_current_worker), db: Session = Depends(get_db)
) -> FileResponse:
    """Streams a stored photo back to the app — dimension photos and
    reference/site photos alike. Ownership is checked via the attachment's
    parent quote (not the item directly), matching _get_owned_quote's
    any-status read-access rule so thumbnails work post-submission too."""
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.quote is None or attachment.quote.assigned_tradie_id != worker.id:
        raise HTTPException(status_code=404, detail="attachment not found")

    path = Path(attachment.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="attachment file missing")

    return FileResponse(path, media_type=attachment.content_type, filename=attachment.filename)


# --- per-item dimension-reading storage (reuses Item.field_provenance,
# the same JSON column the email pipeline uses for audit/merge candidates) --


def _existing_readings(item: Item, field: Literal["width", "height"]) -> list[DimensionReading]:
    provenance = json.loads(item.field_provenance) if item.field_provenance else {}
    key = f"{field}_readings"
    return [DimensionReading(**r) for r in provenance.get(key, [])]


def _store_readings(item: Item, field: Literal["width", "height"], readings: list[DimensionReading]) -> None:
    provenance = json.loads(item.field_provenance) if item.field_provenance else {}
    provenance[f"{field}_readings"] = [r.model_dump() for r in readings]
    item.field_provenance = json.dumps(provenance)


def _add_reading_and_resolve(item: Item, field: Literal["width", "height"], new_reading: DimensionReading) -> dict:
    """Shared by upload_dimension_photo and enter_dimension_manually: append
    the new candidate, resolve, and update the item — the only difference
    between a photo-sourced and typed-in reading is which DimensionReading
    gets built before calling this. Caller still owns the db.commit()."""
    candidates = _existing_readings(item, field)
    candidates.append(new_reading)
    _store_readings(item, field, candidates)

    try:
        resolved = resolve_dimension(candidates)
    except DimensionConflictError as exc:
        # A later retake/entry can turn a previously-resolved axis into a
        # conflict — clear the stale resolved value so the item's stored
        # state always matches its true current status, never a leftover
        # value from before the conflict arose.
        if field == "width":
            item.width_mm = None
        else:
            item.height_mm = None
        return {
            "resolved": False,
            "reason": "conflict",
            "conflict_values_mm": [r.value_mm for r in exc.readings],
        }

    if field == "width":
        item.width_mm = resolved.value_mm
    else:
        item.height_mm = resolved.value_mm
    item.dimensions_multi_reading = item.dimensions_multi_reading or resolved.multi_reading

    if item.width_mm is not None and item.height_mm is not None:
        all_readings = _existing_readings(item, "width") + _existing_readings(item, "height")
        confidences = [r.confidence for r in all_readings if r.confidence is not None]
        item.confidence = sum(confidences) / len(confidences) if confidences else 1.0

    return {"resolved": True, "value_mm": resolved.value_mm, "multi_reading": resolved.multi_reading}
