# app/workers/persist.py
from sqlalchemy.orm import Session

from app.models import Attachment, AttachmentKind, AuditLog, Quote, QuoteStatus


def log_event(db: Session, quote_id: str, event: str, detail: str = "") -> None:
    db.add(AuditLog(quote_id=quote_id, event=event, detail=detail))


def create_quote_with_attachments(
    db: Session,
    *,
    from_address: str,
    email_message_id: str,
    images: list,
    body_text: str = "",
) -> Quote:
    quote = Quote(status=QuoteStatus.received, source_email_from=from_address, original_body_text=body_text)
    db.add(quote)
    db.flush()
    for image in images:
        db.add(
            Attachment(
                quote_id=quote.id,
                email_message_id=email_message_id,
                filename=image.filename,
                content_type=image.content_type,
                storage_path=image.storage_path,
            )
        )
    db.flush()
    return quote


def set_attachment_kinds(quote: Quote, kinds: list[str]) -> None:
    """Stamps classifier output onto each Attachment, in the same order the
    images were passed to classify_images. No-op if counts don't line up
    (defensive — should never happen since both come from the same list)."""
    if len(kinds) != len(quote.attachments):
        return
    for attachment, kind in zip(quote.attachments, kinds):
        attachment.kind = AttachmentKind(kind)
