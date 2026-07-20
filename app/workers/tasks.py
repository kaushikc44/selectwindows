# app/workers/tasks.py
import logging

from celery import Celery

from app.config import settings
from app.db import SessionLocal
from app.ingest.poller import poll_inbox
from app.workers.pipeline import process_quote_pipeline

logger = logging.getLogger(__name__)

celery_app = Celery(
    "glassquote",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)
celery_app.conf.beat_schedule = {
    "poll-inbox-every-minute": {
        "task": "app.workers.tasks.poll_and_process",
        "schedule": 60.0,
    }
}


@celery_app.task(name="app.workers.tasks.process_attachment")
def process_attachment(
    email_message_id: str, from_address: str, storage_path: str, content_type: str, filename: str
) -> str:
    db = SessionLocal()
    try:
        quote_id = process_quote_pipeline(
            db,
            from_address=from_address,
            email_message_id=email_message_id,
            storage_path=storage_path,
            content_type=content_type,
            filename=filename,
        )
        db.commit()
        return quote_id
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.poll_and_process")
def poll_and_process() -> list[str]:
    attachments = poll_inbox()
    quote_ids = []
    for attachment in attachments:
        result = process_attachment.delay(
            attachment.email_message_id,
            attachment.from_address,
            attachment.storage_path,
            attachment.content_type,
            attachment.filename,
        )
        quote_ids.append(result.id)
    logger.info("Enqueued %s quote(s) from inbox poll", len(quote_ids))
    return quote_ids
