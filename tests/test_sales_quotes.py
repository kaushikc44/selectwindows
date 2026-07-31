# tests/test_sales_quotes.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_worker, hash_password
from app.db import get_db
from app.main import app
from app.models import ApprovalComment, Base, Quote, QuoteHeader, QuoteStatus, Worker, WorkerRole


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def sales(db_session):
    w = Worker(username="salesrep", name="Sales Rep", hashed_password=hash_password("pw"), role=WorkerRole.sales)
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def tradie(db_session):
    w = Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"))
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def client(db_session, sales, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: sales
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_sales_endpoints_require_sales_role(db_session, tradie, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: tradie
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/sales/quotes")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_list_tradies_returns_only_active_tradie_accounts(client, db_session, tradie, sales):
    inactive_tradie = Worker(
        username="gone", name="Gone Tradie", hashed_password=hash_password("pw"), is_active=False
    )
    owner = Worker(username="anthony", name="Anthony", hashed_password=hash_password("pw"), role=WorkerRole.owner)
    db_session.add_all([inactive_tradie, owner])
    db_session.commit()

    response = client.get("/sales/tradies")

    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert names == {"Marcus Chen"}


def test_create_sales_job_creates_scheduled_quote_assigned_to_tradie(client, db_session, tradie):
    response = client.post(
        "/sales/quotes",
        json={
            "client_name": "David Nguyen",
            "phone": "0400 111 222",
            "assigned_tradie_id": tradie.id,
            "scheduled_date": "2026-08-05",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "scheduled"

    quote = db_session.get(Quote, body["quote_id"])
    assert quote.status == QuoteStatus.scheduled
    assert quote.assigned_tradie_id == tradie.id
    assert quote.scheduled_date == "2026-08-05"
    assert quote.header.client_name == "David Nguyen"
    assert quote.header.phone == "0400 111 222"


def test_create_sales_job_rejects_non_tradie_assignment(client, db_session, sales):
    response = client.post(
        "/sales/quotes",
        json={"client_name": "David Nguyen", "assigned_tradie_id": sales.id, "scheduled_date": "2026-08-05"},
    )

    assert response.status_code == 422


def test_create_sales_job_rejects_unknown_tradie_id(client):
    response = client.post(
        "/sales/quotes",
        json={"client_name": "David Nguyen", "assigned_tradie_id": "does-not-exist", "scheduled_date": "2026-08-05"},
    )

    assert response.status_code == 422


def test_list_sales_jobs_shows_scheduling_fields_only(client, db_session, tradie):
    quote = Quote(status=QuoteStatus.scheduled, assigned_tradie_id=tradie.id, scheduled_date="2026-08-05")
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="David Nguyen"))
    quote.total = 561.00
    db_session.commit()

    response = client.get("/sales/quotes")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["client_name"] == "David Nguyen"
    assert body[0]["assigned_tradie_name"] == "Marcus Chen"
    assert body[0]["scheduled_date"] == "2026-08-05"
    assert "total" not in body[0]  # scheduling only, never pricing (confirmed decision)


def test_list_sales_jobs_excludes_quotes_with_no_assigned_tradie(client, db_session):
    db_session.add(Quote(status=QuoteStatus.pending_approval))  # old email-pipeline quote
    db_session.commit()

    response = client.get("/sales/quotes")

    assert response.json() == []


def test_get_sales_job_detail_includes_comment_thread(client, db_session, tradie):
    quote = Quote(status=QuoteStatus.scheduled, assigned_tradie_id=tradie.id, scheduled_date="2026-08-05")
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="David Nguyen"))
    db_session.add(ApprovalComment(quote_id=quote.id, author="tradie", body="Weather", action="missed_visit"))
    db_session.commit()

    response = client.get(f"/sales/quotes/{quote.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["client_name"] == "David Nguyen"
    assert body["assigned_tradie_id"] == tradie.id
    assert len(body["comments"]) == 1
    assert body["comments"][0]["action"] == "missed_visit"
    assert "total" not in body


def test_get_sales_job_404_for_quote_with_no_assigned_tradie(client, db_session):
    quote = Quote(status=QuoteStatus.pending_approval)
    db_session.add(quote)
    db_session.commit()

    response = client.get(f"/sales/quotes/{quote.id}")

    assert response.status_code == 404


def test_reschedule_job_updates_date_and_flips_missed_to_scheduled(client, db_session, tradie):
    quote = Quote(status=QuoteStatus.missed, assigned_tradie_id=tradie.id, scheduled_date="2026-08-05")
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="David Nguyen"))
    db_session.commit()

    response = client.post(
        f"/sales/quotes/{quote.id}/reschedule",
        json={"new_date": "2026-08-08", "reason": "weather"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_date"] == "2026-08-08"

    db_session.refresh(quote)
    assert quote.status == QuoteStatus.scheduled
    assert quote.scheduled_date == "2026-08-08"
    assert len(quote.approval_comments) == 1
    assert quote.approval_comments[0].author == "sales"
    assert quote.approval_comments[0].action == "reschedule"
    assert quote.approval_comments[0].body == "Weather"


def test_reschedule_job_with_other_reason_includes_detail_text(client, db_session, tradie):
    quote = Quote(status=QuoteStatus.scheduled, assigned_tradie_id=tradie.id, scheduled_date="2026-08-05")
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="David Nguyen"))
    db_session.commit()

    response = client.post(
        f"/sales/quotes/{quote.id}/reschedule",
        json={"new_date": "2026-08-09", "reason": "other", "other_detail": "Client asked for next week"},
    )

    assert response.status_code == 200
    db_session.refresh(quote)
    assert quote.approval_comments[0].body == "Other: Client asked for next week"


def test_reschedule_job_rejects_when_not_reschedulable(client, db_session, tradie):
    quote = Quote(status=QuoteStatus.approved, assigned_tradie_id=tradie.id, scheduled_date="2026-08-05")
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="David Nguyen"))
    db_session.commit()

    response = client.post(
        f"/sales/quotes/{quote.id}/reschedule",
        json={"new_date": "2026-08-08", "reason": "weather"},
    )

    assert response.status_code == 409
