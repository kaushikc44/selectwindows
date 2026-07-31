# app/ai/classify.py
import json
import logging

from app.ai.llm import LLMUnavailable, vision_completion

logger = logging.getLogger(__name__)

VALID_LABELS = {
    "ar_measure",
    "form_page1",
    "form_continuation",
    "form_installation",
    "hand_sketch",
    "site_photo",
    "other",
}

CLASSIFY_PROMPT = """Classify this single photo into exactly one of these labels:

- ar_measure: an iPhone/AR measuring-app screenshot: a photo with digital
  measurement overlay "pills" on it (e.g. "79 cm", "1.48 m")
- form_page1: page 1 of the Select Windows paper quote form (header fields +
  an items table)
- form_continuation: page 2 of the paper form (continuation items table
  only, no header fields)
- form_installation: page 3 of the paper form (Installation Details /
  Materials & Costs)
- hand_sketch: a freehand hand-drawn sketch, possibly with numbers written
  on it, NOT the printed Select Windows form
- site_photo: a plain photo of a window/door/opening/building with no
  overlay and no form structure
- other: anything else, not related to a quote at all

Return ONLY JSON, no markdown fences, no prose: {"label": "one_of_the_above"}
"""


def classify_attachment(image_bytes: bytes, mime_type: str) -> str:
    try:
        raw = vision_completion([(image_bytes, mime_type)], CLASSIFY_PROMPT, purpose="classify")
    except LLMUnavailable as exc:
        logger.error("Classification unavailable, defaulting to 'other': %s", exc)
        return "other"

    try:
        payload = json.loads(raw, strict=False)
        label = payload.get("label") if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        label = None

    if label not in VALID_LABELS:
        logger.warning("Unrecognized classification label %r, defaulting to 'other'", label)
        return "other"
    return label
