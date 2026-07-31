# tests/test_locking.py
from unittest.mock import MagicMock

from app.workers import locking
from app.workers.locking import with_lock


def _fake_lock(acquire_result: bool):
    lock = MagicMock()
    lock.acquire.return_value = acquire_result
    return lock


def test_runs_fn_when_lock_acquired(monkeypatch):
    fake_client = MagicMock()
    fake_client.lock.return_value = _fake_lock(True)
    monkeypatch.setattr(locking, "_redis_client", fake_client)

    result = with_lock("lock:test", timeout=60, fn=lambda: "did work")

    assert result == "did work"


def test_returns_none_when_lock_already_held(monkeypatch):
    fake_client = MagicMock()
    fake_client.lock.return_value = _fake_lock(False)
    monkeypatch.setattr(locking, "_redis_client", fake_client)

    fn = MagicMock()
    result = with_lock("lock:test", timeout=60, fn=fn)

    assert result is None
    fn.assert_not_called()


def test_lock_is_released_after_fn_runs(monkeypatch):
    fake_client = MagicMock()
    fake_lock = _fake_lock(True)
    fake_client.lock.return_value = fake_lock
    monkeypatch.setattr(locking, "_redis_client", fake_client)

    with_lock("lock:test", timeout=60, fn=lambda: None)

    fake_lock.release.assert_called_once()


def test_lock_is_released_even_if_fn_raises(monkeypatch):
    fake_client = MagicMock()
    fake_lock = _fake_lock(True)
    fake_client.lock.return_value = fake_lock
    monkeypatch.setattr(locking, "_redis_client", fake_client)

    def boom():
        raise RuntimeError("boom")

    try:
        with_lock("lock:test", timeout=60, fn=boom)
    except RuntimeError:
        pass

    fake_lock.release.assert_called_once()


def test_blocking_timeout_is_zero_so_it_never_waits(monkeypatch):
    fake_client = MagicMock()
    fake_client.lock.return_value = _fake_lock(True)
    monkeypatch.setattr(locking, "_redis_client", fake_client)

    with_lock("lock:test", timeout=60, fn=lambda: None)

    _, kwargs = fake_client.lock.call_args
    assert kwargs["blocking_timeout"] == 0
