# app/ai/extract_email.py
"""Pulls tier-2 context (client name, room, product hints, site notes) out
of the email body free text alone. Source tagging ("email_body" vs
"missing") is applied here in plain Python after the call, not by the LLM.

Also pulls any EXPLICIT typed dimensions the rep stated in the body text
(e.g. "Width: 2400 mm") — as raw {value, unit} pairs only, same "no
arithmetic in the LLM" boundary as extract_ar.py. Unit conversion and
merging against photo-derived readings happens deterministically in
app/workers/routing.py / app/engine/units.py / app/engine/merge.py."""

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, chat_completion
from app.schemas import FieldValue

logger = logging.getLogger(__name__)

STRING_FIELDS = ("client_name", "room", "product_hint", "site_notes")

EMAIL_EXTRACTION_PROMPT_TEMPLATE = """A field rep for Select Window Installations wrote this \
email body about a quote job. Pull out only what is explicitly stated — do not guess or infer \
anything not actually said.

EMAIL BODY:
---
{body_text}
---

Also check for EXPLICIT typed dimensions (e.g. "Width: 2400 mm", "Height: 2.1m") — report the \
raw value and unit EXACTLY as written (do not convert units yourself). Only fill these if a \
number with a clear width/height label is actually present; null otherwise — never guess a \
dimension from a product name or general description.

Return ONLY JSON, no markdown fences, no prose:
{{"client_name": "string or null", "room": "string or null",
"product_hint": "short phrase describing the product/material/config mentioned, or null",
"site_notes": "any site condition/access/asbestos/floor-level notes mentioned, or null",
"width_value": null, "width_unit": null, "height_value": null, "height_unit": null}}
"""


class _RawEmailFields(BaseModel):
    client_name: str | None = None
    room: str | None = None
    product_hint: str | None = None
    site_notes: str | None = None
    width_value: float | None = None
    width_unit: str | None = None
    height_value: float | None = None
    height_unit: str | None = None


class EmailDimensionReading(BaseModel):
    raw_value: float
    raw_unit: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)


def _wrap(value: str | None) -> FieldValue[str]:
    if not value:
        return FieldValue[str](value=None, source="missing", confidence=None)
    return FieldValue[str](value=value, source="email_body", confidence=0.8)


def _wrap_dimension(value: float | None, unit: str | None) -> FieldValue[EmailDimensionReading]:
    if value is None or not unit:
        return FieldValue[EmailDimensionReading](value=None, source="missing", confidence=None)
    reading = EmailDimensionReading(raw_value=value, raw_unit=unit)
    return FieldValue[EmailDimensionReading](value=reading, source="email_body", confidence=reading.confidence)


def extract_email_fields(body_text: str) -> dict[str, FieldValue]:
    if not body_text or not body_text.strip():
        raw_fields = _RawEmailFields()
    else:
        prompt = EMAIL_EXTRACTION_PROMPT_TEMPLATE.format(body_text=body_text)
        try:
            raw = chat_completion([{"role": "user", "content": prompt}])
        except LLMUnavailable as exc:
            logger.error("Email field extraction unavailable, treating body as empty: %s", exc)
            raw_fields = _RawEmailFields()
        else:
            try:
                raw_fields = _RawEmailFields.model_validate(json.loads(raw, strict=False))
            except (json.JSONDecodeError, ValidationError) as exc:
                logger.warning("Email field extraction JSON invalid, treating body as empty: %s", exc)
                raw_fields = _RawEmailFields()

    result = {name: _wrap(getattr(raw_fields, name)) for name in STRING_FIELDS}
    result["width"] = _wrap_dimension(raw_fields.width_value, raw_fields.width_unit)
    result["height"] = _wrap_dimension(raw_fields.height_value, raw_fields.height_unit)
    return result
