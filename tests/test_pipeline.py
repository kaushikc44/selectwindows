# tests/test_pipeline.py
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import extract, hardware
from app.models import Base, Quote, QuoteStatus
from app.workers.pipeline import process_quote_pipeline

FIXTURE_JSON = (Path(__file__).parent / "fixtures" / "extraction_valid.json").read_text()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def fixture_image(tmp_path):
    path = tmp_path / "w1.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fakejpegbytes")
    return path


def test_full_chain_reaches_pending_approval_with_correct_gst(monkeypatch, db_session, fixture_image):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=FIXTURE_JSON))
    monkeypatch.setattr(
        hardware, "chat_completion", MagicMock(return_value=json.dumps({"items": [{"code": "SIL-CLEAR", "qty": 2}]}))
    )
    monkeypatch.setattr(
        "app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake")
    )
    mock_send_email = MagicMock()
    monkeypatch.setattr("app.workers.pipeline.send_approval_email", mock_send_email)

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-1@example.com>",
        storage_path=str(fixture_image),
        content_type="image/jpeg",
        filename="w1.jpg",
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.pending_approval
    assert len(quote.panels) == 1
    assert quote.panels[0].width_mm == 1200

    # Golden maths for 1x toughened 1200x900 + 2x SIL-CLEAR hardware (5% waste, 10% GST):
    assert quote.glass_subtotal == Decimal("204.12")
    assert quote.waste_amount == Decimal("9.72")
    assert quote.labour_amount == Decimal("41.20")
    assert quote.hardware_subtotal == Decimal("17.00")
    assert quote.gst_amount == Decimal("26.23")
    assert quote.total == Decimal("288.55")
    assert quote.hardware_lines[0].estimated is True

    assert mock_send_email.call_count == 1
    assert quote.approve_token is not None


def test_extraction_failure_marks_needs_manual_not_crash(monkeypatch, db_session, fixture_image):
    from app.ai.llm import LLMUnavailable

    monkeypatch.setattr(extract, "vision_completion", MagicMock(side_effect=LLMUnavailable("down")))

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-2@example.com>",
        storage_path=str(fixture_image),
        content_type="image/jpeg",
        filename="w1.jpg",
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual


def test_approval_email_failure_marks_needs_manual_not_crash(monkeypatch, db_session, fixture_image):
    monkeypatch.setattr(extract, "vision_completion", MagicMock(return_value=FIXTURE_JSON))
    monkeypatch.setattr(hardware, "chat_completion", MagicMock(return_value=json.dumps({"items": []})))
    monkeypatch.setattr("app.workers.pipeline.generate_quote_pdf", MagicMock(return_value=b"%PDF-fake"))
    monkeypatch.setattr(
        "app.workers.pipeline.send_approval_email", MagicMock(side_effect=RuntimeError("smtp down"))
    )

    quote_id = process_quote_pipeline(
        db_session,
        from_address="fieldworker@example.com",
        email_message_id="<msg-3@example.com>",
        storage_path=str(fixture_image),
        content_type="image/jpeg",
        filename="w1.jpg",
    )
    db_session.commit()

    quote = db_session.get(Quote, quote_id)
    assert quote.status == QuoteStatus.needs_manual
    assert "pipeline error" in quote.notes
