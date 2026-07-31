# app/ai/llm.py
import base64
import logging
import time

from openai import APIError, OpenAI

from app.config import settings

logger = logging.getLogger(__name__)


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


def _call_with_retries(fn, *, attempts: int) -> str:
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


def chat_completion(messages: list[dict], *, temperature: float = 0.0) -> str:
    def _call() -> str:
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    return _call_with_retries(_call, attempts=settings.LLM_MAX_RETRIES + 1)


def vision_completion(images: list[tuple[bytes, str]], prompt: str) -> str:
    """images: list of (image_bytes, mime_type) pairs, sent alongside one text prompt."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for image_bytes, mime_type in images:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}
        )
    messages = [{"role": "user", "content": content}]

    def _call() -> str:
        response = vision_client.chat.completions.create(
            model=settings.LLM_VISION_MODEL,
            messages=messages,
            temperature=0.0,
        )
        return response.choices[0].message.content or ""

    return _call_with_retries(_call, attempts=settings.LLM_MAX_RETRIES + 1)
