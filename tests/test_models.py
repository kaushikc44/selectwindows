# tests/test_models.py
from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Base, GlassType, HardwareLine, Panel, Quote, QuoteStatus


def _sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine


def test_five_tables_created():
    engine = _sqlite_engine()
    tables = set(inspect(engine).get_table_names())
    assert tables == {"quotes", "panels", "hardware_lines", "attachments", "audit_logs"}


def test_quote_status_has_all_six_states():
    expected = {
        "extracted",
        "priced",
        "pending_approval",
        "approved",
        "rejected",
        "needs_manual",
    }
    assert {s.value for s in QuoteStatus} == expected


def test_money_columns_are_numeric_10_2():
    col = Quote.__table__.c.total.type
    assert col.precision == 10
    assert col.scale == 2


def test_quote_panel_hardware_roundtrip():
    engine = _sqlite_engine()
    with Session(engine) as session:
        quote = Quote(status=QuoteStatus.extracted, total=Decimal("123.45"))
        panel = Panel(
            label="W1",
            width_mm=1200,
            height_mm=900,
            qty=1,
            glass_type=GlassType.toughened,
            confidence=0.95,
        )
        hardware = HardwareLine(
            code="SIL-01",
            name="Silicone tube",
            qty=2,
            unit_price=Decimal("8.50"),
            line_total=Decimal("17.00"),
            estimated=True,
        )
        quote.panels.append(panel)
        quote.hardware_lines.append(hardware)
        session.add(quote)
        session.commit()

        saved = session.query(Quote).one()
        assert saved.total == Decimal("123.45")
        assert saved.panels[0].width_mm == 1200
        assert saved.hardware_lines[0].estimated is True
