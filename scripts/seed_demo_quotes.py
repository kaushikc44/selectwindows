# scripts/seed_demo_quotes.py
"""Populates the worker app with a few realistic demo quotes, end-to-end
through the real pipeline functions (not fixtures) — so the owner-review
comment/learning loop (Phase E) and the Sales scheduling loop (Phase F) can
both actually be clicked through before either is wired into daily use.
Deterministic flags (app/engine/flags.py) already catch things like a low
safety-glass sill automatically, so the seeded owner "learning" thread here
is deliberately something no deterministic rule covers: a Strata building
needing a body-corporate-approval note.

Safe to re-run — creates new quotes each run (not deduplicated), but reuses
existing worker accounts by username. Approval emails are suppressed for
seeded quotes (this is demo data, not worth emailing); everything else in
the pipeline — pricing, enrichment, flags, the agent's lesson check — runs
for real, including real LLM calls where the pipeline normally makes them.
"""

from unittest.mock import patch

from app.auth import hash_password
from app.db import SessionLocal
from app.models import (
    ApprovalComment,
    Installation,
    Item,
    LearnedLesson,
    Material,
    ProductType,
    Quote,
    QuoteHeader,
    QuoteStatus,
    Worker,
    WorkerRole,
)
from app.workers.pipeline import process_worker_submission_pipeline

DEMO_TRADIE_USERNAME = "testworker"
DEMO_TRADIE_PASSWORD = "testpass123"
DEMO_OWNER_USERNAME = "anthony"
DEMO_OWNER_PASSWORD = "anthonypass123"
DEMO_SALES_USERNAME = "sales1"
DEMO_SALES_PASSWORD = "salespass123"


def _get_or_create_worker(db, username: str, name: str, password: str, *, role: WorkerRole) -> Worker:
    worker = db.query(Worker).filter_by(username=username).first()
    if worker:
        return worker
    worker = Worker(username=username, name=name, hashed_password=hash_password(password), role=role)
    db.add(worker)
    db.commit()
    print(f"created {role.value} login: {username} / {password}")
    return worker


def _build_quote(db, tradie: Worker, client_name: str, building_type: str) -> Quote:
    # assigned_tradie_id (not created_by_worker_id) is the Phase F field for
    # "which tradie handled this job" — created_by_worker_id now means
    # "which Sales rep created it," which none of these demo quotes have
    # (they're built directly, not through the Sales creation endpoint).
    quote = Quote(status=QuoteStatus.extracted, assigned_tradie_id=tradie.id)
    db.add(quote)
    db.flush()
    db.add(QuoteHeader(quote_id=quote.id, client_name=client_name, rep=tradie.name))
    db.add(Installation(quote_id=quote.id, building_type=building_type))
    db.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window, bathroom",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
            qty=1,
            confidence=1.0,
        )
    )
    db.commit()
    return quote


def main() -> None:
    db = SessionLocal()
    try:
        tradie = _get_or_create_worker(
            db, DEMO_TRADIE_USERNAME, "Marcus Chen", DEMO_TRADIE_PASSWORD, role=WorkerRole.tradie
        )
        sales = _get_or_create_worker(
            db, DEMO_SALES_USERNAME, "Sales Rep", DEMO_SALES_PASSWORD, role=WorkerRole.sales
        )
        _get_or_create_worker(db, DEMO_OWNER_USERNAME, "Anthony", DEMO_OWNER_PASSWORD, role=WorkerRole.owner)

        with (
            patch("app.workers.pipeline.send_approval_email"),
            patch("app.workers.pipeline.generate_quote_pdf", return_value=b"%PDF-fake"),
        ):
            # Quote 0: a Strata job Anthony already reviewed before today
            # (scripted history) — request_changes -> tradie fixes and
            # resends -> approved. This is what creates the first real
            # LearnedLesson, through the same fields owner_quotes.py and
            # worker_quotes.py's resubmit endpoint actually use, not a
            # hand-authored row pretending the loop already ran.
            quote0 = _build_quote(db, tradie, "Priya Nair", building_type="Strata")
            process_worker_submission_pipeline(db, quote0)
            db.commit()

            fix_note = "Strata jobs need a body corporate approval note added for the client before it goes out."
            comment = ApprovalComment(quote_id=quote0.id, author="owner", body=fix_note, action="request_changes")
            db.add(comment)
            quote0.status = QuoteStatus.changes_requested
            db.flush()
            db.add(
                LearnedLesson(
                    trigger_summary="A quote for an awning window (aluminium) at a Strata building",
                    fix_summary=fix_note,
                    source_comment_id=comment.id,
                )
            )
            db.commit()

            quote0.installation.notes = "Body corporate approval required (Strata)."
            db.add(
                ApprovalComment(
                    quote_id=quote0.id, author="tradie", body="Added the body corporate note, resending."
                )
            )
            quote0.status = QuoteStatus.extracted
            db.commit()
            process_worker_submission_pipeline(db, quote0)
            db.add(
                ApprovalComment(quote_id=quote0.id, author="owner", body="All good now, approved.", action="approve")
            )
            quote0.status = QuoteStatus.approved
            db.commit()

            # Quote 1: a NEW Strata job submitted after the lesson above
            # exists — its agent_notes gets computed for real by
            # send_for_approval -> check_against_lessons, not faked, so this
            # should show a matched note when Anthony opens it.
            quote1 = _build_quote(db, tradie, "Robert Kim", building_type="Strata")
            process_worker_submission_pipeline(db, quote1)
            db.commit()

            # Quote 2: an ordinary job, no edge case — just queue variety.
            quote2 = _build_quote(db, tradie, "Elena Popescu", building_type="Residence")
            process_worker_submission_pipeline(db, quote2)
            db.commit()

        # Quote 3: the Sales scheduling loop (Phase F), scripted the same
        # way — a job Sales created and assigned, that the tradie reported
        # missed (weather), that Sales then rescheduled. No pipeline run
        # here; this quote never leaves the scheduling stage.
        quote3 = Quote(
            status=QuoteStatus.scheduled,
            created_by_worker_id=sales.id,
            assigned_tradie_id=tradie.id,
            scheduled_date="2026-08-03",
        )
        db.add(quote3)
        db.flush()
        db.add(QuoteHeader(quote_id=quote3.id, client_name="David Nguyen", phone="0400 111 222"))
        db.commit()

        db.add(ApprovalComment(quote_id=quote3.id, author="tradie", body="Weather", action="missed_visit"))
        quote3.status = QuoteStatus.missed
        db.commit()

        db.add(ApprovalComment(quote_id=quote3.id, author="sales", body="Weather", action="reschedule"))
        quote3.status = QuoteStatus.scheduled
        quote3.scheduled_date = "2026-08-05"
        db.commit()

        print(f"seeded quote {quote0.id} — already resolved (approved), full comment history")
        print(f"seeded quote {quote1.id} — pending_approval, should carry an agent note about Strata jobs")
        print(f"seeded quote {quote2.id} — pending_approval, plain, no edge case")
        print(f"seeded quote {quote3.id} — scheduled for 2026-08-05, missed once (weather) then rescheduled")
        print(f"log in as owner: {DEMO_OWNER_USERNAME} / {DEMO_OWNER_PASSWORD}")
        print(f"log in as sales: {DEMO_SALES_USERNAME} / {DEMO_SALES_PASSWORD}")
        print(f"log in as tradie: {DEMO_TRADIE_USERNAME} / {DEMO_TRADIE_PASSWORD}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
