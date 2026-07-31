# app/api/owner_ai_logs.py
"""Anthony's AI audit trail (maps branch) — a read-only view of every LLM call
the system made on each job: what was sent in, what came back, how long it
took, token usage, and whether it succeeded. Owner-only (require_owner) —
the same "only Anthony sees this" gate as the job map. The rows themselves are
written by app/ai/llm.py from inside chat_completion / vision_completion."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_owner
from app.db import get_db
from app.models import AiCallLog, Worker

router = APIRouter(prefix="/owner/ai-logs", tags=["owner-ai-logs"])


class AiLogOut(BaseModel):
    id: str
    quote_id: str | None = None
    purpose: str
    model: str
    input_text: str | None = None
    output_text: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    success: bool
    error: str | None = None
    created_at: str


class PurposeCount(BaseModel):
    purpose: str
    count: int
    failures: int


class AiLogsResponse(BaseModel):
    total: int
    failures: int
    by_purpose: list[PurposeCount]
    logs: list[AiLogOut]


@router.get("", response_model=AiLogsResponse)
def list_ai_logs(
    quote_id: str | None = Query(default=None, description="Filter to one job's AI calls"),
    purpose: str | None = Query(default=None, description="Filter to one pipeline step, e.g. extract_email"),
    limit: int = Query(default=200, ge=1, le=500),
    owner: Worker = Depends(require_owner),
    db: Session = Depends(get_db),
) -> dict:
    """The AI logs tab — every LLM call, optionally scoped to one job. The
    summary (total, failures, per-purpose counts) covers the whole audit
    table so Anthony sees overall call volume, while `logs` is the
    filtered/sliced recent slice for the list view."""
    base = select(AiCallLog)
    if quote_id is not None:
        base = base.where(AiCallLog.quote_id == quote_id)
    if purpose is not None:
        base = base.where(AiCallLog.purpose == purpose)

    rows = db.scalars(base.order_by(AiCallLog.created_at.desc()).limit(limit)).all()

    # Aggregate over the FULL table (not the filtered slice) for the volume
    # numbers — Anthony wants total call count, not "count of the last 200".
    total = db.scalar(select(func.count()).select_from(AiCallLog)) or 0
    failures = db.scalar(select(func.count()).select_from(AiCallLog).where(AiCallLog.success.is_(False))) or 0
    purpose_rows = db.execute(
        select(
            AiCallLog.purpose,
            func.count().label("count"),
            func.count().filter(AiCallLog.success.is_(False)).label("failures"),
        ).group_by(AiCallLog.purpose)
    ).all()

    return {
        "total": total,
        "failures": failures,
        "by_purpose": [
            {"purpose": p, "count": c, "failures": f} for p, c, f in purpose_rows
        ],
        "logs": [
            {
                "id": row.id,
                "quote_id": row.quote_id,
                "purpose": row.purpose,
                "model": row.model,
                "input_text": row.input_text,
                "output_text": row.output_text,
                "latency_ms": row.latency_ms,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "success": row.success,
                "error": row.error,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }