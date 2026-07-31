# tests/test_needs_manual_notice.py
from unittest.mock import MagicMock

from app.models import Quote, QuoteStatus
from app.output import needs_manual_notice
from app.output.needs_manual_notice import send_needs_manual_notice


def test_sends_to_owner_not_rep(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.needs_manual, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(needs_manual_notice.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    send_needs_manual_notice(quote, "dimension_conflict_item_1_height")

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == needs_manual_notice.settings.OWNER_EMAIL
    assert sent_message["To"] != "rep@fieldcrew.example.com"


def test_body_includes_reason_and_sender(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.needs_manual, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(needs_manual_notice.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    send_needs_manual_notice(quote, "dimension_conflict_item_1_height")

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    body = sent_message.get_content()
    assert "dimension_conflict_item_1_height" in body
    assert "rep@fieldcrew.example.com" in body
    assert quote.id in body
