# app/models.py
import enum
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class QuoteStatus(str, enum.Enum):
    # Worker app path only: a submission being actively built on-device,
    # before the worker taps "Submit Job". Analogous to "received" for the
    # email path, but items/dimensions are filled in progressively rather
    # than extracted all at once.
    draft = "draft"
    received = "received"
    classifying = "classifying"
    extracted = "extracted"
    awaiting_info = "awaiting_info"
    enriched = "enriched"
    priced = "priced"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    needs_manual = "needs_manual"
    # Owner-app path only: Anthony sent this back via a request_changes
    # comment (see app/api/owner_quotes.py) — the tradie can edit it again
    # (same mutation endpoints as draft) until they resubmit.
    changes_requested = "changes_requested"
    # Sales-app path only (see app/api/sales_quotes.py): a job Sales created
    # and assigned to a tradie for a scheduled site visit, before the
    # tradie has started filling anything in — the tradie-side equivalent
    # of "draft" but originated by Sales, not the tradie.
    scheduled = "scheduled"
    # Tradie reported the scheduled visit didn't happen (see
    # POST /worker/quotes/{id}/missed) — Sales can reschedule it back to
    # `scheduled` via POST /sales/quotes/{id}/reschedule.
    missed = "missed"


class AttachmentKind(str, enum.Enum):
    ar_measure = "ar_measure"
    form_page1 = "form_page1"
    form_continuation = "form_continuation"
    form_installation = "form_installation"
    hand_sketch = "hand_sketch"
    site_photo = "site_photo"
    other = "other"


class ProductType(str, enum.Enum):
    # window_types
    awning = "awning"
    casement = "casement"
    sliding = "sliding"
    double_hung = "double_hung"
    louvre = "louvre"
    powerlouvre = "powerlouvre"
    bi_fold = "bi_fold"
    sashless = "sashless"
    gas_strut = "gas_strut"
    # door_types (sliding/bi_fold already covered above)
    stacking = "stacking"
    hinged = "hinged"
    cedar_entry = "cedar_entry"
    unknown = "unknown"


class Material(str, enum.Enum):
    aluminium = "aluminium"
    timber = "timber"
    unknown = "unknown"


class WorkerRole(str, enum.Enum):
    """An account is exactly one of these, never more than one — role-play
    multiple sides of the workflow by logging into different accounts (see
    scripts/create_worker.py --role)."""

    tradie = "tradie"
    sales = "sales"
    owner = "owner"


def _uuid() -> str:
    return str(uuid.uuid4())


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, name="quote_status"), default=QuoteStatus.received, nullable=False
    )
    source_email_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set for worker-app submissions only (see app/api/worker_quotes.py) —
    # null for the email-intake path, which has no worker accounts. Since
    # Phase F, this is the SALES rep who created the job (not necessarily
    # the tradie doing the work) — see assigned_tradie_id below for that.
    created_by_worker_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"), nullable=True)
    # Sales-app path only: which tradie is responsible for this job's site
    # visit (see app/api/sales_quotes.py). This — not created_by_worker_id
    # — is what gates the tradie's own mutation endpoints in
    # app/api/worker_quotes.py, since Sales creates the job but the
    # assigned tradie is the one who fills it in.
    assigned_tradie_id: Mapped[str | None] = mapped_column(ForeignKey("workers.id"), nullable=True)
    # Stored as "YYYY-MM-DD" text, consistent with every other date-shaped
    # field in this schema (e.g. QuoteHeader.date) — no time-of-day
    # component, deliberately kept simple per the approved Phase F plan.
    scheduled_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The original inbound email body — kept so a later dimension-conflict
    # retry reply can be combined with the original context (product hints
    # etc.) when re-running extraction from scratch.
    original_body_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    overall_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    unreadable_fields: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]
    flags: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[{code, message}]
    # Computed once when the quote first reaches pending_approval (see
    # app/ai/approval_agent.py, called from send_for_approval) — which
    # stored LearnedLesson rows look relevant to this quote, if any. A
    # surfaced note for Anthony, never an auto-action — see the "always
    # surface, Anthony clicks" v1 scoping decision.
    agent_notes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]
    # 0-100, higher = less of Anthony's time needed. A deterministic
    # baseline from app/engine/flags.py::compute_readiness_score, adjusted
    # by whether the learning agent found a matching past lesson — computed
    # alongside agent_notes above, recomputed (flags component only, not
    # re-checked against lessons) whenever Anthony edits the quote — see
    # app/workers/pipeline.py::recompute_pricing_and_flags.
    readiness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # awaiting_info reply-threading: Message-ID of the clarification email we
    # sent the rep, and what we asked for, so an inbound reply can be matched
    # back to this quote and merged rather than starting a new one.
    awaiting_info_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    awaiting_info_fields: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list[str]

    items_subtotal: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    installation_subtotal: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    gst_amount: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)

    approve_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reject_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    header: Mapped["QuoteHeader | None"] = relationship(
        back_populates="quote", cascade="all, delete-orphan", uselist=False
    )
    installation: Mapped["Installation | None"] = relationship(
        back_populates="quote", cascade="all, delete-orphan", uselist=False
    )
    items: Mapped[list["Item"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="Item.item_no"
    )
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    approval_comments: Mapped[list["ApprovalComment"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan", order_by="ApprovalComment.created_at"
    )
    # Read-only convenience for the owner queue (app/api/owner_quotes.py) to
    # show which Sales rep created a job — created_by_worker_id already
    # existed, this just adds the ORM relationship for it.
    created_by_worker: Mapped["Worker | None"] = relationship(foreign_keys=[created_by_worker_id])
    # The tradie assigned to this job's site visit (app/api/sales_quotes.py).
    assigned_tradie: Mapped["Worker | None"] = relationship(foreign_keys=[assigned_tradie_id])


class QuoteHeader(Base):
    """Office-side quote fields. Mostly populated later by office staff —
    an on-site LiDAR-photo + email capture rarely supplies these, so nearly
    everything here is nullable and commonly left "unmarked"."""

    __tablename__ = "quote_headers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False, unique=True)

    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_no: Mapped[str | None] = mapped_column(String(100), nullable=True)
    rep: Mapped[str | None] = mapped_column(String(255), nullable=True)
    date: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    colour: Mapped[str | None] = mapped_column(String(100), nullable=True)
    glass: Mapped[str | None] = mapped_column(String(255), nullable=True)

    wind_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    water_rating: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vent_locks: Mapped[str | None] = mapped_column(String(20), nullable=True)
    acoustic_seals: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sump_sills: Mapped[str | None] = mapped_column(String(20), nullable=True)

    reveal_28_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    reveal_28_species: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reveal_28_defin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reveal_45_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    reveal_45_species: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reveal_45_defin: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # JSON-encoded {field_name: {value, source, confidence}} for fields whose
    # provenance matters (which input supplied them, how confident we are).
    field_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped["Quote"] = relationship(back_populates="header")


class Item(Base):
    """One product unit (a window or door), replacing the old flat glass Panel."""

    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False)

    item_no: Mapped[int] = mapped_column(Integer)
    room: Mapped[str | None] = mapped_column(String(100), nullable=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    description_raw: Mapped[str] = mapped_column(Text)
    product_type: Mapped[ProductType] = mapped_column(
        Enum(ProductType, name="product_type"), default=ProductType.unknown
    )
    material: Mapped[Material] = mapped_column(Enum(Material, name="material"), default=Material.unknown)
    # Nullable: the worker-app path creates an Item before any dimension
    # photo is taken (see app/api/worker_quotes.py) — always non-null by the
    # time pricing runs, guaranteed by the submit endpoint's validation.
    height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    width_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Drives the AS1288 mandatory safety-glass flag for low-sill glazing
    # (see app/engine/flags.py::safety_glass_flags) — a plain fact about the
    # opening, not a resolved AR reading, so no candidate/conflict machinery.
    sill_height_mm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen: Mapped[str] = mapped_column(String(20), default="unmarked")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    config_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    install_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # True if height_mm/width_mm is the MINIMUM of disagreeing same-tier
    # readings (see app/engine/merge.py) rather than a single direct
    # reading — surfaced via multi_reading_dimension_flags, never silent.
    dimensions_multi_reading: Mapped[bool] = mapped_column(Boolean, default=False)

    size_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_price: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    line_total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)

    # JSON-encoded {field_name: {value, source, confidence, candidates?}} —
    # candidates holds every raw reading considered during dimension merge,
    # so the "don't average, don't silently pick" rule stays auditable.
    field_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JSON-encoded tier-3 enrichment result (glass_spec, hardware,
    # frame_components, sealant_and_fixings, notes, source) — computed once
    # in run_enrichment_and_flags and persisted here so the PDF (rendered
    # later, in a separate step) can show the materials list, not just the
    # one-line summary flag.
    enrichment_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped["Quote"] = relationship(back_populates="items")


class Installation(Base):
    """Page-3 installation detail. Nullable throughout — a quick on-site
    LiDAR-photo capture typically won't supply most of this; pricing must
    still work when it's absent."""

    __tablename__ = "installations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False, unique=True)

    building_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    construction: Mapped[str | None] = mapped_column(String(50), nullable=True)
    remove_existing: Mapped[str | None] = mapped_column(String(50), nullable=True)
    floor_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    brick_removal_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    scaffold: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hoist: Mapped[str | None] = mapped_column(String(20), nullable=True)
    brick_saw: Mapped[str | None] = mapped_column(String(20), nullable=True)
    men_reqd: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_estimate_hrs: Mapped[float | None] = mapped_column(Float, nullable=True)
    asbestos: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    field_provenance: Mapped[str | None] = mapped_column(Text, nullable=True)

    quote: Mapped["Quote"] = relationship(back_populates="installation")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)

    # email_message_id is reused (not a real Message-ID) for the worker-app
    # path, which has no email — a synthetic identifier is stored instead so
    # this stays a required, non-null audit field either way.
    email_message_id: Mapped[str] = mapped_column(String(998))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
    kind: Mapped[AttachmentKind] = mapped_column(
        Enum(AttachmentKind, name="attachment_kind"), default=AttachmentKind.other
    )
    # Worker-app path only: which item + which dimension this photo was
    # taken for (the email path has no such link — grouping/axis there is
    # inferred by the vision model instead, see app/workers/routing.py).
    item_id: Mapped[str | None] = mapped_column(ForeignKey("items.id"), nullable=True)
    dimension_field: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "width" | "height"
    received_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    quote: Mapped["Quote"] = relationship(back_populates="attachments")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)

    event: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    quote: Mapped["Quote"] = relationship(back_populates="audit_logs")


class Worker(Base):
    """A field rep with app login access. No self-registration — accounts
    are created by the owner (see scripts/create_worker.py)."""

    __tablename__ = "workers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # An account is exactly one role — see app/auth.py::require_owner /
    # require_sales. Role-play multiple sides of the workflow by logging
    # into different accounts (scripts/create_worker.py --role).
    role: Mapped[WorkerRole] = mapped_column(Enum(WorkerRole, name="worker_role"), default=WorkerRole.tradie)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalComment(Base):
    """The review thread for a worker-app submission: Anthony's comments
    and actions (approve/reject/request_changes) plus the tradie's replies
    when fixing a changes_requested quote. See app/api/owner_quotes.py and
    the resubmit endpoint in app/api/worker_quotes.py."""

    __tablename__ = "approval_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False)

    author: Mapped[str] = mapped_column(String(20))  # "owner" | "tradie"
    body: Mapped[str] = mapped_column(Text)
    # Set for owner comments that also changed the quote's status; null for
    # a plain comment or a tradie's resolution note.
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    quote: Mapped["Quote"] = relationship(back_populates="approval_comments")


class LearnedLesson(Base):
    """A flat, growing memory of Anthony's past request_changes corrections
    — v1's entire "learning" mechanism (see app/ai/approval_agent.py). No
    embeddings or fine-tuning: trigger_summary/fix_summary are stored
    verbatim from his comment text and read as plain-text context by a
    chat_completion call before a new quote reaches his queue."""

    __tablename__ = "learned_lessons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trigger_summary: Mapped[str] = mapped_column(Text)
    fix_summary: Mapped[str] = mapped_column(Text)
    source_comment_id: Mapped[str | None] = mapped_column(ForeignKey("approval_comments.id"), nullable=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
