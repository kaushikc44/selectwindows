# app/engine/merge.py
"""Deterministic cross-source merge — no LLM involved. Combines candidate
readings/fields from multiple extractors (form/AR/sketch/email/rep-reply)
into one final value per field, per the precedence rule in
select-windows-domain-brief.md: multiple same-precedence readings that
disagree within tolerance resolve to their MINIMUM (never silently averaged
or maxed — always visibly flagged, see ExtractionItem.dimensions_multi_reading),
same trade convention as the paper form's multi-point width/height readings —
size to the tightest constraint so the manufactured unit is never too big to
fit an imprecise opening. Readings that disagree beyond tolerance are a
genuine conflict that needs a human, never resolved automatically."""

from dataclasses import dataclass

from app.schemas import DimensionReading, FieldValue

# manual_entry ranks highest: a tradie typing in a tape-measure reading in
# the worker app is a deliberate, direct human measurement, not an estimate
# to be second-guessed by an AR photo. rep_reply ranks next: it only exists
# because we explicitly asked the rep to resolve a gap, so it's authoritative
# for whatever field it answers.
SOURCE_PRECEDENCE = ["manual_entry", "rep_reply", "form_field", "ar_overlay", "sketch_annotation", "email_body"]

# Beyond this, two readings are a genuine conflict (needs_manual / a retake
# request) — never averaged. Raised from 5% after real AR-overlay pairs on
# the same edge came in ~8.5% apart (documented AR error is ±20mm, so some
# spread between separate photos of the same edge is expected, not a sign
# something's actually wrong).
CONFLICT_THRESHOLD_PCT = 15.0


class DimensionConflictError(Exception):
    """Raised when two candidate readings for the same dimension disagree by
    more than CONFLICT_THRESHOLD_PCT. The caller must treat this as
    needs_manual — never average or silently pick one."""

    def __init__(self, readings: list[DimensionReading]):
        self.readings = readings
        super().__init__(f"dimension readings disagree by >{CONFLICT_THRESHOLD_PCT}%: {readings}")


@dataclass
class ResolvedDimension:
    value_mm: int
    source: str
    # True when value_mm is the MINIMUM of multiple same-precedence readings
    # that disagreed (within tolerance) rather than a single raw reading —
    # callers must surface this on the item, never let it pass silently as
    # if it were a direct measurement.
    multi_reading: bool = False


def _max_pairwise_disagreement_pct(values: list[int]) -> float:
    lo, hi = min(values), max(values)
    if lo == 0:
        return float("inf") if hi else 0.0
    return (hi - lo) / lo * 100


def _rank(source: str) -> int:
    return SOURCE_PRECEDENCE.index(source) if source in SOURCE_PRECEDENCE else len(SOURCE_PRECEDENCE)


def resolve_dimension(readings: list[DimensionReading]) -> ResolvedDimension | None:
    """Applies source precedence with a conflict guard. None if there are no
    readings at all. Raises DimensionConflictError if any two candidate
    values disagree by more than CONFLICT_THRESHOLD_PCT.

    Within that threshold, multiple readings that share the single highest-
    precedence tier present (e.g. two ar_overlay photos of the same edge, or
    the paper form's multi-point width/height readings) but still disagree
    resolve to their MINIMUM — sizing to the tightest constraint, standard
    trade practice for a replacement unit. A lower-precedence reading is
    still never blended in, it's simply outranked as before."""
    if not readings:
        return None

    values = [r.value_mm for r in readings]
    if len(values) > 1 and _max_pairwise_disagreement_pct(values) > CONFLICT_THRESHOLD_PCT:
        raise DimensionConflictError(readings)

    top_rank = min(_rank(r.source) for r in readings)
    top_tier = [r for r in readings if _rank(r.source) == top_rank]

    if len(top_tier) > 1 and len({r.value_mm for r in top_tier}) > 1:
        min_value = min(r.value_mm for r in top_tier)
        return ResolvedDimension(value_mm=min_value, source=top_tier[0].source, multi_reading=True)

    best = min(readings, key=lambda r: _rank(r.source))
    return ResolvedDimension(value_mm=best.value_mm, source=best.source)


def merge_field_value(candidates: list[FieldValue]) -> FieldValue:
    """Simple precedence pick for non-dimension fields (no numeric conflict
    check — these aren't comparable the way dimensions are). A candidate
    with source="missing" is never chosen over a real one."""
    present = [c for c in candidates if c.source != "missing" and c.value is not None]
    if not present:
        return FieldValue(value=None, source="missing", confidence=None)
    return min(present, key=lambda c: _rank(c.source))
