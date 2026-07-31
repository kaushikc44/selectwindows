# app/ai/extract_form.py
"""Extraction scoped to classified Select Windows paper-form pages
(form_page1 / form_continuation / form_installation) — see
select-windows-domain-brief.md for the field-by-field form layout. Unlike
extract_ar.py, the form states H/W directly in mm, so no unit conversion is
needed here."""

import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.schemas import DimensionReading, ExtractionResultV2

logger = logging.getLogger(__name__)

FORM_EXTRACTION_PROMPT_TEMPLATE = """You are digitizing photos of the Select Window Installations \
paper quote form (Brookvale, Sydney) — one or more of: page 1 (header + items table), \
page 2 (continuation items table), page 3 (installation details).

Any free text the rep also wrote in the email body is given below for extra context \
(e.g. clarifying an ambiguous item) — the form itself is the authoritative source.

EMAIL BODY TEXT:
---
{body_text}
---

Your job:
1. Header circled-option fields (wind rating, water rating, vent locks, acoustic \
seals, sump sills, reveal linings) — report exactly which value is circled, or \
"unmarked" if none is clearly circled. NEVER guess.
2. Items table: H (height) comes before W (width) on the form. Both are already in \
MILLIMETRES on the form — read the printed/written number directly, integer between \
100 and 6000. qty defaults to 1 if blank, but you MUST set qty_defaulted=true and \
lower that item's confidence when you default it.
3. product_type must be exactly one of: awning, casement, sliding, double_hung, \
louvre, powerlouvre, bi_fold, sashless, gas_strut, stacking, hinged, cedar_entry, \
unknown. material must be exactly one of: aluminium, timber, unknown. Use "unknown" \
rather than guessing if the Description cell doesn't clearly say. If the Description \
cell contains a config-code shorthand (e.g. "BFW-3", "CA-L", "SL2"), also set \
config_code to that exact code.
4. Page 3 installation fields — only fill from what's actually marked/written on the \
form; "unmarked"/null otherwise. NEVER guess.
5. confidence (0.0-1.0) reflects how certain you are of that item's measurements and \
product/material identification. overall_confidence reflects the whole extraction. \
List any critical field you could not read at all in unreadable_fields.

Return ONLY JSON matching this exact schema, no markdown fences, no extra prose:

{{"header": {{"client_name": null, "client_address": null, "contact_name": null,
"phone": null, "email": null, "job_no": null, "rep": null, "date": null,
"delivery_address": null, "colour": null, "glass": null,
"wind_rating": "unmarked", "water_rating": "unmarked", "vent_locks": "unmarked",
"acoustic_seals": "unmarked", "sump_sills": "unmarked",
"reveal_28": {{"selected": false, "species": "unmarked", "defin": "unmarked"}},
"reveal_45": {{"selected": false, "species": "unmarked", "defin": "unmarked"}}}},
"items": [{{"item_no": 1, "room": null, "qty": 1, "qty_defaulted": false,
"description_raw": "exact handwriting", "product_type": "bi_fold", "material": "aluminium",
"config_code": null, "height_mm": 0, "width_mm": 0, "screen": "unmarked", "confidence": 0.0}}],
"installation": {{"building_type": null, "construction": null, "remove_existing": null,
"floor_level": null, "brick_removal_m2": null, "scaffold": "unmarked", "men_reqd": null,
"time_estimate_hrs": null, "asbestos": "unmarked", "notes": ""}},
"overall_confidence": 0.0, "unreadable_fields": []}}
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


@dataclass
class ExtractionOutcome:
    result: ExtractionResultV2 | None
    needs_manual: bool
    reason: str = ""
    # Populated only when reason starts with "dimension_conflict_" — the
    # specific readings that disagreed, so a retry request to the rep can
    # name the actual conflicting values instead of just the axis/item.
    conflict_readings: list[DimensionReading] | None = None


def _parse(raw_text: str) -> ExtractionResultV2:
    # strict=False: the model sometimes echoes multi-line email text into a
    # string field with a literal newline instead of an escaped \n, which
    # strict JSON parsing would otherwise reject outright.
    payload = json.loads(raw_text, strict=False)
    result = ExtractionResultV2.model_validate(payload)
    _stamp_form_field_readings(result)
    return result


def _stamp_form_field_readings(result: ExtractionResultV2) -> None:
    """The paper form states H/W directly, so each item's resolved dimension
    IS the form_field reading — record it as such for merge.py/audit."""
    for item in result.items:
        if not item.height_readings:
            item.height_readings = [
                DimensionReading(value_mm=item.height_mm, source="form_field", confidence=item.confidence)
            ]
        if not item.width_readings:
            item.width_readings = [
                DimensionReading(value_mm=item.width_mm, source="form_field", confidence=item.confidence)
            ]


def extract_form(images: list[tuple[bytes, str]], body_text: str) -> ExtractionOutcome:
    prompt = FORM_EXTRACTION_PROMPT_TEMPLATE.format(body_text=body_text or "(no text in email body)")

    try:
        raw_text = vision_completion(images, prompt)
    except LLMUnavailable as exc:
        logger.error("Form extraction unavailable: %s", exc)
        return ExtractionOutcome(result=None, needs_manual=True, reason="llm_unavailable")

    try:
        result = _parse(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Form extraction JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = vision_completion(images, repair_prompt)
            result = _parse(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Form extraction repair retry failed: %s", retry_exc)
            return ExtractionOutcome(result=None, needs_manual=True, reason="unparseable_extraction")

    if result.needs_manual:
        return ExtractionOutcome(result=result, needs_manual=True, reason="low_confidence_or_unreadable")
    return ExtractionOutcome(result=result, needs_manual=False)
