# app/auth.py
"""Worker app authentication — JWT bearer tokens. No self-registration;
accounts are created by the owner (see scripts/create_worker.py)."""

import datetime as dt

import bcrypt
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Worker, WorkerRole

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(worker_id: str) -> str:
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.JWT_ACCESS_TOKEN_MINUTES)
    payload = {"sub": worker_id, "exp": expires_at}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


class InvalidWorkerToken(Exception):
    """Raised when a bearer token fails signature verification or has expired."""


def decode_access_token(token: str) -> str:
    """Returns the worker_id encoded in the token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidWorkerToken(str(exc)) from exc
    return payload["sub"]


def get_current_worker(token: str = Depends(_oauth2_scheme), db: Session = Depends(get_db)) -> Worker:
    try:
        worker_id = decode_access_token(token)
    except InvalidWorkerToken as exc:
        raise HTTPException(status_code=401, detail="invalid or expired token") from exc

    worker = db.get(Worker, worker_id)
    if worker is None or not worker.is_active:
        raise HTTPException(status_code=401, detail="worker not found or inactive")
    return worker


def require_owner(worker: Worker = Depends(get_current_worker)) -> Worker:
    """Gates app/api/owner_quotes.py — an account is exactly one role
    (Worker.role), never more than one. See scripts/create_worker.py
    --role for provisioning."""
    if worker.role != WorkerRole.owner:
        raise HTTPException(status_code=403, detail="owner access required")
    return worker


def require_sales(worker: Worker = Depends(get_current_worker)) -> Worker:
    """Gates app/api/sales_quotes.py — see require_owner above."""
    if worker.role != WorkerRole.sales:
        raise HTTPException(status_code=403, detail="sales access required")
    return worker
