# app/ai/extract_ar.py
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.engine.units import UnknownUnitError, normalize_to_mm

logger = logging.getLogger(__name__)

AR_EXTRACTION_PROMPT = """This is a screenshot from an iPhone AR/LiDAR measuring app,
showing a photo of a window or door opening with digital measurement "pills"
overlaid on it (e.g. "79 cm", "1.48 m"). Read every pill visible.

For each pill: report the raw numeric value and unit EXACTLY as shown (do not
convert units yourself). If it's clear from arrows/labels/context whether a
pill measures the opening's width or height, set axis to "width" or "height";
if it's ambiguous, set axis to "unlabelled" — do not guess.

Also give a genuine confidence score (0.0-1.0) for each reading, based on how
clearly you can actually read the digits in the photo — crisp, sharp,
unobstructed text should score high (0.85-1.0); small, blurry, low-contrast,
or partially obscured text should score lower. This must reflect your real
assessment of THIS image, not a placeholder — never default to 0.0 unless the
digits are genuinely illegible.

Return ONLY JSON, no markdown fences, no prose:
{"readings": [{"raw_value": 79.0, "raw_unit": "cm", "axis": "width|height|unlabelled", "confidence": 0.9}]}
"""


class _RawPill(BaseModel):
    raw_value: float
    raw_unit: str
    axis: Literal["width", "height", "unlabelled"] = "unlabelled"
    # "full": this reading spans the item's whole edge (the normal case —
    # possibly confirmed by more than one photo showing the same value).
    # "partial": this reading is only ONE SECTION of a larger total span —
    # e.g. a wide sliding door opening split into a glazed section + a solid
    # infill panel side by side, sold/installed as one combined unit. Partial
    # readings on the same axis get summed (deterministic addition, never by
    # the model) instead of being checked for equality against each other.
    segment: Literal["full", "partial"] = "full"
    confidence: float = Field(ge=0.0, le=1.0)


class _RawARResult(BaseModel):
    readings: list[_RawPill] = Field(default_factory=list)


class ARReading(BaseModel):
    value_mm: int
    axis: Literal["width", "height", "unlabelled"]
    confidence: float


def extract_ar_readings(image_bytes: bytes, mime_type: str) -> list[ARReading]:
    """Reads AR-overlay pills from one photo. Unit conversion happens here in
    plain Python (app.engine.units), never by asking the LLM to do math."""
    try:
        raw = vision_completion([(image_bytes, mime_type)], AR_EXTRACTION_PROMPT)
    except LLMUnavailable as exc:
        logger.error("AR extraction unavailable: %s", exc)
        return []

    try:
        parsed = _RawARResult.model_validate(json.loads(raw, strict=False))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("AR extraction JSON invalid, skipping this image: %s", exc)
        return []

    readings = []
    for pill in parsed.readings:
        try:
            value_mm = normalize_to_mm(pill.raw_value, pill.raw_unit)
        except UnknownUnitError:
            logger.warning("AR pill has unrecognized unit %r, skipping", pill.raw_unit)
            continue
        readings.append(ARReading(value_mm=value_mm, axis=pill.axis, confidence=pill.confidence))
    return readings


# --- Grouped multi-photo extraction ---------------------------------------
# A single opening often can't be captured in one photo (an iPhone AR/LiDAR
# scan of a large window needs several shots to cover every edge), and one
# email can describe several distinct openings. Reading each photo in
# isolation and pooling every reading into one item conflates the two —
# this call sees every photo plus the email text together and does the
# room/item grouping itself, the same way extract_form.py already handles
# multi-page paper forms in one call.

GROUPED_EXTRACTION_PROMPT_TEMPLATE = """These are photos a field rep for Select Window \
Installations emailed in about one or more window/door openings. Each photo is either an \
iPhone AR/LiDAR measuring-app screenshot (digital measurement "pills" overlaid on the photo, \
e.g. "79 cm", "1.48 m") or a hand-drawn sketch with numbers written on it.

EMAIL BODY TEXT:
---
{body_text}
---

Your job:
1. First, look carefully at what EACH photo individually shows: is there visible hardware — \
hinges (= a hinged door), rollers/tracks (= sliding), louvre blades, or no operable hardware at \
all (= a fixed glass panel)? What's in the background? Are two sections framed together in the \
SAME overall frame/track, forming one continuous opening (e.g. a wide sliding door where part \
is glazed and part is a solid infill panel, side by side)? Two photos with different visible \
hardware AND clearly unrelated frames/locations show DIFFERENT physical items — do not merge \
those just because they were sent together. But two sections sharing the same frame/track and \
the same height, installed/ordered as one continuous span, are SECTIONS of ONE item, not two \
separate items.
2. GROUP the photos into ITEMS on that basis. Multiple photos of the SAME opening or the SAME \
multi-section span belong together as one item (very common: a large opening often needs \
several photos to capture every edge, since one AR shot can't always show the whole thing — \
expect to see the SAME reading value repeated across confirming photos of the same edge, and \
DIFFERENT width readings sharing the SAME height across the sections of one multi-section \
opening). A photo showing a genuinely unrelated opening — different frame, different room, no \
shared track/header — is a SEPARATE item. Use the email text's room mentions to guide grouping \
when given; otherwise group by the visual signals above.
3. For each item, report: room (from the text, or null if not stated), a short description of \
what's shown, distinguishing_features (what makes this item visually different from the OTHER \
items in this submission — null if there is only one item total), product_type_hint (see \
below), source_kind ("ar_overlay" if this item's photos are AR/LiDAR screenshots, \
"sketch_annotation" if they're hand-drawn sketches), and EVERY raw dimension reading found \
across that item's photos — value and unit EXACTLY as shown (do not convert units yourself). If \
it's clear whether a reading is the opening's width or height, set axis accordingly; otherwise \
"unlabelled" — do not guess.
4. segment: for each reading, set to "full" if it spans the item's WHOLE edge (the normal case), \
or "partial" ONLY if it's one of two-or-more genuinely separate, physically distinct sections — \
different frames/panels side by side, sold and installed as one combined unit (e.g. the glazed \
section's width and a solid infill panel's width, side by side) — do NOT add them together \
yourself, just tag them "partial" and report each raw value separately. Do NOT use "partial" for \
a single AR/LiDAR quadrilateral trace around ONE opening that shows both a top-edge and a \
bottom-edge measurement (or a left-edge and a right-edge) that are close but not identical — that \
is normal camera-angle imprecision on the SAME edge, not two sections. Tag both readings "full" \
on the same axis in that case; a small difference between them is expected and handled elsewhere.
5. product_type_hint: name THIS item's product type using one of these exact words if you can \
tell — from the photo's visible hardware, or from email text that unambiguously refers to THIS \
specific item (not a different item in the same submission) — windows: awning, casement, \
sliding, double hung, louvre, powerlouvre, bi-fold, sashless, gas strut; doors: sliding, \
stacking, bi-fold, hinged, cedar entry. Set to null if you cannot tell for THIS item — never \
copy a product type from email text that could equally describe a different item in this \
submission.
6. For hand-sketch photos, only read written numeric annotations — never interpret the drawn \
geometry itself.
7. confidence: for each reading, give a genuine score (0.0-1.0) for how clearly YOU can read \
those specific digits in that specific photo — crisp, sharp, unobstructed text scores high \
(0.85-1.0); small, blurry, low-contrast, angled, or partially obscured text scores lower. This \
must be your real assessment of this image, not a placeholder value — never default to 0.0 \
unless the digits are genuinely illegible.

Return ONLY JSON, no markdown fences, no prose:
{{"items": [{{"room": null, "description": "short description", "distinguishing_features": null,
"product_type_hint": null, "source_kind": "ar_overlay",
"readings": [{{"raw_value": 79.0, "raw_unit": "cm", "axis": "width|height|unlabelled",
"segment": "full|partial", "confidence": 0.9}}]}}]}}
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


class GroupedItemReadings(BaseModel):
    room: str | None = None
    description: str | None = None
    distinguishing_features: str | None = None
    product_type_hint: str | None = None
    source_kind: Literal["ar_overlay", "sketch_annotation"] = "ar_overlay"
    readings: list[_RawPill] = Field(default_factory=list)


class GroupedExtractionResult(BaseModel):
    items: list[GroupedItemReadings] = Field(default_factory=list)


def _parse_grouped(raw_text: str) -> GroupedExtractionResult:
    return GroupedExtractionResult.model_validate(json.loads(raw_text, strict=False))


def extract_grouped_readings(images: list[tuple[bytes, str]], body_text: str) -> GroupedExtractionResult:
    """One vision call covering every AR/sketch photo in the email plus the
    body text, grouped into items. Still returns only raw {value, unit}
    pairs per reading — grouping is a classification decision the model
    makes, unit conversion stays deterministic (app.engine.units)."""
    if not images:
        return GroupedExtractionResult(items=[])

    prompt = GROUPED_EXTRACTION_PROMPT_TEMPLATE.format(body_text=body_text or "(no text in email body)")

    try:
        raw_text = vision_completion(images, prompt)
    except LLMUnavailable as exc:
        logger.error("Grouped extraction unavailable: %s", exc)
        return GroupedExtractionResult(items=[])

    try:
        return _parse_grouped(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Grouped extraction JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = vision_completion(images, repair_prompt)
            return _parse_grouped(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Grouped extraction repair retry failed: %s", retry_exc)
            return GroupedExtractionResult(items=[])
