# app/ai/extract_ar_field.py
"""Single-photo, single-axis AR reading extraction for the worker app's
per-field capture flow (one dedicated photo slot per dimension). Unlike
extract_ar.py's grouped multi-photo extraction — built to compensate for an
email photo's axis being ambiguous and item boundaries being unknown — the
app already tells the backend which axis this photo is for and which item
it belongs to, so there's nothing to infer or group: no axis guessing, no
"full" vs "partial" segment concept (that existed only to cover for not
knowing item/field boundaries). Same "LLM reports raw value+unit+confidence,
never converts units itself" boundary as every other extractor in app/ai/."""

import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.engine.units import UnknownUnitError, normalize_to_mm

logger = logging.getLogger(__name__)

FIELD_EXTRACTION_PROMPT_TEMPLATE = """This photo was taken specifically to measure the {axis} of a \
window or door opening, using an iPhone AR/LiDAR measuring app (digital measurement "pills" \
overlaid on the photo, e.g. "79 cm", "1.48 m").

Find the pill that measures the opening's {axis} and report its raw numeric value and unit \
EXACTLY as shown (do not convert units yourself). If more than one pill is visible, pick the one \
that best represents the {axis} of the opening shown — not a wall, room, or unrelated measurement.

Also give a genuine confidence score (0.0-1.0) based on how clearly you can actually read the \
digits in the photo — crisp, sharp, unobstructed text should score high (0.85-1.0); small, \
blurry, low-contrast, or partially obscured text should score lower. This must reflect your real \
assessment of THIS image, not a placeholder — never default to 0.0 unless the digits are \
genuinely illegible.

If no relevant measurement pill is visible at all, set found to false and omit raw_value/raw_unit.

Return ONLY JSON, no markdown fences, no prose:
{{"found": true, "raw_value": 79.0, "raw_unit": "cm", "confidence": 0.9}}
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


class _RawFieldReading(BaseModel):
    found: bool = True
    raw_value: float | None = None
    raw_unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ARFieldReading(BaseModel):
    value_mm: int
    confidence: float


def _parse(raw_text: str) -> _RawFieldReading:
    return _RawFieldReading.model_validate(json.loads(raw_text, strict=False))


def extract_single_reading(
    image_bytes: bytes, mime_type: str, axis: Literal["width", "height"]
) -> ARFieldReading | None:
    """Reads the one AR-overlay pill this photo was taken to capture. Returns
    None if the LLM is unavailable, the reading can't be parsed after one
    repair retry, no relevant pill was found, or the unit is unrecognized —
    the caller (the photo-upload endpoint) treats None as "ask the worker to
    retake this photo", never a silent guess."""
    prompt = FIELD_EXTRACTION_PROMPT_TEMPLATE.format(axis=axis)

    try:
        raw_text = vision_completion([(image_bytes, mime_type)], prompt, purpose="extract_ar_field")
    except LLMUnavailable as exc:
        logger.error("Single-field AR extraction unavailable: %s", exc)
        return None

    try:
        parsed = _parse(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Single-field AR extraction JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = vision_completion([(image_bytes, mime_type)], repair_prompt, purpose="extract_ar_field_repair")
            parsed = _parse(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Single-field AR extraction repair retry failed: %s", retry_exc)
            return None

    if not parsed.found or parsed.raw_value is None or not parsed.raw_unit:
        return None

    try:
        value_mm = normalize_to_mm(parsed.raw_value, parsed.raw_unit)
    except UnknownUnitError:
        logger.warning("Single-field AR reading has unrecognized unit %r", parsed.raw_unit)
        return None

    return ARFieldReading(value_mm=value_mm, confidence=parsed.confidence)
