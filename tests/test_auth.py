# tests/test_auth.py
import datetime as dt

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import (
    InvalidWorkerToken,
    create_access_token,
    decode_access_token,
    get_current_worker,
    hash_password,
    verify_password,
)
from app.config import settings
from app.models import Base, Worker


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_hash_password_never_stores_plaintext():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_verify_password_accepts_correct_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_access_token_roundtrips_worker_id():
    token = create_access_token("worker-1")
    assert decode_access_token(token) == "worker-1"


def test_decode_rejects_garbage_token():
    with pytest.raises(InvalidWorkerToken):
        decode_access_token("not-a-real-token")


def test_decode_rejects_token_signed_with_different_secret():
    token = jwt.encode({"sub": "worker-1"}, "a-different-secret", algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidWorkerToken):
        decode_access_token(token)


def test_decode_rejects_expired_token():
    expired_payload = {
        "sub": "worker-1",
        "exp": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1),
    }
    token = jwt.encode(expired_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(InvalidWorkerToken):
        decode_access_token(token)


def test_get_current_worker_returns_worker_for_valid_token(db_session):
    worker = Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"))
    db_session.add(worker)
    db_session.commit()

    token = create_access_token(worker.id)
    result = get_current_worker(token=token, db=db_session)

    assert result.id == worker.id
    assert result.username == "marcus"


def test_get_current_worker_rejects_invalid_token(db_session):
    with pytest.raises(HTTPException) as exc_info:
        get_current_worker(token="garbage", db=db_session)
    assert exc_info.value.status_code == 401


def test_get_current_worker_rejects_unknown_worker_id(db_session):
    token = create_access_token("no-such-worker-id")
    with pytest.raises(HTTPException) as exc_info:
        get_current_worker(token=token, db=db_session)
    assert exc_info.value.status_code == 401


def test_get_current_worker_rejects_inactive_worker(db_session):
    worker = Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"), is_active=False)
    db_session.add(worker)
    db_session.commit()

    token = create_access_token(worker.id)
    with pytest.raises(HTTPException) as exc_info:
        get_current_worker(token=token, db=db_session)
    assert exc_info.value.status_code == 401
