# app/api/sales_quotes.py
"""Job creation and scheduling for the Sales role (Phase F) — every job now
originates here: Sales enters the customer's details, assigns a tradie, and
sets a visit date. The tradie then completes the rest (property/compliance
details, items, measurements) on site via app/api/worker_quotes.py, and
submits as before. Sales sees scheduling status only — customer, assigned
tradie, date, status, and the reschedule/missed-visit comment thread — never
pricing, flags, or materials (that stays Anthony-only via
app/api/owner_quotes.py, unchanged by this file)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_sales
from app.db import get_db
from app.models import ApprovalComment, Quote, QuoteHeader, QuoteStatus, Worker, WorkerRole
from app.schemas import RESCHEDULE_REASON_LABELS, RescheduleReason
from app.workers.persist import log_event

router = APIRouter(prefix="/sales/quotes", tags=["sales-quotes"])
tradies_router = APIRouter(prefix="/sales", tags=["sales-quotes"])

# A job can be rescheduled out of either of these — "scheduled" (just
# changing the date before the visit happens) or "missed" (the visit didn't
# happen, this is what brings it back onto the schedule).
_RESCHEDULABLE_STATUSES = (QuoteStatus.scheduled, QuoteStatus.missed)


class NewSalesJobRequest(BaseModel):
    client_name: str
    client_address: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    job_no: str | None = None
    assigned_tradie_id: str
    scheduled_date: str


class NewSalesJobResponse(BaseModel):
    quote_id: str
    status: str


class SalesJobSummary(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    assigned_tradie_name: str | None = None
    scheduled_date: str | None = None
    created_at: str


class SalesCommentOut(BaseModel):
    id: str
    author: str
    body: str
    action: str | None = None
    created_at: str


class SalesJobDetail(BaseModel):
    quote_id: str
    status: str
    client_name: str | None = None
    client_address: str | None = None
    contact_name: str | None = None
    phone: str | None = None
    email: str | None = None
    job_no: str | None = None
    assigned_tradie_id: str | None = None
    assigned_tradie_name: str | None = None
    scheduled_date: str | None = None
    comments: list[SalesCommentOut] = Field(default_factory=list)


class RescheduleRequest(BaseModel):
    new_date: str
    reason: RescheduleReason
    other_detail: str | None = None


class RescheduleResponse(BaseModel):
    quote_id: str
    status: str
    scheduled_date: str


class TradieOut(BaseModel):
    id: str
    name: str


def _get_schedulable_quote(quote_id: str, db: Session) -> Quote:
    """No tradie/sales ownership restriction — any Sales account can see and
    reschedule any job (dispatch is a shared queue, not per-rep-scoped like
    the tradie's own job list). Restricted only to quotes that actually went
    through this scheduling flow (have an assigned tradie)."""
    quote = db.get(Quote, quote_id)
    if quote is None or quote.assigned_tradie_id is None:
        raise HTTPException(status_code=404, detail="quote not found")
    return quote


def _job_to_summary(quote: Quote) -> dict:
    return {
        "quote_id": quote.id,
        "status": quote.status.value,
        "client_name": quote.header.client_name if quote.header else None,
        "assigned_tradie_name": quote.assigned_tradie.name if quote.assigned_tradie else None,
        "scheduled_date": quote.scheduled_date,
        "created_at": quote.created_at.isoformat(),
    }


@router.post("", response_model=NewSalesJobResponse)
def create_sales_job(
    body: NewSalesJobRequest, sales: Worker = Depends(require_sales), db: Session = Depends(get_db)
) -> dict:
    tradie = db.get(Worker, body.assigned_tradie_id)
    if tradie is None or tradie.role != WorkerRole.tradie:
        raise HTTPException(status_code=422, detail="assigned_tradie_id is not a valid tradie account")

    quote = Quote(
        status=QuoteStatus.scheduled,
        created_by_worker_id=sales.id,
        assigned_tradie_id=tradie.id,
        scheduled_date=body.scheduled_date,
    )
    db.add(quote)
    db.flush()

    quote.header = QuoteHeader(
        client_name=body.client_name,
        client_address=body.client_address,
        contact_name=body.contact_name,
        phone=body.phone,
        email=body.email,
        job_no=body.job_no,
    )

    log_event(db, quote.id, "sales_job_created", f"assigned to {tradie.name}")
    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value}


@router.get("", response_model=list[SalesJobSummary])
def list_sales_jobs(sales: Worker = Depends(require_sales), db: Session = Depends(get_db)) -> list[dict]:
    """Every job with a schedule, system-wide — not scoped to the Sales
    account that created it, since dispatch is a shared view across the
    team, not a personal queue."""
    quotes = db.scalars(
        select(Quote).where(Quote.assigned_tradie_id.is_not(None)).order_by(Quote.created_at.desc())
    )
    return [_job_to_summary(q) for q in quotes]


@router.get("/{quote_id}", response_model=SalesJobDetail)
def get_sales_job(quote_id: str, sales: Worker = Depends(require_sales), db: Session = Depends(get_db)) -> dict:
    quote = _get_schedulable_quote(quote_id, db)
    header = quote.header
    return {
        "quote_id": quote.id,
        "status": quote.status.value,
        "client_name": header.client_name if header else None,
        "client_address": header.client_address if header else None,
        "contact_name": header.contact_name if header else None,
        "phone": header.phone if header else None,
        "email": header.email if header else None,
        "job_no": header.job_no if header else None,
        "assigned_tradie_id": quote.assigned_tradie_id,
        "assigned_tradie_name": quote.assigned_tradie.name if quote.assigned_tradie else None,
        "scheduled_date": quote.scheduled_date,
        "comments": [
            {
                "id": c.id,
                "author": c.author,
                "body": c.body,
                "action": c.action,
                "created_at": c.created_at.isoformat(),
            }
            for c in quote.approval_comments
        ],
    }


@router.post("/{quote_id}/reschedule", response_model=RescheduleResponse)
def reschedule_job(
    quote_id: str,
    body: RescheduleRequest,
    sales: Worker = Depends(require_sales),
    db: Session = Depends(get_db),
) -> dict:
    quote = _get_schedulable_quote(quote_id, db)
    if quote.status not in _RESCHEDULABLE_STATUSES:
        raise HTTPException(
            status_code=409, detail=f"quote is in status {quote.status.value}, cannot be rescheduled"
        )

    reason_text = RESCHEDULE_REASON_LABELS[body.reason]
    if body.reason == "other" and body.other_detail:
        reason_text = f"{reason_text}: {body.other_detail}"

    quote.scheduled_date = body.new_date
    quote.status = QuoteStatus.scheduled
    db.add(ApprovalComment(quote_id=quote.id, author="sales", body=reason_text, action="reschedule"))
    log_event(db, quote.id, "sales_job_rescheduled", body.new_date)
    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value, "scheduled_date": quote.scheduled_date}


@tradies_router.get("/tradies", response_model=list[TradieOut])
def list_tradies(sales: Worker = Depends(require_sales), db: Session = Depends(get_db)) -> list[dict]:
    tradies = db.scalars(
        select(Worker).where(Worker.role == WorkerRole.tradie, Worker.is_active.is_(True)).order_by(Worker.name)
    )
    return [{"id": t.id, "name": t.name} for t in tradies]
