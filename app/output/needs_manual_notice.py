# app/output/needs_manual_notice.py
"""Notifies the OWNER (internal staff, not the rep or a customer) whenever a
quote lands in needs_manual, so a submission the system correctly declines
to auto-resolve is never silently invisible — the rep/sender still gets
nothing (this isn't customer-facing), but someone always knows to look."""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings
from app.models import Quote

logger = logging.getLogger(__name__)


def send_needs_manual_notice(quote: Quote, reason: str) -> None:
    message = EmailMessage()
    message["Subject"] = f"Quote needs manual review (job {quote.id[:8]})"
    message["From"] = settings.SMTP_FROM
    message["To"] = settings.OWNER_EMAIL
    message.set_content(
        f"Quote {quote.id} could not be automatically resolved and needs manual review.\n\n"
        f"Reason: {reason}\n"
        f"From: {quote.source_email_from or '(unknown)'}\n"
    )

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)

    logger.info("needs_manual notice sent to %s for quote %s (reason: %s)", settings.OWNER_EMAIL, quote.id, reason)
