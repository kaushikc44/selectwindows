# app/ai/extract_sketch.py
"""Reads ONLY written numeric dimension annotations off a hand sketch crop —
never interprets the drawn geometry itself (per select-windows-domain-brief.md,
Phase 1 explicitly defers sketch-geometry interpretation). Unit conversion is
deterministic Python, same boundary as extract_ar.py."""

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.engine.units import UnknownUnitError, normalize_to_mm

logger = logging.getLogger(__name__)

SKETCH_EXTRACTION_PROMPT = """This is a photo of a freehand hand-drawn sketch, possibly with \
numbers written on it. Do NOT try to interpret the drawing itself (panel layout, opening \
direction, handing) — only read any numeric dimension annotations that were actually written \
on the page (e.g. "1200", "1.2m", "900mm").

For each number found, report the raw value and unit exactly as written (assume "mm" if no \
unit is shown and the number looks like it's already in millimetres, e.g. a number over 50).

Return ONLY JSON, no markdown fences, no prose:
{"readings": [{"raw_value": 1200.0, "raw_unit": "mm", "confidence": 0.0}]}
"""


class _RawAnnotation(BaseModel):
    raw_value: float
    raw_unit: str
    confidence: float = Field(ge=0.0, le=1.0)


class _RawSketchResult(BaseModel):
    readings: list[_RawAnnotation] = Field(default_factory=list)


class SketchAnnotation(BaseModel):
    value_mm: int
    confidence: float


def extract_sketch_annotations(image_bytes: bytes, mime_type: str) -> list[SketchAnnotation]:
    try:
        raw = vision_completion([(image_bytes, mime_type)], SKETCH_EXTRACTION_PROMPT, purpose="extract_sketch")
    except LLMUnavailable as exc:
        logger.error("Sketch annotation extraction unavailable: %s", exc)
        return []

    try:
        parsed = _RawSketchResult.model_validate(json.loads(raw, strict=False))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Sketch annotation JSON invalid, skipping this image: %s", exc)
        return []

    annotations = []
    for reading in parsed.readings:
        try:
            value_mm = normalize_to_mm(reading.raw_value, reading.raw_unit)
        except UnknownUnitError:
            logger.warning("Sketch annotation has unrecognized unit %r, skipping", reading.raw_unit)
            continue
        annotations.append(SketchAnnotation(value_mm=value_mm, confidence=reading.confidence))
    return annotations
