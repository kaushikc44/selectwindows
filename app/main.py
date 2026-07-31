# app/main.py
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.owner_quotes import router as owner_quotes_router
from app.api.sales_quotes import router as sales_quotes_router
from app.api.sales_quotes import tradies_router as sales_tradies_router
from app.api.worker_quotes import preview_router as worker_preview_router
from app.api.worker_quotes import router as worker_quotes_router
from app.auth import create_access_token, verify_password
from app.db import create_all, get_db
from app.models import Quote, QuoteStatus, Worker
from app.output.approval import InvalidApprovalToken, verify_token
from app.schemas import QuoteOut, WorkerTokenOut


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(title="GlassQuote PoC", lifespan=lifespan)
app.include_router(worker_quotes_router)
app.include_router(worker_preview_router)
app.include_router(owner_quotes_router)
app.include_router(sales_quotes_router)
app.include_router(sales_tradies_router)


@app.post("/auth/login", response_model=WorkerTokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> dict:
    worker = db.scalar(select(Worker).where(Worker.username == form.username))
    if worker is None or not worker.is_active or not verify_password(form.password, worker.hashed_password):
        raise HTTPException(status_code=401, detail="incorrect username or password")
    return {"access_token": create_access_token(worker.id), "token_type": "bearer", "role": worker.role.value}


@app.get("/quotes/{quote_id}", response_model=QuoteOut)
def get_quote(quote_id: str, db: Session = Depends(get_db)) -> Quote:
    quote = db.get(Quote, quote_id)
    if quote is None:
        raise HTTPException(status_code=404, detail="quote not found")
    return quote


def _apply_token_action(
    token: str, *, expected_action: str, new_status: QuoteStatus, db: Session
) -> dict:
    try:
        payload = verify_token(token)
    except InvalidApprovalToken as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if payload.get("action") != expected_action:
        raise HTTPException(status_code=400, detail="token/action mismatch")

    quote = db.get(Quote, payload["quote_id"])
    if quote is None:
        raise HTTPException(status_code=404, detail="quote not found")

    if quote.token_used:
        raise HTTPException(status_code=410, detail="token already used")

    expected_token = quote.approve_token if expected_action == "approve" else quote.reject_token
    if token != expected_token:
        raise HTTPException(status_code=400, detail="token no longer valid for this quote")

    if quote.status != QuoteStatus.pending_approval:
        raise HTTPException(
            status_code=409, detail=f"quote is in status {quote.status.value}, not pending_approval"
        )

    quote.status = new_status
    quote.token_used = True
    db.commit()
    return {"quote_id": quote.id, "status": quote.status.value}


@app.get("/approve/{token}")
def approve_quote(token: str, db: Session = Depends(get_db)) -> dict:
    return _apply_token_action(
        token, expected_action="approve", new_status=QuoteStatus.approved, db=db
    )


@app.get("/reject/{token}")
def reject_quote(token: str, db: Session = Depends(get_db)) -> dict:
    return _apply_token_action(
        token, expected_action="reject", new_status=QuoteStatus.rejected, db=db
    )
