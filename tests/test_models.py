# tests/test_models.py
import json
from decimal import Decimal

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import (
    Attachment,
    AttachmentKind,
    Base,
    Installation,
    Item,
    Material,
    ProductType,
    Quote,
    QuoteHeader,
    QuoteStatus,
)


def _sqlite_engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine


def test_tables_created():
    engine = _sqlite_engine()
    tables = set(inspect(engine).get_table_names())
    assert tables == {
        "quotes",
        "quote_headers",
        "items",
        "installations",
        "attachments",
        "audit_logs",
        "workers",
        "approval_comments",
        "learned_lessons",
        "geocode_cache",
        "ai_call_logs",
    }


def test_quote_status_has_all_fourteen_states():
    expected = {
        "draft",
        "received",
        "classifying",
        "extracted",
        "awaiting_info",
        "enriched",
        "priced",
        "pending_approval",
        "approved",
        "rejected",
        "needs_manual",
        "changes_requested",
        "scheduled",
        "missed",
    }
    assert {s.value for s in QuoteStatus} == expected


def test_quote_defaults_to_received():
    engine = _sqlite_engine()
    with Session(engine) as session:
        quote = Quote()
        session.add(quote)
        session.commit()
        assert session.query(Quote).one().status == QuoteStatus.received


def test_money_columns_are_numeric_10_2():
    col = Quote.__table__.c.total.type
    assert col.precision == 10
    assert col.scale == 2


def test_attachment_kind_has_all_seven_labels():
    expected = {
        "ar_measure",
        "form_page1",
        "form_continuation",
        "form_installation",
        "hand_sketch",
        "site_photo",
        "other",
    }
    assert {k.value for k in AttachmentKind} == expected


def test_quote_header_item_installation_roundtrip():
    engine = _sqlite_engine()
    with Session(engine) as session:
        quote = Quote(status=QuoteStatus.extracted, total=Decimal("1155.00"))
        quote.header = QuoteHeader(glass="double glazed", wind_rating="unmarked")
        quote.installation = Installation(floor_level="ground", scaffold="unmarked")
        quote.items.append(
            Item(
                item_no=1,
                room="Laundry",
                qty=1,
                description_raw="bi-fold window, aluminium, laundry",
                product_type=ProductType.bi_fold,
                material=Material.aluminium,
                height_mm=1200,
                width_mm=900,
                confidence=0.9,
                config_code="BFW-3",
                field_provenance=json.dumps(
                    {"height_mm": {"value": 1200, "source": "ar_overlay", "confidence": 0.8}}
                ),
            )
        )
        session.add(quote)
        session.commit()

        saved = session.query(Quote).one()
        assert saved.total == Decimal("1155.00")
        assert saved.header.glass == "double glazed"
        assert saved.installation.floor_level == "ground"
        assert saved.items[0].product_type == ProductType.bi_fold
        assert saved.items[0].height_mm == 1200
        assert saved.items[0].config_code == "BFW-3"
        provenance = json.loads(saved.items[0].field_provenance)
        assert provenance["height_mm"]["source"] == "ar_overlay"


def test_awaiting_info_fields_roundtrip():
    engine = _sqlite_engine()
    with Session(engine) as session:
        quote = Quote(
            status=QuoteStatus.awaiting_info,
            awaiting_info_message_id="<clarify-1@select.example.com>",
            awaiting_info_fields=json.dumps(["product_type", "client_name"]),
        )
        session.add(quote)
        session.commit()

        saved = session.query(Quote).one()
        assert saved.status == QuoteStatus.awaiting_info
        assert json.loads(saved.awaiting_info_fields) == ["product_type", "client_name"]


def test_attachment_kind_defaults_to_other():
    engine = _sqlite_engine()
    with Session(engine) as session:
        quote = Quote()
        session.add(quote)
        session.flush()
        session.add(
            Attachment(
                quote_id=quote.id,
                email_message_id="<msg-1@example.com>",
                filename="opening.jpg",
                content_type="image/jpeg",
                storage_path="/tmp/opening.jpg",
            )
        )
        session.commit()

        saved = session.query(Attachment).one()
        assert saved.kind == AttachmentKind.other
