# app/ai/extract.py
import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.models import GlassType
from app.schemas import ExtractionResult

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a glass measurement extraction assistant.
Read the attached photo of hand-written glass panel measurements and return ONLY JSON
matching this exact schema, with no markdown fences and no extra prose:

{"panels": [{"label": "W1", "width_mm": 1200, "height_mm": 900, "qty": 1,
"glass_type": "toughened|clear_float|laminated|double_glazed|unknown", "confidence": 0.0}],
"notes": "anything else written in the photo"}

Rules: width_mm and height_mm are integers in millimetres between 100 and 6000.
qty is an integer >= 1. confidence is between 0.0 and 1.0, reflecting how legible
the handwriting/markings were for that panel. If glass_type is not stated, use "unknown".
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


@dataclass
class ExtractionOutcome:
    result: ExtractionResult | None
    needs_manual: bool
    reason: str = ""


def _parse(raw_text: str) -> ExtractionResult:
    payload = json.loads(raw_text)
    return ExtractionResult.model_validate(payload)


def _apply_glass_type_defaults(result: ExtractionResult) -> ExtractionResult:
    for panel in result.panels:
        if panel.glass_type == GlassType.unknown.value:
            panel.glass_type = GlassType.clear_float.value
            panel.glass_type_flagged = True
    return result


def extract_panels(image_bytes: bytes, mime_type: str = "image/jpeg") -> ExtractionOutcome:
    try:
        raw_text = vision_completion(image_bytes, EXTRACTION_PROMPT, mime_type=mime_type)
    except LLMUnavailable as exc:
        logger.error("Vision extraction unavailable: %s", exc)
        return ExtractionOutcome(result=None, needs_manual=True, reason="llm_unavailable")

    try:
        result = _parse(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Extraction JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = vision_completion(image_bytes, repair_prompt, mime_type=mime_type)
            result = _parse(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Extraction repair retry failed: %s", retry_exc)
            return ExtractionOutcome(result=None, needs_manual=True, reason="unparseable_extraction")

    result = _apply_glass_type_defaults(result)
    if result.needs_manual:
        return ExtractionOutcome(result=result, needs_manual=True, reason="low_confidence_panel")
    return ExtractionOutcome(result=result, needs_manual=False)
