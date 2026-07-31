# tests/test_missing_info.py
from unittest.mock import MagicMock

from app.models import Quote, QuoteStatus
from app.output import missing_info
from app.output.missing_info import send_dimension_conflict_retry_request, send_missing_info_request
from app.schemas import DimensionReading


def test_sends_to_rep_not_owner(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.awaiting_info, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(missing_info.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    send_missing_info_request(quote, ["product_type", "client_name"])

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "rep@fieldcrew.example.com"
    assert sent_message["To"] != missing_info.settings.OWNER_EMAIL


def test_body_lists_exactly_the_missing_fields(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.awaiting_info, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(missing_info.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    send_missing_info_request(quote, ["product_type"])

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    body = sent_message.get_content()
    assert "product type" in body
    assert "client's name" not in body


def test_product_type_request_lists_exact_accepted_vocabulary(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.awaiting_info, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(missing_info.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    send_missing_info_request(quote, ["product_type"])

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    body = sent_message.get_content()
    for term in ("bi-fold", "casement", "awning", "hinged", "cedar entry"):
        assert term in body


def test_returns_the_outbound_message_id(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.awaiting_info, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(missing_info.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    message_id = send_missing_info_request(quote, ["client_name"])

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["Message-ID"] == message_id
    assert message_id.startswith("<") and message_id.endswith(">")


def test_dimension_conflict_retry_sent_to_rep_names_the_conflicting_values(monkeypatch):
    quote = Quote(id="quote-1", status=QuoteStatus.awaiting_info, source_email_from="rep@fieldcrew.example.com")

    mock_smtp_instance = MagicMock()
    mock_smtp_instance.__enter__.return_value = mock_smtp_instance
    monkeypatch.setattr(missing_info.smtplib, "SMTP", MagicMock(return_value=mock_smtp_instance))

    readings = [
        DimensionReading(value_mm=790, source="ar_overlay"),
        DimensionReading(value_mm=2000, source="ar_overlay"),
    ]
    message_id = send_dimension_conflict_retry_request(quote, readings)

    sent_message = mock_smtp_instance.send_message.call_args[0][0]
    assert sent_message["To"] == "rep@fieldcrew.example.com"
    assert sent_message["Subject"].startswith(missing_info.SUBJECT_MARKER)
    body = sent_message.get_content()
    assert "790mm" in body
    assert "2000mm" in body
    assert "retake" in body.lower()
    assert sent_message["Message-ID"] == message_id
