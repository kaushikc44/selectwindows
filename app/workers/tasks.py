# app/workers/tasks.py
import logging

from celery import Celery
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.ingest.poller import PolledImage, poll_inbox, poll_replies
from app.models import Quote, QuoteStatus
from app.workers.locking import with_lock
from app.workers.pipeline import process_quote_pipeline, process_reply_pipeline, process_worker_submission_pipeline

# Generous enough to cover a slow IMAP session + several LLM calls, but
# still auto-expires if a worker process dies mid-task rather than wedging
# the lock forever.
POLL_LOCK_TIMEOUT_SECONDS = 300

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
    },
    "poll-replies-every-minute": {
        "task": "app.workers.tasks.poll_and_process_replies",
        "schedule": 60.0,
    },
}


@celery_app.task(name="app.workers.tasks.process_attachment")
def process_attachment(
    email_message_id: str, from_address: str, body_text: str, images: list[dict]
) -> str:
    db = SessionLocal()
    try:
        quote_id = process_quote_pipeline(
            db,
            from_address=from_address,
            email_message_id=email_message_id,
            body_text=body_text,
            images=[PolledImage(**image) for image in images],
        )
        db.commit()
        return quote_id
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_worker_submission")
def process_worker_submission(quote_id: str) -> str:
    db = SessionLocal()
    try:
        quote = db.get(Quote, quote_id)
        if quote is not None:
            process_worker_submission_pipeline(db, quote)
            db.commit()
        return quote_id
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks.process_reply")
def process_reply(quote_id: str, body_text: str, images: list[dict] | None = None) -> str:
    db = SessionLocal()
    try:
        quote = db.get(Quote, quote_id)
        if quote is not None:
            process_reply_pipeline(
                db, quote, body_text, images=[PolledImage(**image) for image in images or []]
            )
            db.commit()
        return quote_id
    finally:
        db.close()


def _poll_and_process_impl() -> list[str]:
    messages = poll_inbox()
    quote_ids = []
    for message in messages:
        result = process_attachment.delay(
            message.email_message_id,
            message.from_address,
            message.body_text,
            [
                {"filename": img.filename, "content_type": img.content_type, "storage_path": img.storage_path}
                for img in message.images
            ],
        )
        quote_ids.append(result.id)
    logger.info("Enqueued %s quote(s) from inbox poll", len(quote_ids))
    return quote_ids


@celery_app.task(name="app.workers.tasks.poll_and_process")
def poll_and_process() -> list[str]:
    result = with_lock("lock:poll_and_process", timeout=POLL_LOCK_TIMEOUT_SECONDS, fn=_poll_and_process_impl)
    if result is None:
        logger.info("Skipping poll_and_process — previous run still in progress")
        return []
    return result


def _poll_and_process_replies_impl() -> list[str]:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(Quote.id, Quote.awaiting_info_message_id).where(Quote.status == QuoteStatus.awaiting_info)
        ).all()
        message_id_to_quote_id = {message_id: quote_id for quote_id, message_id in rows if message_id}
    finally:
        db.close()

    if not message_id_to_quote_id:
        return []

    replies = poll_replies(set(message_id_to_quote_id.keys()))
    task_ids = []
    for reply in replies:
        quote_id = message_id_to_quote_id.get(reply.in_reply_to)
        if quote_id is None:
            continue
        result = process_reply.delay(
            quote_id,
            reply.body_text,
            [
                {"filename": img.filename, "content_type": img.content_type, "storage_path": img.storage_path}
                for img in reply.images
            ],
        )
        task_ids.append(result.id)
    logger.info("Enqueued %s rep-reply quote(s) from awaiting_info poll", len(task_ids))
    return task_ids


@celery_app.task(name="app.workers.tasks.poll_and_process_replies")
def poll_and_process_replies() -> list[str]:
    result = with_lock(
        "lock:poll_and_process_replies", timeout=POLL_LOCK_TIMEOUT_SECONDS, fn=_poll_and_process_replies_impl
    )
    if result is None:
        logger.info("Skipping poll_and_process_replies — previous run still in progress")
        return []
    return result
