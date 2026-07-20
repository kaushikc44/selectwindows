# app/main.py
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.db import create_all, get_db
from app.models import Quote, QuoteStatus
from app.output.approval import InvalidApprovalToken, verify_token
from app.schemas import QuoteOut


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_all()
    yield


app = FastAPI(title="GlassQuote PoC", lifespan=lifespan)


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
