# app/ai/llm.py
import base64
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar

from openai import APIError, OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Per-job context for AI call logging (maps branch). The pipeline sets this
# around a run so every LLM call inside it — extract/classify/enrich/approval —
# is attributed to the quote in app/ai/llm.py's AiCallLog row, without having
# to thread quote_id through every call site. A ContextVar (not a global) so
# concurrent Celery tasks / request threads don't bleed into each other.
_ai_quote_id: ContextVar[str | None] = ContextVar("ai_quote_id", default=None)


@contextmanager
def ai_quote_context(quote_id: str | None):
    """Bind the current job to AI calls made inside this block. Use in the
    pipeline entry points (app/workers/pipeline.py) so the AiCallLog rows
    written by chat_completion / vision_completion carry the right quote_id."""
    token = _ai_quote_id.set(quote_id)
    try:
        yield
    finally:
        _ai_quote_id.reset(token)


class LLMUnavailable(Exception):
    """Raised when the configured LLM endpoint cannot fulfil a request after retries."""


client = OpenAI(
    base_url=settings.LLM_BASE_URL,
    api_key=settings.LLM_API_KEY,
    timeout=settings.LLM_TIMEOUT_SECONDS,
)

vision_client = OpenAI(
    base_url=settings.LLM_VISION_BASE_URL or settings.LLM_BASE_URL,
    api_key=settings.LLM_VISION_API_KEY or settings.LLM_API_KEY,
    timeout=settings.LLM_TIMEOUT_SECONDS,
)


# Indirection so tests can point logging at the in-memory test DB instead of
# the real DATABASE_URL — app/ai/llm.py logs in its own session and must work
# both in the web/Celery process (real DB) and under pytest (test DB).
def _get_log_session():
    from app.db import SessionLocal

    return SessionLocal()


def _render_input(messages: list[dict]) -> str:
    """Flatten chat messages to a readable audit string. For vision calls the
    caller passes a single user message whose content is a list of parts; we
    keep the text prompt and summarise image parts (count/mime/size) rather
    than embedding base64 — an audit row shouldn't carry megabytes."""
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(f"[{role}] {content}")
        elif isinstance(content, list):
            text_chunks: list[str] = []
            images: list[str] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text_chunks.append(str(item.get("text", "")))
                elif item.get("type") == "image_url":
                    url = (item.get("image_url") or {}).get("url", "")
                    mime = "image"
                    if url.startswith("data:"):
                        mime = url.split(";", 1)[0][5:] or "image"
                    # url looks like "data:<mime>;base64,<len>..." — log the
                    # kind and approximate size, never the bytes.
                    encoded = url.split("base64,", 1)[-1] if "base64," in url else ""
                    size = len(encoded) * 3 // 4 if encoded else 0
                    images.append(f"{mime} ~{size} bytes")
            text_chunks = [t for t in text_chunks if t]
            rendered = "\n".join(text_chunks)
            if images:
                rendered = f"{rendered}\n[images: {', '.join(images)}]" if rendered else f"[images: {', '.join(images)}]"
            parts.append(f"[{role}] {rendered}")
    return "\n".join(parts)


def _log_call(
    *,
    purpose: str,
    quote_id: str | None,
    model: str,
    input_text: str | None,
    output_text: str | None,
    start: float,
    usage: object | None,
    success: bool,
    error: str | None,
) -> None:
    """Best-effort audit write — must never raise and break the real call."""
    try:
        from app.models import AiCallLog

        p_tok = c_tok = None
        if usage is not None:
            p_tok = getattr(usage, "prompt_tokens", None)
            c_tok = getattr(usage, "completion_tokens", None)
        session = _get_log_session()
        try:
            session.add(
                AiCallLog(
                    quote_id=quote_id,
                    purpose=purpose,
                    model=model,
                    input_text=input_text,
                    output_text=output_text,
                    latency_ms=int((time.monotonic() - start) * 1000),
                    prompt_tokens=p_tok,
                    completion_tokens=c_tok,
                    success=success,
                    error=error,
                )
            )
            session.commit()
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 - logging is best-effort
        logger.warning("AiCallLog write failed: %s", exc)


def _call_with_retries(fn, *, attempts: int):
    """Returns the raw OpenAI response (so the caller can read usage) or
    raises LLMUnavailable after `attempts` tries."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except APIError as exc:
            last_exc = exc
            logger.warning("LLM call failed (attempt %s/%s): %s", attempt + 1, attempts, exc)
            if attempt < attempts - 1:
                time.sleep(2**attempt)
    raise LLMUnavailable(str(last_exc)) from last_exc


def chat_completion(
    messages: list[dict], *, temperature: float = 0.0, purpose: str = "unknown", quote_id: str | None = None
) -> str:
    qid = quote_id if quote_id is not None else _ai_quote_id.get()
    start = time.monotonic()
    input_text = _render_input(messages)

    def _call():
        return client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=temperature,
        )

    try:
        response = _call_with_retries(_call, attempts=settings.LLM_MAX_RETRIES + 1)
    except LLMUnavailable as exc:
        _log_call(
            purpose=purpose, quote_id=qid, model=settings.LLM_MODEL, input_text=input_text,
            output_text=None, start=start, usage=None, success=False, error=str(exc),
        )
        raise
    content = response.choices[0].message.content or ""
    _log_call(
        purpose=purpose, quote_id=qid, model=settings.LLM_MODEL, input_text=input_text,
        output_text=content, start=start, usage=getattr(response, "usage", None),
        success=True, error=None,
    )
    return content


def vision_completion(
    images: list[tuple[bytes, str]], prompt: str, *, purpose: str = "unknown", quote_id: str | None = None
) -> str:
    """images: list of (image_bytes, mime_type) pairs, sent alongside one text prompt."""
    qid = quote_id if quote_id is not None else _ai_quote_id.get()
    start = time.monotonic()

    content: list[dict] = [{"type": "text", "text": prompt}]
    for image_bytes, mime_type in images:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
        )
    messages = [{"role": "user", "content": content}]
    input_text = _render_input(messages)

    def _call():
        return vision_client.chat.completions.create(
            model=settings.LLM_VISION_MODEL,
            messages=messages,
            temperature=0.0,
        )

    try:
        response = _call_with_retries(_call, attempts=settings.LLM_MAX_RETRIES + 1)
    except LLMUnavailable as exc:
        _log_call(
            purpose=purpose, quote_id=qid, model=settings.LLM_VISION_MODEL, input_text=input_text,
            output_text=None, start=start, usage=None, success=False, error=str(exc),
        )
        raise
    content_text = response.choices[0].message.content or ""
    _log_call(
        purpose=purpose, quote_id=qid, model=settings.LLM_VISION_MODEL, input_text=input_text,
        output_text=content_text, start=start, usage=getattr(response, "usage", None),
        success=True, error=None,
    )
    return content_text