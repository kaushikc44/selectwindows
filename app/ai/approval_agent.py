# app/ai/approval_agent.py
"""v1 of the owner-review "learning" loop (see app/api/owner_quotes.py): no
embeddings or fine-tuning, just a growing list of Anthony's past
request_changes corrections (LearnedLesson rows), read as plain-text context
by one chat_completion call before a new quote reaches his queue. Always
surfaces a note for Anthony to see — this never auto-approves or auto-edits
anything (see the "always surface, Anthony clicks" v1 scoping decision)."""

import json
import logging

from pydantic import BaseModel, Field, ValidationError

from app.ai.llm import LLMUnavailable, chat_completion
from app.models import LearnedLesson, Quote

logger = logging.getLogger(__name__)

CHECK_PROMPT_TEMPLATE = """You're a junior assistant helping Anthony, the owner of an aluminium \
window/door installation business, review a quote before he approves it. Anthony has previously \
corrected similar quotes — here is everything he's taught you so far:

{lessons_text}

Here is the new quote to check:

{quote_text}

Does anything about this quote match a pattern Anthony has corrected before? Only flag a genuine \
match — if nothing in the lesson list is clearly relevant, say so. You are NOT deciding whether \
to approve this quote; you're only drafting a short note for Anthony pointing out anything that \
looks like a past issue, so he can double check before he approves it himself.

Return ONLY JSON, no markdown fences, no prose:
{{"notes": ["short note referencing what matched and why, one per relevant lesson"]}}
If nothing matches, return {{"notes": []}}.
"""

REPAIR_PROMPT_TEMPLATE = """Your previous response could not be parsed as valid JSON matching
the required schema. Error: {error}

Previous response:
{previous}

Reply again with ONLY the corrected JSON, no markdown fences, no prose."""


class _CheckResult(BaseModel):
    notes: list[str] = Field(default_factory=list)


def _quote_text(quote: Quote) -> str:
    lines: list[str] = []
    if quote.flags:
        for flag in json.loads(quote.flags):
            lines.append(f"- flag: {flag['message']}")
    for item in quote.items:
        detail = f"- item {item.item_no}: {item.product_type.value}, {item.material.value}"
        if item.sill_height_mm is not None:
            detail += f", sill height {item.sill_height_mm}mm"
        lines.append(detail)
    return "\n".join(lines) if lines else "(no items or flags)"


def _lessons_text(lessons: list[LearnedLesson]) -> str:
    return "\n".join(f"- when: {lesson.trigger_summary} | fix: {lesson.fix_summary}" for lesson in lessons)


def _parse(raw_text: str) -> _CheckResult:
    return _CheckResult.model_validate(json.loads(raw_text, strict=False))


def check_against_lessons(quote: Quote, lessons: list[LearnedLesson]) -> list[str]:
    """Returns [] on any failure (unavailable LLM, unparseable output after
    one repair retry), when there are no lessons yet, or when nothing
    relevant is found — callers must treat an empty list as "nothing to
    flag," never block approval-email sending on it."""
    if not lessons:
        return []

    prompt = CHECK_PROMPT_TEMPLATE.format(lessons_text=_lessons_text(lessons), quote_text=_quote_text(quote))

    try:
        raw_text = chat_completion(
            [{"role": "user", "content": prompt}], purpose="approval_lesson_check", quote_id=quote.id
        )
    except LLMUnavailable as exc:
        logger.error("Approval-agent lesson check unavailable: %s", exc)
        return []

    try:
        return _parse(raw_text).notes
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.warning("Approval-agent lesson check JSON invalid, attempting one repair retry: %s", exc)
        try:
            repair_prompt = REPAIR_PROMPT_TEMPLATE.format(error=exc, previous=raw_text)
            repaired_text = chat_completion(
                [{"role": "user", "content": repair_prompt}], purpose="approval_lesson_check_repair", quote_id=quote.id
            )
            return _parse(repaired_text).notes
        except (json.JSONDecodeError, ValidationError, LLMUnavailable) as retry_exc:
            logger.error("Approval-agent lesson check repair retry failed: %s", retry_exc)
            return []
