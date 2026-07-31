# tests/test_main.py
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import decode_access_token, hash_password
from app.db import get_db
from app.main import app
from app.models import Base, Quote, QuoteStatus, Worker
from app.output.approval import build_approval_links


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def client(db_session, monkeypatch):
    def _get_db_override():
        yield db_session

    # The real lifespan calls create_all() against settings.DATABASE_URL (postgres),
    # which isn't reachable in unit tests; tables are already created on db_session's engine.
    monkeypatch.setattr("app.main.create_all", lambda: None)

    app.dependency_overrides[get_db] = _get_db_override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _pending_quote(db_session: Session) -> Quote:
    quote = Quote(status=QuoteStatus.pending_approval, total=Decimal("539.70"))
    db_session.add(quote)
    db_session.commit()
    approve_url, reject_url, approve_token, reject_token = build_approval_links(quote.id)
    quote.approve_token = approve_token
    quote.reject_token = reject_token
    db_session.commit()
    return quote


def test_get_quote_returns_404_when_missing(client):
    response = client.get("/quotes/does-not-exist")
    assert response.status_code == 404


def test_get_quote_returns_quote_out(client, db_session):
    quote = _pending_quote(db_session)
    response = client.get(f"/quotes/{quote.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"


def test_approve_flips_status_to_approved(client, db_session):
    quote = _pending_quote(db_session)

    response = client.get(f"/approve/{quote.approve_token}", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.approved
    assert quote.token_used is True


def test_reject_flips_status_to_rejected(client, db_session):
    quote = _pending_quote(db_session)

    response = client.get(f"/reject/{quote.reject_token}")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


def test_token_is_single_use(client, db_session):
    quote = _pending_quote(db_session)

    first = client.get(f"/approve/{quote.approve_token}")
    second = client.get(f"/approve/{quote.approve_token}")

    assert first.status_code == 200
    assert second.status_code == 410


def test_reject_token_cannot_be_used_to_approve(client, db_session):
    quote = _pending_quote(db_session)

    response = client.get(f"/approve/{quote.reject_token}")

    assert response.status_code == 400


def test_invalid_token_returns_400(client):
    response = client.get("/approve/not-a-real-token")
    assert response.status_code == 400


def test_login_returns_access_token_for_correct_credentials(client, db_session):
    db_session.add(Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw")))
    db_session.commit()

    response = client.post("/auth/login", data={"username": "marcus", "password": "pw"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"])


def test_login_rejects_wrong_password(client, db_session):
    db_session.add(Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw")))
    db_session.commit()

    response = client.post("/auth/login", data={"username": "marcus", "password": "wrong"})

    assert response.status_code == 401


def test_login_rejects_unknown_username(client):
    response = client.post("/auth/login", data={"username": "nobody", "password": "pw"})
    assert response.status_code == 401


def test_login_rejects_inactive_worker(client, db_session):
    db_session.add(
        Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"), is_active=False)
    )
    db_session.commit()

    response = client.post("/auth/login", data={"username": "marcus", "password": "pw"})

    assert response.status_code == 401
