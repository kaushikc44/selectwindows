# app/ai/extract.py
import json
import logging
from dataclasses import dataclass

from pydantic import ValidationError

from app.ai.llm import LLMUnavailable, vision_completion
from app.schemas import ExtractionResultV2

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT_TEMPLATE = """You are digitizing a window/door installation quote request for \
Select Window Installations (Brookvale, Sydney).

A field worker has emailed one or more photos taken on-site with an iPhone LiDAR \
measuring app. Each photo shows a window or door opening with the measurement \
overlaid digitally/AR-rendered directly on the image (not a physical tape measure). \
The worker also wrote a plain-language description of what's needed in the email \
body, given below.

EMAIL BODY TEXT:
---
{body_text}
---

Your job:
1. For each photo, read the digital LiDAR measurement overlay. It may be shown in \
metres, centimetres, millimetres, or inches — convert whatever unit is shown to \
integer MILLIMETRES. height_mm and width_mm must each be an integer between 100 and 6000.
2. Read the email body text to determine, for each item: room, product type, \
material, quantity, and any other detail mentioned.
3. Correlate photos with text-mentioned items into one items array — match by \
order and by content (e.g. if the text says "bi-fold window, laundry" and there is \
one photo, that photo is the bi-fold window's measurement).
4. product_type must be exactly one of: awning, casement, sliding, double_hung, \
louvre, powerlouvre, bi_fold, sashless, gas_strut, stacking, hinged, cedar_entry, \
unknown. material must be exactly one of: aluminium, timber, unknown. Use "unknown" \
rather than guessing if the text doesn't clearly say.
5. qty defaults to 1 if not stated, but you MUST set qty_defaulted=true and lower \
that item's confidence when you default it.
6. description_raw must be the exact relevant text/phrase from the email body for \
that item (or a short factual note if there was none).
7. Office-side header fields (client name/address, job number, rep, wind rating, \
water rating, reveal linings, etc.) are almost never present in this kind of \
on-site capture. Only fill a header field if the email text explicitly states it — \
otherwise leave it null (or "unmarked" for the rating/yes-no fields). NEVER guess \
a header field.
8. Same rule for installation fields (building type, construction, floor level, \
brick removal, scaffold, etc.) — only fill from explicit text, "unmarked"/null \
otherwise.
9. confidence (0.0-1.0) reflects how certain you are of that item's measurements \
and product/material identification. overall_confidence reflects the whole \
extraction. List any critical field you could not read at all in unreadable_fields.

Return ONLY JSON matching this exact schema, no markdown fences, no extra prose:

{{"header": {{"client_name": null, "client_address": null, "contact_name": null,
"phone": null, "email": null, "job_no": null, "rep": null, "date": null,
"delivery_address": null, "colour": null, "glass": null,
"wind_rating": "unmarked", "water_rating": "unmarked", "vent_locks": "unmarked",
"acoustic_seals": "unmarked", "sump_sills": "unmarked",
"reveal_28": {{"selected": false, "species": "unmarked", "defin": "unmarked"}},
"reveal_45": {{"selected": false, "species": "unmarked", "defin": "unmarked"}}}},
"items": [{{"item_no": 1, "room": null, "qty": 1, "qty_defaulted": false,
"description_raw": "exact text", "product_type": "bi_fold", "material": "aluminium",
"height_mm": 0, "width_mm": 0, "screen": "unmarked", "confidence": 0.0}}],
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


def _parse(raw_text: str) -> ExtractionResultV2:
    # strict=False: the model sometimes echoes multi-line email text into a
    # string field (e.g. notes) with a literal newline instead of an escaped
    # \n, which strict JSON parsing would otherwise reject outright.
    payload = json.loads(raw_text, strict=False)
    return ExtractionResultV2.model_validate(payload)


def extract_quote(images: list[tuple[bytes, str]], body_text: str) -> ExtractionOutcome:
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(body_text=body_text or "(no text in email body)")

    try:
        raw_text = vision_completion(images, prompt, purpose="extract")
    except LLMUnavailable as exc:
        logger.error("Vision extraction unavailable: %s", exc)
        return ExtractionOutcome(result=None, needs_manual=True, reason="llm_unavailable")

    try:
        result = _parse(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Extraction JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = vision_completion(images, repair_prompt, purpose="extract_repair")
            result = _parse(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Extraction repair retry failed: %s", retry_exc)
            return ExtractionOutcome(result=None, needs_manual=True, reason="unparseable_extraction")

    if result.needs_manual:
        return ExtractionOutcome(result=result, needs_manual=True, reason="low_confidence_or_unreadable")
    return ExtractionOutcome(result=result, needs_manual=False)
