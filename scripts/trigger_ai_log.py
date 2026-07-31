"""Trigger one real approval-agent AI call on a pending job so Anthony's AI
Logs (maps branch) has a genuine row — input = lessons + quote, output = the
agent's notes — demonstrating the audit trail end-to-end. Run inside the app
container so DATABASE_URL/LLM config are live."""
from sqlalchemy import select

from app.ai.approval_agent import check_against_lessons
from app.db import SessionLocal
from app.models import LearnedLesson, Quote, QuoteStatus

db = SessionLocal()
try:
    quote = db.scalar(
        select(Quote).where(Quote.status == QuoteStatus.pending_approval).join(Quote.header)
    )
    if quote is None:
        print("no pending_approval quote found")
    else:
        lessons = list(db.scalars(select(LearnedLesson)))
        notes = check_against_lessons(quote, lessons)
        print(f"quote {quote.id} ({quote.header.client_name if quote.header else '?'}):")
        print(f"  lessons loaded: {len(lessons)}")
        print(f"  agent notes: {notes}")
finally:
    db.close()