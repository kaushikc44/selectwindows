# app/workers/persist.py
from sqlalchemy.orm import Session

from app.models import Attachment, AuditLog, Quote, QuoteStatus


def log_event(db: Session, quote_id: str, event: str, detail: str = "") -> None:
    db.add(AuditLog(quote_id=quote_id, event=event, detail=detail))


def create_quote_with_attachment(
    db: Session,
    *,
    from_address: str,
    email_message_id: str,
    storage_path: str,
    content_type: str,
    filename: str,
) -> Quote:
    quote = Quote(status=QuoteStatus.extracted, source_email_from=from_address)
    db.add(quote)
    db.flush()
    db.add(
        Attachment(
            quote_id=quote.id,
            email_message_id=email_message_id,
            filename=filename,
            content_type=content_type,
            storage_path=storage_path,
        )
    )
    return quote
