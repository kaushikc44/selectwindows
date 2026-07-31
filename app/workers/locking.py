# app/workers/locking.py
"""Prevents overlapping Celery beat ticks from doing the same IMAP/LLM work
twice. Without this, a slow poll still in-flight when the next scheduled
tick fires causes duplicate processing — this is exactly what produced
multiple duplicate "still need info" emails to a rep in production: several
overlapping poll_and_process_replies runs each independently found the same
unprocessed reply before any of them had marked it processed."""

import redis

from app.config import settings

_redis_client = redis.Redis.from_url(settings.REDIS_URL)


def with_lock(lock_name: str, timeout: int, fn):
    """Runs fn() only if the named lock is acquired immediately (no
    blocking/waiting). Returns fn()'s result, or None if another run is
    already in progress. timeout is a safety auto-expiry in case a worker
    crashes mid-task, so the lock can't get stuck held forever."""
    lock = _redis_client.lock(lock_name, timeout=timeout, blocking_timeout=0)
    if not lock.acquire(blocking=False):
        return None
    try:
        return fn()
    finally:
        try:
            lock.release()
        except redis.exceptions.LockError:
            pass  # already expired — timeout already protects correctness
