# app/ingest/poller.py
import email
import imaplib
import logging
import re
import uuid
from dataclasses import dataclass, field
from email import policy
from email.message import Message
from pathlib import Path

from app.config import settings
from app.output import missing_info

logger = logging.getLogger(__name__)

# Mailboxes with a large backlog of unseen mail can return a SEARCH response
# line longer than imaplib's default 1MB cap; raise it well above what any
# realistic UNSEEN id list would need.
imaplib._MAXLINE = 10_000_000

DEFAULT_STORAGE_DIR = Path("data/attachments")

_TAG_RE = re.compile(r"<[^>]+>")
# Matches the "On <date>, <name> wrote:" attribution line most mail clients
# (Gmail, Apple Mail, Outlook) insert above quoted text in a reply.
_QUOTE_ATTRIBUTION_RE = re.compile(r"^On .+ wrote:\s*$", re.MULTILINE)

# Tracking "already processed" via the standard \Seen flag is fragile: a human
# casually opening/previewing their own inbox (very likely when OWNER_EMAIL is
# also the intake inbox) marks mail read, silently hiding it from future
# UNSEEN polls forever. Use a dedicated custom keyword flag instead, so
# whether a human has read the email is irrelevant to whether we've processed it.
PROCESSED_FLAG = "GlassQuoteProcessed"


@dataclass
class PolledImage:
    filename: str
    content_type: str
    storage_path: str


@dataclass
class PolledMessage:
    email_message_id: str
    from_address: str
    body_text: str
    images: list[PolledImage] = field(default_factory=list)


@dataclass
class PolledReply:
    email_message_id: str
    from_address: str
    body_text: str
    in_reply_to: str
    images: list[PolledImage] = field(default_factory=list)


def connect_imap() -> imaplib.IMAP4:
    imap_cls = imaplib.IMAP4_SSL if settings.IMAP_USE_SSL else imaplib.IMAP4
    client = imap_cls(settings.IMAP_HOST, settings.IMAP_PORT)
    client.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
    client.select(settings.IMAP_MAILBOX)
    return client


def _image_parts(msg: Message) -> list[Message]:
    return [
        part for part in msg.walk() if part.get_content_type().startswith("image/") and part.get_filename()
    ]


def _strip_quoted_reply(text: str) -> str:
    """Drops the quoted original message from a reply, so an LLM extracting
    fields from the new text isn't confused by the previous email's own
    wording (e.g. a clarification request that itself lists candidate
    values) still being present below it."""
    match = _QUOTE_ATTRIBUTION_RE.search(text)
    if match:
        text = text[: match.start()]
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(lines).strip()


def _body_text(msg: Message) -> str:
    body_part = msg.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        return ""
    content = body_part.get_content()
    if body_part.get_content_type() == "text/html":
        content = _TAG_RE.sub(" ", content)
    return _strip_quoted_reply(content.strip())


def _save_attachment(part: Message, storage_dir: Path) -> Path:
    storage_dir.mkdir(parents=True, exist_ok=True)
    original_name = part.get_filename() or "attachment.bin"
    unique_name = f"{uuid.uuid4().hex}_{Path(original_name).name}"
    path = storage_dir / unique_name
    path.write_bytes(part.get_payload(decode=True))
    return path


def _mark_processed(client: imaplib.IMAP4, num: bytes) -> None:
    client.store(num, "+FLAGS", f"(\\Seen {PROCESSED_FLAG})")


def _process_message(client: imaplib.IMAP4, num: bytes, storage_dir: Path) -> PolledMessage | None:
    status, msg_data = client.fetch(num, "(RFC822)")
    if status != "OK" or not msg_data or msg_data[0] is None:
        logger.error("IMAP fetch failed for message %s", num)
        return None

    raw_bytes = msg_data[0][1]
    msg = email.message_from_bytes(raw_bytes, policy=policy.default)
    message_id = msg.get("Message-ID") or str(uuid.uuid4())
    from_address = msg.get("From", "")

    image_parts = _image_parts(msg)
    if not image_parts:
        logger.info("Skipping non-image email %s from %s", message_id, from_address)
        _mark_processed(client, num)
        return None

    images = []
    for part in image_parts:
        path = _save_attachment(part, storage_dir)
        images.append(
            PolledImage(filename=path.name, content_type=part.get_content_type(), storage_path=str(path))
        )

    _mark_processed(client, num)
    return PolledMessage(
        email_message_id=message_id,
        from_address=from_address,
        body_text=_body_text(msg),
        images=images,
    )


def _search_query() -> str:
    query = f"UNKEYWORD {PROCESSED_FLAG}"
    if settings.IMAP_SUBJECT_FILTER:
        query += f' SUBJECT "{settings.IMAP_SUBJECT_FILTER}"'
    return query


def poll_inbox(
    storage_dir: Path = DEFAULT_STORAGE_DIR, client: imaplib.IMAP4 | None = None
) -> list[PolledMessage]:
    owns_client = client is None
    client = client or connect_imap()
    results: list[PolledMessage] = []
    try:
        status, data = client.search(None, _search_query())
        if status != "OK":
            logger.error("IMAP search failed with status %s", status)
            return results

        for num in data[0].split():
            message = _process_message(client, num, storage_dir)
            if message is not None:
                results.append(message)
    finally:
        if owns_client:
            client.logout()
    return results


def poll_replies(
    awaiting_message_ids: set[str],
    storage_dir: Path = DEFAULT_STORAGE_DIR,
    client: imaplib.IMAP4 | None = None,
) -> list[PolledReply]:
    """Finds rep replies to a previously-sent missing-info clarification
    email, matched via the In-Reply-To header against outstanding
    Message-IDs (Quote.awaiting_info_message_id). Best-effort: some mail
    clients rewrite threading headers, which this can't recover from.

    Does exactly ONE IMAP search regardless of how many quotes are
    outstanding — an earlier version searched once per awaiting quote,
    which against a large mailbox made this take minutes per poll cycle."""
    if not awaiting_message_ids:
        return []

    owns_client = client is None
    client = client or connect_imap()
    results: list[PolledReply] = []
    try:
        status, data = client.search(None, f'UNKEYWORD {PROCESSED_FLAG} SUBJECT "{missing_info.SUBJECT_MARKER}"')
        if status != "OK":
            logger.error("IMAP reply search failed with status %s", status)
            return results

        for num in data[0].split():
            status, msg_data = client.fetch(num, "(RFC822)")
            if status != "OK" or not msg_data or msg_data[0] is None:
                logger.error("IMAP fetch failed for reply message %s", num)
                continue

            msg = email.message_from_bytes(msg_data[0][1], policy=policy.default)
            in_reply_to = msg.get("In-Reply-To")
            if in_reply_to not in awaiting_message_ids:
                # our own outbound copy, or a reply to some other/expired
                # request — not one we're waiting on; mark seen so it's not
                # re-fetched on every future poll.
                _mark_processed(client, num)
                continue

            message_id = msg.get("Message-ID") or str(uuid.uuid4())
            from_address = msg.get("From", "")

            images = []
            for part in _image_parts(msg):
                path = _save_attachment(part, storage_dir)
                images.append(
                    PolledImage(filename=path.name, content_type=part.get_content_type(), storage_path=str(path))
                )

            _mark_processed(client, num)
            results.append(
                PolledReply(
                    email_message_id=message_id,
                    from_address=from_address,
                    body_text=_body_text(msg),
                    in_reply_to=in_reply_to,
                    images=images,
                )
            )
    finally:
        if owns_client:
            client.logout()
    return results
