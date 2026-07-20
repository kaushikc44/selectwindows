# app/models.py
import enum
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
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
    extracted = "extracted"
    priced = "priced"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    needs_manual = "needs_manual"


class GlassType(str, enum.Enum):
    toughened = "toughened"
    clear_float = "clear_float"
    laminated = "laminated"
    double_glazed = "double_glazed"
    unknown = "unknown"


def _uuid() -> str:
    return str(uuid.uuid4())


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    status: Mapped[QuoteStatus] = mapped_column(
        Enum(QuoteStatus, name="quote_status"), default=QuoteStatus.extracted, nullable=False
    )
    source_email_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    glass_subtotal: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    hardware_subtotal: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    labour_amount: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    waste_amount: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    gst_amount: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)
    total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)

    approve_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reject_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    token_used: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    panels: Mapped[list["Panel"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    hardware_lines: Mapped[list["HardwareLine"]] = relationship(
        back_populates="quote", cascade="all, delete-orphan"
    )
    attachments: Mapped[list["Attachment"]] = relationship(back_populates="quote", cascade="all, delete-orphan")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="quote", cascade="all, delete-orphan")


class Panel(Base):
    __tablename__ = "panels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False)

    label: Mapped[str] = mapped_column(String(50))
    width_mm: Mapped[int] = mapped_column(Integer)
    height_mm: Mapped[int] = mapped_column(Integer)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    glass_type: Mapped[GlassType] = mapped_column(Enum(GlassType, name="glass_type"))
    confidence: Mapped[float] = mapped_column(default=1.0)
    glass_type_flagged: Mapped[bool] = mapped_column(Boolean, default=False)

    area_m2: Mapped[Numeric | None] = mapped_column(Numeric(10, 3), nullable=True)
    line_total: Mapped[Numeric | None] = mapped_column(Numeric(10, 2), nullable=True)

    quote: Mapped["Quote"] = relationship(back_populates="panels")


class HardwareLine(Base):
    __tablename__ = "hardware_lines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"), nullable=False)

    code: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(255))
    qty: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    line_total: Mapped[Numeric] = mapped_column(Numeric(10, 2))
    estimated: Mapped[bool] = mapped_column(Boolean, default=True)

    quote: Mapped["Quote"] = relationship(back_populates="hardware_lines")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)

    email_message_id: Mapped[str] = mapped_column(String(998), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    storage_path: Mapped[str] = mapped_column(String(500))
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
