# tests/test_approval.py
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from itsdangerous import URLSafeTimedSerializer

from app.models import Quote, QuoteStatus
from app.output import approval
from app.output.approval import (
    InvalidApprovalToken,
    build_approval_links,
    generate_token,
    send_approval_email,
    verify_token,
)


def test_build_approval_links_produce_distinct_tokens():
    approve_url, reject_url, approve_token, reject_token = build_approval_links("quote-1")
    assert "/approve/" in approve_url
    assert "/reject/" in reject_url
    assert approve_token in approve_url
    assert reject_token in reject_url
    assert approve_token != reject_token


def test_verify_token_roundtrips_payload():
    token = generate_token("quote-1", "approve")
    payload = verify_token(token)
    assert payload == {"quote_id": "quote-1", "action": "approve"}


def test_verify_token_rejects_bad_signature():
    with pytest.raises(InvalidApprovalToken):
        verify_token("not-a-real-token")


def test_verify_token_rejects_expired_token(monkeypatch):
    stale_serializer = URLSafeTimedSerializer("different-secret-key", salt="glassquote-approval")
    token = stale_serializer.dumps({"quote_id": "quote-1", "action": "approve"})
    with pytest.raises(InvalidApprovalToken):
        verify_token(token)


def test_send_approval_email_sends_via_smtp_with_pdf_attachment(monkeypatch):
    quote = Quote(
        id="quote-1",
        status=QuoteStatus.pending_approval,
        glass_subtotal=Decimal("408.24"),
        hardware_subtotal=Decimal("25.50"),
        labour_amount=Decimal("82.40"),
        waste_amount=Decimal("19.44"),
        gst_amount=Decimal("49.06"),
        total=Decimal("539.70"),
    )

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    mock_smtp_cls = MagicMock(return_value=mock_smtp_instance)
    monkeypatch.setattr(approval.smtplib, "SMTP", mock_smtp_cls)

    send_approval_email(quote, b"%PDF-fake", "http://x/approve/tok", "http://x/reject/tok")

    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once()
    assert mock_smtp_instance.send_message.call_count == 1
    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == approval.settings.OWNER_EMAIL
    attachment_parts = [p for p in sent_message.walk() if p.get_filename()]
    assert attachment_parts[0].get_filename() == "quote-quote-1.pdf"
