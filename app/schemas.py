# app/schemas.py
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import GlassType, QuoteStatus


class PanelIn(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    label: str
    width_mm: int = Field(ge=100, le=6000)
    height_mm: int = Field(ge=100, le=6000)
    qty: int = Field(ge=1)
    glass_type: GlassType = GlassType.unknown
    confidence: float = Field(ge=0.0, le=1.0)
    glass_type_flagged: bool = False


class ExtractionResult(BaseModel):
    panels: list[PanelIn]
    notes: str = ""

    @property
    def needs_manual(self) -> bool:
        return any(p.confidence < 0.7 for p in self.panels)


class HardwareLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    qty: int
    unit_price: Decimal
    line_total: Decimal
    estimated: bool


class PanelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    label: str
    width_mm: int
    height_mm: int
    qty: int
    glass_type: str
    confidence: float
    glass_type_flagged: bool
    area_m2: Decimal | None = None
    line_total: Decimal | None = None


class QuoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: QuoteStatus
    notes: str | None = None
    panels: list[PanelOut]
    hardware_lines: list[HardwareLineOut]
    glass_subtotal: Decimal | None = None
    hardware_subtotal: Decimal | None = None
    labour_amount: Decimal | None = None
    waste_amount: Decimal | None = None
    gst_amount: Decimal | None = None
    total: Decimal | None = None
