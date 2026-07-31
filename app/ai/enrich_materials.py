# app/ai/enrich_materials.py
"""Interim, LLM-generated materials/parts estimate for a known product_type +
material combination — a deliberate, user-approved stand-in for real Tier-3
enrichment data until a RAG-backed knowledge base replaces it. Unlike
app/engine/enrich.py (pure deterministic YAML lookup, never touched by an
LLM), this module explicitly asks DeepSeek to guess a plausible parts
breakdown. Every caller MUST tag the result as an unverified AI estimate
(never presented like the real defaults.yaml placeholder data) — see
EnrichmentResult.source == "llm_estimate" in app/engine/enrich.py."""

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, chat_completion

logger = logging.getLogger(__name__)

MATERIAL_ESTIMATE_PROMPT_TEMPLATE = """A field rep for Select Window Installations (Sydney, \
Australia) needs a rough materials/parts estimate for a quote, before a real spec sheet is \
available. Give your best plausible guess for a typical Australian residential job — this is an \
interim estimate only, not a fabrication-ready bill of materials, so keep each list short (a \
handful of the most relevant items, not an exhaustive parts catalogue).

Product type: {product_type}
Frame material: {material}
Approximate size band: {size_band}
Glass hint (if any): {glass_hint}

Return ONLY JSON, no markdown fences, no prose:
{{"glass_spec": "short glass spec string, e.g. \\"6mm single toughened\\"",
"frame_components": ["short item", "..."],
"hardware": ["short item", "..."],
"sealant_and_fixings": ["short item", "..."],
"notes": "any short caveat, or null"}}
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


class MaterialEstimate(BaseModel):
    glass_spec: str
    frame_components: list[str] = Field(default_factory=list)
    hardware: list[str] = Field(default_factory=list)
    sealant_and_fixings: list[str] = Field(default_factory=list)
    notes: str | None = None


def _parse(raw_text: str) -> MaterialEstimate:
    return MaterialEstimate.model_validate(json.loads(raw_text, strict=False))


def generate_material_estimate(
    product_type: str, material: str, size_band: str, glass_hint: str | None = None
) -> MaterialEstimate | None:
    """Returns None on any failure (unavailable LLM, unparseable output after
    one repair retry) — callers must fall back to the deterministic
    enrich_item() lookup, never leave enrichment unset."""
    prompt = MATERIAL_ESTIMATE_PROMPT_TEMPLATE.format(
        product_type=product_type, material=material, size_band=size_band, glass_hint=glass_hint or "none stated"
    )

    try:
        raw_text = chat_completion([{"role": "user", "content": prompt}], purpose="enrich_materials")
    except LLMUnavailable as exc:
        logger.error("Material estimate unavailable: %s", exc)
        return None

    try:
        return _parse(raw_text)
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Material estimate JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = chat_completion([{"role": "user", "content": repair_prompt}], purpose="enrich_materials_repair")
            return _parse(repaired_text)
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Material estimate repair retry failed: %s", retry_exc)
            return None
