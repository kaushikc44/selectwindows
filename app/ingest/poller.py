# app/ingest/poller.py
import email
import imaplib
import logging
import uuid
from dataclasses import dataclass
from email.message import Message
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_STORAGE_DIR = Path("data/attachments")


@dataclass
class PolledAttachment:
    email_message_id: str
    from_address: str
    filename: str
    content_type: str
    storage_path: str


def connect_imap() -> imaplib.IMAP4:
    imap_cls = imaplib.IMAP4_SSL if settings.IMAP_USE_SSL else imaplib.IMAP4
    client = imap_cls(settings.IMAP_HOST, settings.IMAP_PORT)
    client.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
    client.select(settings.IMAP_MAILBOX)
    return client


def _first_image_part(msg: Message) -> Message | None:
    for part in msg.walk():
        if part.get_content_type().startswith("image/") and part.get_filename():
            return part
    return None


def _save_attachment(part: Message, storage_dir: Path) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)
    original_name = part.get_filename() or "attachment.bin"
    unique_name = f"{uuid.uuid4().hex}_{Path(original_name).name}"
    path = storage_dir / unique_name
    path.write_bytes(part.get_payload(decode=True))
    return path


def _mark_seen(client: imaplib.IMAP4, num: bytes) -> None:
    client.store(num, "+FLAGS", "\\Seen")


def _process_message(client: imaplib.IMAP4, num: bytes, storage_dir: Path) -> PolledAttachment | None:
    status, msg_data = client.fetch(num, "(RFC822)")
    if status != "OK" or not msg_data or msg_data[0] is None:
        logger.error("IMAP fetch failed for message %s", num)
        return None

    raw_bytes = msg_data[0][1]
    msg = email.message_from_bytes(raw_bytes)
    message_id = msg.get("Message-ID") or str(uuid.uuid4())
    from_address = msg.get("From", "")

    image_part = _first_image_part(msg)
    if image_part is None:
        logger.info("Skipping non-image email %s from %s", message_id, from_address)
        _mark_seen(client, num)
        return None

    path = _save_attachment(image_part, storage_dir)
    _mark_seen(client, num)
    return PolledAttachment(
        email_message_id=message_id,
        from_address=from_address,
        filename=path.name,
        content_type=image_part.get_content_type(),
        storage_path=str(path),
    )


def poll_inbox(
    storage_dir: Path = DEFAULT_STORAGE_DIR, client: imaplib.IMAP4 | None = None
) -> list[PolledAttachment]:
    owns_client = client is None
    client = client or connect_imap()
    results: list[PolledAttachment] = []
    try:
        status, data = client.search(None, "UNSEEN")
        if status != "OK":
            logger.error("IMAP search failed with status %s", status)
            return results

        for num in data[0].split():
            attachment = _process_message(client, num, storage_dir)
            if attachment is not None:
                results.append(attachment)
    finally:
        if owns_client:
            client.logout()
    return results
