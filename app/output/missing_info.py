# app/output/missing_info.py
"""Sends a short clarification email to the REP (not the customer, not the
owner) when critical tier-2 fields are missing, and returns the outbound
Message-ID so the reply can later be matched back to this quote."""

import logging
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid

from app.config import settings
from app.models import Quote
from app.schemas import DimensionReading

logger = logging.getLogger(__name__)

# Shared with app.ingest.poller: lets poll_replies() find candidate reply
# emails with a single IMAP SUBJECT search instead of one search per
# outstanding awaiting_info quote.
SUBJECT_MARKER = "Quick info needed"

# Listing the exact accepted terms (rather than "the product type") matters:
# the reply is matched against this fixed vocabulary by keyword, not
# interpreted freely — a rep writing "hinge" or "glass slab" won't match
# anything, so the request has to spell out words that will.
PRODUCT_TYPE_OPTIONS = (
    "one of these exact words — windows: awning, casement, sliding, "
    "double hung, louvre, powerlouvre, bi-fold, sashless, gas strut; "
    "doors: sliding, stacking, bi-fold, hinged, cedar entry"
)

FIELD_LABELS = {
    "product_type": f"the product type — {PRODUCT_TYPE_OPTIONS}",
    "client_name": "the client's name",
}


def _missing_fields_text(missing_fields: list[str]) -> str:
    return "\n".join(f"- {FIELD_LABELS.get(field, field)}" for field in missing_fields)


def send_missing_info_request(quote: Quote, missing_fields: list[str]) -> str:
    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    message["Subject"] = f"{SUBJECT_MARKER} for your quote request (job {quote.id[:8]})"
    message["From"] = settings.SMTP_FROM
    message["To"] = quote.source_email_from
    message.set_content(
        "Thanks for the photos! To finish this quote we just need:\n\n"
        f"{_missing_fields_text(missing_fields)}\n\n"
        "Just reply to this email with those details and we'll continue.\n"
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    logger.info(
        "Missing-info request sent to %s for quote %s (fields: %s)",
        quote.source_email_from,
        quote.id,
        missing_fields,
    )
    return message_id


def _conflict_readings_text(readings: list[DimensionReading]) -> str:
    return "\n".join(f"- {r.value_mm}mm (read from {r.source.replace('_', ' ')})" for r in readings)


def send_dimension_conflict_retry_request(quote: Quote, readings: list[DimensionReading]) -> str:
    """Sent when two or more readings for the same edge disagree by more
    than the merge threshold — asks the rep to retake a clearer photo or
    just restate the correct number, rather than silently going to
    needs_manual. Reuses SUBJECT_MARKER so poll_replies() picks the reply up
    the same way it does for a missing product_type/client_name request."""
    message = EmailMessage()
    message_id = make_msgid()
    message["Message-ID"] = message_id
    message["Subject"] = f"{SUBJECT_MARKER} for your quote request (job {quote.id[:8]})"
    message["From"] = settings.SMTP_FROM
    message["To"] = quote.source_email_from
    message.set_content(
        "Thanks for the photos! We couldn't get a clear measurement — we read conflicting values "
        "for the same edge:\n\n"
        f"{_conflict_readings_text(readings)}\n\n"
        "Could you please retake a clearer photo of that measurement, or just reply with the "
        "correct number? A new photo attached to your reply is fine too.\n"
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    logger.info(
        "Dimension-conflict retry request sent to %s for quote %s (%s readings)",
        quote.source_email_from,
        quote.id,
        len(readings),
    )
    return message_id
