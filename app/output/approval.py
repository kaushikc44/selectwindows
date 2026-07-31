# app/output/approval.py
import json
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.models import Quote
from app.output.pdf import PLACEHOLDER_BANNER

logger = logging.getLogger(__name__)

_SALT = "glassquote-approval"
_serializer = URLSafeTimedSerializer(settings.APPROVAL_SECRET_KEY, salt=_SALT)


class InvalidApprovalToken(Exception):
    """Raised when a token fails signature verification or has expired."""


def generate_token(quote_id: str, action: str) -> str:
    return _serializer.dumps({"quote_id": quote_id, "action": action})


def verify_token(token: str) -> dict:
    try:
        return _serializer.loads(token, max_age=settings.APPROVAL_TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise InvalidApprovalToken("token expired") from exc
    except BadSignature as exc:
        raise InvalidApprovalToken("bad signature") from exc


def build_approval_links(quote_id: str) -> tuple[str, str, str, str]:
    approve_token = generate_token(quote_id, "approve")
    reject_token = generate_token(quote_id, "reject")
    approve_url = f"{settings.PUBLIC_BASE_URL}/approve/{approve_token}"
    reject_url = f"{settings.PUBLIC_BASE_URL}/reject/{reject_token}"
    return approve_url, reject_url, approve_token, reject_token


def _flags_text(quote: Quote) -> str:
    if not quote.flags:
        return ""
    flags = json.loads(quote.flags)
    if not flags:
        return ""
    lines = "\n".join(f"  - {f['message']}" for f in flags)
    return f"Flags:\n{lines}\n\n"


def _breakdown_text(quote: Quote, approve_url: str, reject_url: str) -> str:
    return (
        f"New quote {quote.id} is ready for review.\n\n"
        f"{PLACEHOLDER_BANNER}\n\n"
        f"Items subtotal: ${quote.items_subtotal}\n"
        f"Installation subtotal: ${quote.installation_subtotal}\n"
        f"GST: ${quote.gst_amount}\n"
        f"Total: ${quote.total}\n\n"
        f"{_flags_text(quote)}"
        f"Approve: {approve_url}\n"
        f"Reject: {reject_url}\n"
    )


def send_approval_email(quote: Quote, pdf_bytes: bytes, approve_url: str, reject_url: str) -> None:
    message = MIMEMultipart()
    message["Subject"] = f"Quote {quote.id} pending approval"
    message["From"] = settings.SMTP_FROM
    message["To"] = settings.OWNER_EMAIL
    message.attach(MIMEText(_breakdown_text(quote, approve_url, reject_url), "plain"))

    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=f"quote-{quote.id}.pdf")
    message.attach(attachment)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)
    logger.info("Approval email sent to %s for quote %s", settings.OWNER_EMAIL, quote.id)
