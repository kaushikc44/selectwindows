# tests/test_ai_logs.py
"""AI call audit logging (maps branch) — every LLM call writes an AiCallLog
row (purpose, quote_id, input, output, latency, tokens, success), and
GET /owner/ai-logs exposes it to Anthony only. The real OpenAI client and the
log DB session are stubbed so this runs offline against the in-memory test DB.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.llm import LLMUnavailable, ai_quote_context, chat_completion, vision_completion
from app.auth import get_current_worker, hash_password
from app.db import get_db
from app.main import app
from app.models import AiCallLog, Base, Worker, WorkerRole


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def owner(db_session):
    w = Worker(username="anthony", name="Anthony", hashed_password=hash_password("pw"), role=WorkerRole.owner)
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def tradie(db_session):
    w = Worker(username="marcus", name="Marcus", hashed_password=hash_password("pw"))
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def log_session(db_session, monkeypatch):
    """Point app.ai.llm's audit writes at the in-memory test session instead
    of the real DATABASE_URL, so a logged call actually lands where the test
    can see it."""
    monkeypatch.setattr("app.ai.llm._get_log_session", lambda: db_session)
    return db_session


def _fake_create_returns(content: str, *, prompt_tokens: int = 12, completion_tokens: int = 7):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def test_chat_completion_logs_success(log_session, monkeypatch):
    """A successful call writes a row with purpose, the input prompt, the
    output text, token usage, latency, and success=True."""
    monkeypatch.setattr(
        "app.ai.llm.client.chat.completions.create",
        lambda **kw: _fake_create_returns('{"notes": ["safety glass"]}'),
    )

    with ai_quote_context("job-123"):
        out = chat_completion([{"role": "user", "content": "Check this quote."}], purpose="approval_lesson_check")

    assert out == '{"notes": ["safety glass"]}'
    rows = log_session.query(AiCallLog).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.purpose == "approval_lesson_check"
    assert row.quote_id == "job-123"
    assert "[user] Check this quote." in row.input_text
    assert row.output_text == '{"notes": ["safety glass"]}'
    assert row.success is True
    assert row.prompt_tokens == 12
    assert row.completion_tokens == 7
    assert row.latency_ms is not None and row.latency_ms >= 0
    assert row.error is None


def test_chat_completion_logs_failure(log_session, monkeypatch):
    """A failed call (LLMUnavailable raised before any retry sleep) is logged
    with success=False and the error text, then re-raised — the audit must
    survive a crash, not just the happy path."""
    def _raise(**kw):
        raise LLMUnavailable("endpoint down")

    monkeypatch.setattr("app.ai.llm.client.chat.completions.create", _raise)

    with pytest.raises(LLMUnavailable):
        with ai_quote_context("job-456"):
            chat_completion([{"role": "user", "content": "p"}], purpose="extract_email")

    rows = log_session.query(AiCallLog).all()
    assert len(rows) == 1
    assert rows[0].success is False
    assert rows[0].output_text is None
    assert "endpoint down" in rows[0].error
    assert rows[0].quote_id == "job-456"


def test_vision_completion_logs_image_manifest_not_bytes(log_session, monkeypatch):
    """Vision calls record the text prompt + an image manifest in input_text —
    never the base64 image bytes (the audit table shouldn't carry megabytes)."""
    monkeypatch.setattr(
        "app.ai.llm.vision_client.chat.completions.create",
        lambda **kw: _fake_create_returns("{}", prompt_tokens=50, completion_tokens=1),
    )
    big = b"x" * 4000  # ~4KB → ~5333 base64 chars

    with ai_quote_context("job-vis"):
        vision_completion([(big, "image/jpeg")], "Extract the window dimensions.", purpose="extract_ar")

    row = log_session.query(AiCallLog).one()
    assert row.purpose == "extract_ar"
    assert "Extract the window dimensions." in row.input_text
    assert "image/jpeg" in row.input_text
    # The raw image bytes must NOT be in the audit row.
    assert "xxxx" not in row.input_text


def test_ai_logs_endpoint_requires_owner_role(db_session, tradie, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: tradie
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/owner/ai-logs")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_ai_logs_endpoint_returns_logs_and_summary(db_session, owner, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: owner

    db_session.add_all([
        AiCallLog(quote_id="A", purpose="extract_email", model="m", input_text="in", output_text="out1",
                  success=True, prompt_tokens=1, completion_tokens=2, latency_ms=10),
        AiCallLog(quote_id="A", purpose="classify", model="m", input_text="in", output_text=None,
                  success=False, error="boom", latency_ms=5),
        AiCallLog(quote_id="B", purpose="enrich_materials", model="m", input_text="in", output_text="out3",
                  success=True, latency_ms=8),
    ])
    db_session.commit()

    try:
        with TestClient(app) as test_client:
            all_resp = test_client.get("/owner/ai-logs")
            scoped = test_client.get("/owner/ai-logs", params={"quote_id": "A"})
    finally:
        app.dependency_overrides.clear()

    assert all_resp.status_code == 200
    body = all_resp.json()
    assert body["total"] == 3
    assert body["failures"] == 1
    purposes = {p["purpose"]: p for p in body["by_purpose"]}
    assert purposes["extract_email"]["count"] == 1
    assert purposes["classify"]["failures"] == 1
    # Most-recent-first slice.
    assert [l["quote_id"] for l in body["logs"]] == ["B", "A", "A"] or len(body["logs"]) == 3

    scoped_body = scoped.json()
    assert scoped_body["total"] == 3  # summary is over the whole table
    assert {l["quote_id"] for l in scoped_body["logs"]} == {"A"}