# app/api/owner_quotes.py
"""Anthony's review queue — the comment/approve/reject/request_changes loop
that replaces the old single-click email approve/reject links for worker-app
submissions. See app/ai/approval_agent.py for how a request_changes comment
becomes a LearnedLesson the agent checks future quotes against, and
app/api/worker_quotes.py::resubmit_quote for the tradie's side of the loop
once a quote comes back changes_requested."""

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.worker_quotes import CommentOut, QuoteFlag
from app.auth import require_owner
from app.config import settings
from app.db import get_db
from app.geocode import geocode_address, normalise_address
from app.models import ApprovalComment, GeocodeCache, Installation, Item, LearnedLesson, Material, ProductType, Quote, QuoteStatus, Worker
from app.schemas import ExtractionHeader, ExtractionInstallation
from app.workers.persist import log_event
from app.workers.pipeline import recompute_pricing_and_flags

router = APIRouter(prefix="/owner/quotes", tags=["owner-quotes"])

# Anthony's full queue+history — not scoped to one tradie, unlike
# app/api/worker_quotes.py's list_my_quotes. draft/extracted/awaiting_info/
# enriched/priced are deliberately excluded: those are transient states
# before a quote reaches him, nothing to review yet.
_QUEUE_STATUSES = (
    QuoteStatus.pending_approval,
    QuoteStatus.needs_manual,
    QuoteStatus.changes_requested,
    QuoteStatus.approved,
    QuoteStatus.rejected,
)

# Only a quote actively awaiting his decision can be approved/rejected/sent
# back — one already changes_requested/approved/rejected needs the tradie
# (or nothing) to act next, not another decision from Anthony.
_ACTIONABLE_STATUSES = (QuoteStatus.pending_approval, QuoteStatus.needs_manual)

# An auto-approved quote sits in `approved` without Anthony ever clicking
# Approve. He can still undo that — reject it, or send it back to the tradie.
# Those two actions (not approve, which would be a pointless no-op) are
# permitted on an approved quote so a score-based auto-approval is always
# reversible. See app/workers/pipeline.py::_auto_approve.
_REOPENABLE_STATUSES = (QuoteStatus.approved,)
_REOPEN_ACTIONS = ("reject", "request_changes")


class OwnerQuoteSummary(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    created_at: str
    total: str | None = None
    tradie_name: str | None = None
    # 0-100, higher = less of Anthony's time needed — see
    # app/engine/flags.py::compute_readiness_score. None until the quote
    # has gone through send_for_approval at least once.
    readiness_score: int | None = None


class OwnerHeader(BaseModel):
    client_address: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    job_no: str | None = None
    rep: str | None = None
    delivery_address: str | None = None
    colour: str | None = None
    glass: str | None = None
    wind_rating: str | None = None
    water_rating: str | None = None
    vent_locks: str | None = None
    acoustic_seals: str | None = None
    sump_sills: str | None = None


class OwnerInstallation(BaseModel):
    building_type: str | None = None
    construction: str | None = None
    floor_level: str | None = None
    remove_existing: str | None = None
    brick_removal_m2: float | None = None
    scaffold: str | None = None
    hoist: str | None = None
    brick_saw: str | None = None
    asbestos: str | None = None
    notes: str | None = None


class OwnerItemSummary(BaseModel):
    item_id: str
    item_no: int
    product_type: str
    material: str
    room: str | None = None
    config_code: str | None = None
    width_mm: int | None = None
    height_mm: int | None = None
    sill_height_mm: int | None = None
    qty: int
    unit_price: str | None = None
    line_total: str | None = None
    # From Item.enrichment_json (app/engine/enrich.py / app/ai/enrich_materials.py)
    # — the same materials breakdown already in the approval PDF
    # (app/output/pdf.py::_materials_block), just surfaced in-app too.
    glass_spec: str | None = None
    hardware: list[str] = Field(default_factory=list)
    frame_components: list[str] = Field(default_factory=list)
    sealant_and_fixings: list[str] = Field(default_factory=list)
    enrichment_notes: str | None = None


class OwnerQuoteDetail(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    header: OwnerHeader
    installation: OwnerInstallation
    items_subtotal: str | None = None
    installation_subtotal: str | None = None
    gst_amount: str | None = None
    total: str | None = None
    flags: list[QuoteFlag] = Field(default_factory=list)
    # The agent's matched-lesson notes (app/ai/approval_agent.py) — a
    # surfaced hint, never an auto-action. Empty until a quote has gone
    # through send_for_approval at least once.
    agent_notes: list[str] = Field(default_factory=list)
    items: list[OwnerItemSummary]
    comments: list[CommentOut] = Field(default_factory=list)
    tradie_name: str | None = None
    readiness_score: int | None = None


class CommentRequest(BaseModel):
    body: str
    action: Literal["comment", "approve", "reject", "request_changes"] = "comment"


class CommentResponse(BaseModel):
    quote_id: str
    status: str


class OwnerItemEdit(BaseModel):
    # None = a brand-new item Anthony is adding; set = editing (or, with
    # delete=True, removing) an existing one.
    item_id: str | None = None
    delete: bool = False

    product_type: ProductType = ProductType.unknown
    material: Material = Material.unknown
    room: str | None = None
    config_code: str | None = None
    qty: int = Field(default=1, ge=1)
    width_mm: int | None = None
    height_mm: int | None = None
    sill_height_mm: int | None = None

    # Overrides Item.enrichment_json directly — see
    # app/engine/enrich.py::EnrichmentResult, stored with source="owner_edit"
    # so app/engine/flags.py::default_enrichment_flags knows this is a
    # human-verified spec, not an unreviewed AI estimate or placeholder.
    glass_spec: str = ""
    hardware: list[str] = Field(default_factory=list)
    frame_components: list[str] = Field(default_factory=list)
    sealant_and_fixings: list[str] = Field(default_factory=list)
    enrichment_notes: str | None = None


class EditQuoteRequest(BaseModel):
    header: ExtractionHeader = Field(default_factory=ExtractionHeader)
    installation: ExtractionInstallation = Field(default_factory=ExtractionInstallation)
    items: list[OwnerItemEdit] = Field(default_factory=list)


def _tradie_name(quote: Quote) -> str | None:
    """Since Phase F, assigned_tradie_id is the correct "which tradie
    handled this" field for jobs created via app/api/sales_quotes.py.
    Falls back to created_by_worker for quotes from before that existed —
    the tradie-app-only path (Phases D/E) set created_by_worker_id to the
    tradie themselves, with no separate assignment step."""
    if quote.assigned_tradie is not None:
        return quote.assigned_tradie.name
    if quote.created_by_worker is not None:
        return quote.created_by_worker.name
    return None


def _get_queue_quote(quote_id: str, db: Session) -> Quote:
    quote = db.get(Quote, quote_id)
    if quote is None or quote.status not in _QUEUE_STATUSES:
        raise HTTPException(status_code=404, detail="quote not found")
    return quote


def _item_to_owner_summary(item: Item) -> dict:
    enrichment = json.loads(item.enrichment_json) if item.enrichment_json else {}
    return {
        "item_id": item.id,
        "item_no": item.item_no,
        "product_type": item.product_type.value,
        "material": item.material.value,
        "room": item.room,
        "config_code": item.config_code,
        "width_mm": item.width_mm,
        "height_mm": item.height_mm,
        "sill_height_mm": item.sill_height_mm,
        "qty": item.qty,
        "unit_price": str(item.unit_price) if item.unit_price is not None else None,
        "line_total": str(item.line_total) if item.line_total is not None else None,
        "glass_spec": enrichment.get("glass_spec"),
        "hardware": enrichment.get("hardware") or [],
        "frame_components": enrichment.get("frame_components") or [],
        "sealant_and_fixings": enrichment.get("sealant_and_fixings") or [],
        "enrichment_notes": enrichment.get("notes"),
    }


def _quote_to_detail(quote: Quote) -> dict:
    header = quote.header
    installation = quote.installation
    return {
        "quote_id": quote.id,
        "status": quote.status.value,
        "client_name": header.client_name if header else None,
        "header": {
            "client_address": header.client_address if header else None,
            "contact_name": header.contact_name if header else None,
            "phone": header.phone if header else None,
            "email": header.email if header else None,
            "job_no": header.job_no if header else None,
            "rep": header.rep if header else None,
            "delivery_address": header.delivery_address if header else None,
            "colour": header.colour if header else None,
            "glass": header.glass if header else None,
            "wind_rating": header.wind_rating if header else None,
            "water_rating": header.water_rating if header else None,
            "vent_locks": header.vent_locks if header else None,
            "acoustic_seals": header.acoustic_seals if header else None,
            "sump_sills": header.sump_sills if header else None,
        },
        "installation": {
            "building_type": installation.building_type if installation else None,
            "construction": installation.construction if installation else None,
            "floor_level": installation.floor_level if installation else None,
            "remove_existing": installation.remove_existing if installation else None,
            "brick_removal_m2": installation.brick_removal_m2 if installation else None,
            "scaffold": installation.scaffold if installation else None,
            "hoist": installation.hoist if installation else None,
            "brick_saw": installation.brick_saw if installation else None,
            "asbestos": installation.asbestos if installation else None,
            "notes": installation.notes if installation else None,
        },
        "items_subtotal": str(quote.items_subtotal) if quote.items_subtotal is not None else None,
        "installation_subtotal": str(quote.installation_subtotal) if quote.installation_subtotal is not None else None,
        "gst_amount": str(quote.gst_amount) if quote.gst_amount is not None else None,
        "total": str(quote.total) if quote.total is not None else None,
        "flags": json.loads(quote.flags) if quote.flags else [],
        "agent_notes": json.loads(quote.agent_notes) if quote.agent_notes else [],
        "items": [_item_to_owner_summary(item) for item in quote.items],
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
        "tradie_name": _tradie_name(quote),
        "readiness_score": quote.readiness_score,
    }


@router.get("", response_model=list[OwnerQuoteSummary])
def list_owner_queue(owner: Worker = Depends(require_owner), db: Session = Depends(get_db)) -> list[dict]:
    quotes = db.scalars(select(Quote).where(Quote.status.in_(_QUEUE_STATUSES)).order_by(Quote.created_at.desc()))
    return [
        {
            "quote_id": q.id,
            "status": q.status.value,
            "client_name": q.header.client_name if q.header else None,
            "created_at": q.created_at.isoformat(),
            "total": str(q.total) if q.total is not None else None,
            "tradie_name": _tradie_name(q),
            "readiness_score": q.readiness_score,
        }
        for q in quotes
    ]


# ---------------------------------------------------------------------------
# Anthony's job map (maps branch)
#
# A geocoded view of his in-flight work — every job that's either waiting on
# his decision or already moving through the field, pinpointed on a map of
# NSW by the house address entered on the quote. Only the owner role can
# reach this endpoint (require_owner), so only Anthony sees where his jobs
# are. See app/geocode.py for the Nominatim lookup + NSW bounding box, and
# app/models.py::GeocodeCache for why re-opens don't re-geocode. Declared
# BEFORE the /{quote_id} route so FastAPI matches the literal "/map" path
# first instead of treating "map" as a quote_id.
# ---------------------------------------------------------------------------

# Statuses that have a physical job location Anthony would act on. The
# review-queue endpoint above (_QUEUE_STATUSES) deliberately excludes the
# early transient states; this map is broader — it also includes
# scheduled/missed, because a site visit Sales booked (app/api/sales_quotes.py)
# is "ongoing work" Anthony wants to see even before it reaches him for
# pricing. rejected is excluded: the job is dead, not ongoing.
_MAP_STATUSES = (
    QuoteStatus.pending_approval,  # needs Anthony's approval — "pending"
    QuoteStatus.needs_manual,  # needs Anthony's approval — "pending"
    QuoteStatus.changes_requested,  # back with the tradie — "ongoing"
    QuoteStatus.approved,  # being built — "ongoing"
    QuoteStatus.scheduled,  # site visit booked — "ongoing"
    QuoteStatus.missed,  # visit didn't happen, awaiting reschedule — "ongoing"
)

# "pending" = Anthony still owes a decision; "ongoing" = already past his
# desk (or never on it — scheduled/missed). The mobile map colours pins by
# this category so he can spot what needs his attention at a glance.
_PENDING_STATUSES = frozenset({QuoteStatus.pending_approval, QuoteStatus.needs_manual})


class OwnerMapPin(BaseModel):
    quote_id: str
    status: str
    category: Literal["pending", "ongoing"]
    client_name: str | None = None
    address: str | None = None
    lat: float
    lng: float
    total: str | None = None
    scheduled_date: str | None = None
    tradie_name: str | None = None
    readiness_score: int | None = None


class OwnerMapResponse(BaseModel):
    pins: list[OwnerMapPin]
    # Jobs in-scope that couldn't be pinpointed — either no address on the
    # quote, or the address couldn't be geocoded to a NSW point. Surfaced as
    # a count so Anthony knows the map isn't the whole picture.
    unmapped: int


def _map_address(quote: Quote) -> str:
    """The house location to pinpoint — prefer the property/install address
    (client_address), fall back to the delivery address. Normalised for the
    geocode cache key by app/geocode.py::normalise_address upstream."""
    header = quote.header
    if header is None:
        return ""
    return normalise_address(header.client_address) or normalise_address(header.delivery_address)


@router.get("/map", response_model=OwnerMapResponse)
def get_owner_map(owner: Worker = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    """Geocoded pins for Anthony's in-flight NSW jobs — only the owner role
    can call this, so only he sees job locations. Resolves each quote's
    house address to a lat/lng (cache-first, then Nominatim capped at
    GEOCODE_MAX_LOOKUPS_PER_REQUEST live lookups so Nominatim's 1 req/s policy
    holds). Quotes with no address or an unresolvable one are counted in
    `unmapped` rather than dropped silently."""
    quotes = db.scalars(
        select(Quote).where(Quote.status.in_(_MAP_STATUSES)).order_by(Quote.created_at.desc())
    ).all()

    # Cache lookup is one indexed query per address — collect them in one
    # SELECT instead so a full map open isn't N queries.
    addresses = [addr for addr in (_map_address(q) for q in quotes) if addr]
    cache_rows: dict[str, GeocodeCache] = {}
    if addresses:
        for row in db.scalars(select(GeocodeCache).where(GeocodeCache.address.in_(addresses))):
            cache_rows[row.address] = row

    fresh_budget = settings.GEOCODE_MAX_LOOKUPS_PER_REQUEST
    pins: list[dict] = []
    unmapped = 0

    for quote in quotes:
        address = _map_address(quote)
        if not address:
            unmapped += 1
            continue

        row = cache_rows.get(address)
        if row is None:
            # No cache entry yet — geocode live if the per-request budget
            # allows, otherwise leave it for a later pass and count unmapped.
            if fresh_budget <= 0:
                unmapped += 1
                continue
            fresh_budget -= 1
            coords = geocode_address(address)
            row = GeocodeCache(address=address, resolved=coords is not None)
            if coords is not None:
                row.lat, row.lng = coords
            db.add(row)
            cache_rows[address] = row

        if not row.resolved or row.lat is None or row.lng is None:
            unmapped += 1
            continue

        pins.append(
            {
                "quote_id": quote.id,
                "status": quote.status.value,
                "category": "pending" if quote.status in _PENDING_STATUSES else "ongoing",
                "client_name": quote.header.client_name if quote.header else None,
                "address": address,
                "lat": row.lat,
                "lng": row.lng,
                "total": str(quote.total) if quote.total is not None else None,
                "scheduled_date": quote.scheduled_date,
                "tradie_name": _tradie_name(quote),
                "readiness_score": quote.readiness_score,
            }
        )

    db.commit()
    return {"pins": pins, "unmapped": unmapped}


@router.get("/{quote_id}", response_model=OwnerQuoteDetail)
def get_owner_quote(quote_id: str, owner: Worker = Depends(require_owner), db: Session = Depends(get_db)) -> dict:
    quote = _get_queue_quote(quote_id, db)
    return _quote_to_detail(quote)


@router.post("/{quote_id}/comments", response_model=CommentResponse)
def post_comment(
    quote_id: str,
    body: CommentRequest,
    owner: Worker = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_queue_quote(quote_id, db)

    if body.action != "comment":
        # Approve/reject/request_changes need a quote awaiting a decision. The
        # exception is undoing an auto-approval: reject/request_changes are
        # also allowed on an already-approved quote (but approve is not — it
        # would be a no-op on an approved quote).
        if quote.status not in _ACTIONABLE_STATUSES and not (
            quote.status in _REOPENABLE_STATUSES and body.action in _REOPEN_ACTIONS
        ):
            raise HTTPException(
                status_code=409,
                detail=f"quote is in status {quote.status.value}, not awaiting a decision",
            )

    comment = ApprovalComment(
        quote_id=quote.id,
        author="owner",
        body=body.body,
        action=None if body.action == "comment" else body.action,
    )
    db.add(comment)

    if body.action == "approve":
        quote.status = QuoteStatus.approved
    elif body.action == "reject":
        quote.status = QuoteStatus.rejected
    elif body.action == "request_changes":
        quote.status = QuoteStatus.changes_requested
        db.flush()  # comment.id must exist before LearnedLesson references it
        db.add(
            LearnedLesson(
                trigger_summary=f"A quote like this one: {_quote_text_summary(quote)}",
                fix_summary=body.body,
                source_comment_id=comment.id,
            )
        )

    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value}


@router.post("/{quote_id}/edit", response_model=OwnerQuoteDetail)
def edit_quote(
    quote_id: str,
    body: EditQuoteRequest,
    owner: Worker = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """Anthony can change anything on a quote while it's still his to
    decide on — header, installation, and every item field, including
    adding/removing items outright. `body.items` is expected to be the
    COMPLETE current item list every time (matching this codebase's
    existing whole-object-resubmission pattern, e.g.
    app/api/worker_quotes.py::set_property_details) — mark an item
    `delete: true` to remove it rather than omitting it. Re-runs pricing
    and rebuilds flags/readiness_score afterward (see
    app/workers/pipeline.py::recompute_pricing_and_flags) but never
    re-runs the materials LLM estimate, so a manual materials correction
    here is never silently overwritten."""
    quote = _get_queue_quote(quote_id, db)
    if quote.status not in _ACTIONABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"quote is in status {quote.status.value}, not awaiting a decision",
        )
    if quote.header is None:
        raise HTTPException(status_code=500, detail="quote has no header")

    header = body.header
    quote.header.client_name = header.client_name
    quote.header.client_address = header.client_address
    quote.header.contact_name = header.contact_name
    quote.header.phone = header.phone
    quote.header.email = header.email
    quote.header.job_no = header.job_no
    quote.header.rep = header.rep
    quote.header.date = header.date
    quote.header.delivery_address = header.delivery_address
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

    existing_items = {item.id: item for item in quote.items}
    kept_items: list[Item] = []
    for item_edit in body.items:
        if item_edit.item_id is not None:
            item = existing_items.get(item_edit.item_id)
            if item is None:
                raise HTTPException(status_code=404, detail=f"item {item_edit.item_id} not found on this quote")
            if item_edit.delete:
                db.delete(item)
                continue
        else:
            item = Item(quote_id=quote.id, item_no=0)  # renumbered below
            db.add(item)

        item.product_type = item_edit.product_type
        item.material = item_edit.material
        item.room = item_edit.room
        item.config_code = item_edit.config_code
        item.qty = item_edit.qty
        item.width_mm = item_edit.width_mm
        item.height_mm = item_edit.height_mm
        item.sill_height_mm = item_edit.sill_height_mm
        item.description_raw = f"{item_edit.material.value} {item_edit.product_type.value.replace('_', ' ')}" + (
            f", {item_edit.room}" if item_edit.room else ""
        )
        item.enrichment_json = json.dumps(
            {
                "glass_spec": item_edit.glass_spec,
                "safety_glass_required": False,  # write-only field, never read by pricing/flags — see Phase G plan
                "hardware": item_edit.hardware,
                "energy_u_value": None,
                "energy_shgc": None,
                "labour_hours": 0.0,
                "men_required": 1,
                "unrecognized": False,
                "source": "owner_edit",
                "frame_components": item_edit.frame_components,
                "sealant_and_fixings": item_edit.sealant_and_fixings,
                "notes": item_edit.enrichment_notes,
            }
        )
        kept_items.append(item)

    db.flush()
    for i, item in enumerate(kept_items, start=1):
        item.item_no = i

    db.add(ApprovalComment(quote_id=quote.id, author="owner", body="Anthony edited this quote.", action="edit"))

    recompute_pricing_and_flags(db, quote)
    log_event(db, quote.id, "owner_quote_edited", owner.id)
    db.commit()
    db.refresh(quote)
    return _quote_to_detail(quote)


def _quote_text_summary(quote: Quote) -> str:
    """A short, honest description of what the quote looked like when
    Anthony flagged it — v1's "trigger" half of a LearnedLesson is just
    this plus his own comment text (the fix), not an LLM-restructured
    abstraction. See app/ai/approval_agent.py for how this gets read back."""
    parts = [f"{item.product_type.value} ({item.material.value})" for item in quote.items]
    return ", ".join(parts) if parts else "a quote with no items"
