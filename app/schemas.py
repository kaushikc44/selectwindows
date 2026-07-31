# app/schemas.py
from decimal import Decimal
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models import Material, ProductType, QuoteStatus

CONFIDENCE_THRESHOLD = 0.7

YesNoUnmarked = Literal["yes", "no", "unmarked"]

# Shared by the tradie's "Couldn't Complete This Visit" report
# (app/api/worker_quotes.py::report_missed_visit) and Sales's reschedule
# action (app/api/sales_quotes.py::reschedule_job) — one taxonomy, not two.
RescheduleReason = Literal["customer_rescheduled", "tradie_unavailable", "weather", "access_issue", "other"]
RESCHEDULE_REASON_LABELS: dict[str, str] = {
    "customer_rescheduled": "Customer rescheduled",
    "tradie_unavailable": "Tradie unavailable",
    "weather": "Weather",
    "access_issue": "Access issue",
    "other": "Other",
}

# Every tiered field's provenance. "assumed"/"default" mean it wasn't
# extracted from any input at all — those get an asterisk on the quote.
FieldSource = Literal[
    "ar_overlay",
    "form_field",
    "email_body",
    "sketch_annotation",
    "rep_reply",
    "manual_entry",
    "default",
    "assumed",
    "missing",
]

_T = TypeVar("_T")


class FieldValue(BaseModel, Generic[_T]):
    """Wraps any tier-2/3 field with where it came from and how sure we are."""

    value: _T | None = None
    source: FieldSource = "missing"
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class DimensionReading(BaseModel):
    """One raw candidate reading for a height/width, prior to merge. Multiple
    of these (one per input source that mentioned this dimension) feed
    app/engine/merge.py, which applies source precedence and the >15%
    conflict check — readings within tolerance may be averaged there
    (never here), readings beyond it are a genuine conflict, never averaged.

    Upper bound is 20000mm, not 6000 — a single reading never exceeds a
    single window/door, but a *summed* multi-section reading (see
    app/workers/routing.py::_sum_partial_segments, for a wide commercial
    opening split into several sections) legitimately can. Keep in sync with
    ExtractionItem's bounds below and app/engine/pricing.py::MAX_DIM_MM."""

    value_mm: int = Field(ge=100, le=20000)
    source: FieldSource
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    axis_labelled: bool = True  # False when an AR pill couldn't be tied to width vs height


class RevealLining(BaseModel):
    selected: bool = False
    species: Literal["maple", "pine", "unmarked"] = "unmarked"
    defin: Literal["80", "100", "116", "138", "165", "other", "unmarked"] = "unmarked"


class ExtractionHeader(BaseModel):
    """Office-side quote fields. On a LiDAR-photo + email capture almost none
    of this is available, so every field defaults to null/"unmarked" and is
    only filled in when the email text explicitly states it."""

    client_name: str | None = None
    client_address: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    job_no: str | None = None
    rep: str | None = None
    date: str | None = None
    delivery_address: str | None = None
    colour: str | None = None
    glass: str | None = None

    wind_rating: Literal["700", "1000", "1500", "2000", "other", "unmarked"] = "unmarked"
    water_rating: Literal["150", "200", "300", "400", "450", "other", "unmarked"] = "unmarked"
    vent_locks: YesNoUnmarked = "unmarked"
    acoustic_seals: YesNoUnmarked = "unmarked"
    sump_sills: YesNoUnmarked = "unmarked"

    reveal_28: RevealLining = Field(default_factory=RevealLining)
    reveal_45: RevealLining = Field(default_factory=RevealLining)


class ExtractionItem(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    item_no: int
    room: str | None = None
    qty: int = Field(default=1, ge=1)
    description_raw: str
    product_type: ProductType = ProductType.unknown
    material: Material = Material.unknown
    height_mm: int = Field(ge=100, le=20000)  # see DimensionReading above for why not 6000
    width_mm: int = Field(ge=100, le=20000)
    screen: YesNoUnmarked = "unmarked"
    confidence: float = Field(ge=0.0, le=1.0)
    qty_defaulted: bool = False
    config_code: str | None = None
    # True if height_mm and/or width_mm is the MINIMUM of multiple
    # same-precedence readings that disagreed within tolerance (see
    # app/engine/merge.py) rather than a single direct reading — must always
    # be visibly flagged, never silent.
    dimensions_multi_reading: bool = False

    # Raw pre-merge candidates from every source that mentioned this item's
    # dimensions (populated by extract_ar.py / extract_form.py / etc. and
    # consumed by app/engine/merge.py). Empty when there was only ever one
    # source, in which case height_mm/width_mm above are already final.
    height_readings: list[DimensionReading] = Field(default_factory=list)
    width_readings: list[DimensionReading] = Field(default_factory=list)


class ExtractionInstallation(BaseModel):
    building_type: str | None = None
    construction: str | None = None
    remove_existing: str | None = None
    floor_level: str | None = None
    brick_removal_m2: float | None = None
    scaffold: YesNoUnmarked = "unmarked"
    hoist: YesNoUnmarked = "unmarked"
    brick_saw: YesNoUnmarked = "unmarked"
    men_reqd: int | None = None
    time_estimate_hrs: float | None = None
    asbestos: YesNoUnmarked = "unmarked"
    notes: str = ""


class ExtractionResultV2(BaseModel):
    header: ExtractionHeader = Field(default_factory=ExtractionHeader)
    items: list[ExtractionItem] = Field(default_factory=list)
    installation: ExtractionInstallation = Field(default_factory=ExtractionInstallation)
    overall_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    unreadable_fields: list[str] = Field(default_factory=list)

    @property
    def needs_manual(self) -> bool:
        if self.overall_confidence < CONFIDENCE_THRESHOLD:
            return True
        if self.unreadable_fields:
            return True
        return any(item.confidence < CONFIDENCE_THRESHOLD for item in self.items)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    item_no: int
    room: str | None = None
    qty: int
    description_raw: str
    product_type: str
    material: str
    # Optional: null while a worker-app draft item is still awaiting its
    # dimension photos (see app/api/worker_quotes.py) — always set by the
    # time a quote reaches pending_approval.
    height_mm: int | None = None
    width_mm: int | None = None
    screen: str
    confidence: float
    config_code: str | None = None
    size_band: str | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None


class HeaderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    client_name: str | None = None
    client_address: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    job_no: str | None = None
    rep: str | None = None
    date: str | None = None
    colour: str | None = None
    glass: str | None = None
    wind_rating: str | None = None
    water_rating: str | None = None


class InstallationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    building_type: str | None = None
    construction: str | None = None
    remove_existing: str | None = None
    floor_level: str | None = None
    brick_removal_m2: float | None = None
    scaffold: str | None = None
    hoist: str | None = None
    brick_saw: str | None = None
    men_reqd: int | None = None
    time_estimate_hrs: float | None = None
    asbestos: str | None = None
    notes: str | None = None


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: QuoteStatus
    notes: str | None = None
    overall_confidence: float | None = None
    flags: str | None = None  # raw JSON list[{code, message}]
    awaiting_info_fields: str | None = None  # raw JSON list[str]
    header: HeaderOut | None = None
    installation: InstallationOut | None = None
    items: list[ItemOut]
    items_subtotal: Decimal | None = None
    installation_subtotal: Decimal | None = None
    gst_amount: Decimal | None = None
    total: Decimal | None = None


class WorkerTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "tradie"
