# tests/test_worker_quotes.py
import io
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import worker_quotes
from app.auth import get_current_worker, hash_password
from app.db import get_db
from app.main import app
from app.models import ApprovalComment, Base, Item, Quote, QuoteHeader, QuoteStatus, Worker


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def worker(db_session):
    w = Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"))
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def client(db_session, worker, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    monkeypatch.setattr(worker_quotes, "process_worker_submission", MagicMock())

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: worker
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _make_quote(
    db_session, tradie: Worker, status: QuoteStatus = QuoteStatus.draft, client_name: str | None = "Sarah Williams"
) -> Quote:
    """Jobs are created by Sales, not the tradie (Phase F — see
    app/api/sales_quotes.py), so tests that only care about the tradie-side
    item/photo/submit endpoints construct the starting quote directly
    rather than going through the (now separate) sales creation endpoint."""
    quote = Quote(status=status, assigned_tradie_id=tradie.id)
    db_session.add(quote)
    db_session.flush()
    if client_name is not None:
        db_session.add(QuoteHeader(quote_id=quote.id, client_name=client_name))
    db_session.commit()
    return quote


def _quote_with_item(client, db_session, worker) -> tuple[str, str]:
    quote = _make_quote(db_session, worker)
    item_id = client.post(
        f"/worker/quotes/{quote.id}/items",
        json={"product_type": "louvre", "material": "aluminium", "room": "Bathroom"},
    ).json()["item_id"]
    return quote.id, item_id


def test_add_item_creates_item_with_incrementing_item_no(client, db_session, worker):
    quote = _make_quote(db_session, worker, client_name=None)

    first = client.post(
        f"/worker/quotes/{quote.id}/items",
        json={"product_type": "louvre", "material": "aluminium", "room": "Bathroom"},
    )
    second = client.post(
        f"/worker/quotes/{quote.id}/items",
        json={"product_type": "sliding", "material": "aluminium", "room": "Living Room"},
    )

    assert first.json()["item_no"] == 1
    assert second.json()["item_no"] == 2
    db_session.refresh(quote)
    assert len(quote.items) == 2
    assert quote.items[0].product_type.value == "louvre"


def test_add_item_rejects_invalid_product_type(client, db_session, worker):
    quote = _make_quote(db_session, worker, client_name=None)

    response = client.post(
        f"/worker/quotes/{quote.id}/items", json={"product_type": "not_a_real_type", "material": "aluminium"}
    )

    assert response.status_code == 422


def test_add_item_to_someone_elses_quote_returns_404(client, db_session):
    other_worker = Worker(username="other", name="Other Worker", hashed_password=hash_password("pw"))
    db_session.add(other_worker)
    db_session.commit()
    other_quote = Quote(status=QuoteStatus.draft, assigned_tradie_id=other_worker.id)
    db_session.add(other_quote)
    db_session.commit()

    response = client.post(
        f"/worker/quotes/{other_quote.id}/items", json={"product_type": "louvre", "material": "aluminium"}
    )

    assert response.status_code == 404


def test_photo_upload_resolves_dimension_on_clear_reading(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=940, confidence=0.95))
    )

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "height"},
        files={"photo": ("height.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["value_mm"] == 940

    item = db_session.get(Item, item_id)
    assert item.height_mm == 940
    assert item.width_mm is None


def test_photo_upload_returns_unreadable_when_no_reading_found(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    monkeypatch.setattr(worker_quotes, "extract_single_reading", MagicMock(return_value=None))

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("width.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "resolved": False,
        "value_mm": None,
        "multi_reading": False,
        "reason": "unreadable",
        "conflict_values_mm": None,
    }


def test_photo_upload_retake_within_tolerance_resolves_to_minimum(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=2700, confidence=0.9))
    )
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w1.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=2470, confidence=0.9))
    )
    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w2.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    body = response.json()
    assert body["resolved"] is True
    assert body["value_mm"] == 2470  # min(2700, 2470)
    assert body["multi_reading"] is True

    item = db_session.get(Item, item_id)
    assert item.width_mm == 2470
    assert item.dimensions_multi_reading is True


def test_photo_upload_genuine_conflict_returned_not_resolved(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=2470, confidence=0.9))
    )
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w1.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=6050, confidence=0.9))
    )
    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w2.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    body = response.json()
    assert body["resolved"] is False
    assert body["reason"] == "conflict"
    assert set(body["conflict_values_mm"]) == {2470, 6050}

    item = db_session.get(Item, item_id)
    assert item.width_mm is None


def test_photo_upload_sets_item_confidence_once_both_axes_resolved(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=940, confidence=0.8))
    )
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "height"},
        files={"photo": ("h.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )
    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=2585, confidence=0.6))
    )
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    item = db_session.get(Item, item_id)
    assert item.confidence == pytest.approx(0.7)  # mean(0.8, 0.6)


def test_submit_rejects_when_item_missing_dimensions(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    response = client.post(f"/worker/quotes/{quote_id}/submit")

    assert response.status_code == 422
    assert any("missing a resolved width" in detail for detail in response.json()["detail"])


def test_submit_rejects_when_no_client_name(client, db_session, worker):
    quote = _make_quote(db_session, worker, client_name=None)

    response = client.post(f"/worker/quotes/{quote.id}/submit")

    assert response.status_code == 422
    assert any("client name" in detail for detail in response.json()["detail"])


def test_submit_succeeds_and_enqueues_processing(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()

    response = client.post(f"/worker/quotes/{quote_id}/submit")

    assert response.status_code == 200
    assert response.json()["status"] == "extracted"
    worker_quotes.process_worker_submission.delay.assert_called_once_with(quote_id)


def test_cannot_add_items_to_a_submitted_quote(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()
    client.post(f"/worker/quotes/{quote_id}/submit")

    response = client.post(
        f"/worker/quotes/{quote_id}/items", json={"product_type": "sliding", "material": "aluminium"}
    )

    assert response.status_code == 409


def test_elevation_preview_returns_svg_for_recognized_code(client):
    response = client.get("/worker/elevation-preview", params={"config_code": "BFW-4"})

    assert response.status_code == 200
    assert "<svg" in response.json()["svg"]


def test_elevation_preview_requires_auth(monkeypatch):
    monkeypatch.setattr("app.main.create_all", lambda: None)
    with TestClient(app) as unauthenticated_client:
        response = unauthenticated_client.get("/worker/elevation-preview", params={"config_code": "SL2"})
    assert response.status_code == 401


def test_elevation_preview_unrecognized_code_still_renders_a_placeholder(client):
    response = client.get("/worker/elevation-preview", params={"config_code": "ZZTOP-9"})

    assert response.status_code == 200
    assert "<svg" in response.json()["svg"]


def test_list_my_quotes_returns_only_this_workers_quotes(client, db_session, worker):
    other_worker = Worker(username="other", name="Other Worker", hashed_password=hash_password("pw"))
    db_session.add(other_worker)
    db_session.commit()
    db_session.add(Quote(status=QuoteStatus.draft, assigned_tradie_id=other_worker.id))
    db_session.commit()

    _make_quote(db_session, worker)

    response = client.get("/worker/quotes")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["client_name"] == "Sarah Williams"
    assert body[0]["status"] == "draft"


def test_list_my_quotes_orders_newest_first(client, db_session, worker):
    import datetime as dt

    first = _make_quote(db_session, worker, client_name="First Job")
    second = _make_quote(db_session, worker, client_name="Second Job")
    # SQLite's func.now() can resolve both inserts to the same instant in a
    # fast test run — set explicit, distinct timestamps rather than relying
    # on wall-clock ordering.
    first.created_at = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    second.created_at = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
    db_session.commit()

    body = client.get("/worker/quotes").json()

    assert [q["client_name"] for q in body] == ["Second Job", "First Job"]


def test_get_my_quote_returns_items_with_dimension_state(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()

    response = client.get(f"/worker/quotes/{quote_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["client_name"] == "Sarah Williams"
    assert body["status"] == "draft"
    assert len(body["items"]) == 1
    assert body["items"][0]["item_id"] == item_id
    assert body["items"][0]["width_mm"] == 2470
    assert body["items"][0]["height_mm"] == 940


def test_get_my_quote_for_someone_elses_quote_returns_404(client, db_session):
    other_worker = Worker(username="other", name="Other Worker", hashed_password=hash_password("pw"))
    db_session.add(other_worker)
    db_session.commit()
    other_quote = Quote(status=QuoteStatus.draft, assigned_tradie_id=other_worker.id)
    db_session.add(other_quote)
    db_session.commit()

    response = client.get(f"/worker/quotes/{other_quote.id}")

    assert response.status_code == 404


def test_get_my_quote_works_after_submission_not_just_drafts(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()
    client.post(f"/worker/quotes/{quote_id}/submit")

    response = client.get(f"/worker/quotes/{quote_id}")

    assert response.status_code == 200
    assert response.json()["status"] == "extracted"


def test_upload_reference_photo_stores_attachment_without_extraction(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    mock_extract = MagicMock()
    monkeypatch.setattr(worker_quotes, "extract_single_reading", mock_extract)

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
        files={"photo": ("site.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"].endswith("site.jpg")
    mock_extract.assert_not_called()  # reference photos never run dimension extraction

    item = db_session.get(Item, item_id)
    assert item.width_mm is None and item.height_mm is None  # unaffected


def test_upload_multiple_reference_photos_all_saved(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    for name in ("site1.jpg", "site2.jpg", "site3.jpg"):
        response = client.post(
            f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
            files={"photo": (name, io.BytesIO(b"fake"), "image/jpeg")},
        )
        assert response.status_code == 200

    listed = client.get(f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos").json()
    assert len(listed) == 3


def test_list_reference_photos_empty_when_none_uploaded(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    response = client.get(f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos")

    assert response.status_code == 200
    assert response.json() == []


def test_list_reference_photos_works_after_submission(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
        files={"photo": ("site.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()
    client.post(f"/worker/quotes/{quote_id}/submit")


def test_get_attachment_streams_the_stored_photo_bytes(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    upload = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
        files={"photo": ("site.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")},
    ).json()

    response = client.get(f"/worker/attachments/{upload['attachment_id']}")

    assert response.status_code == 200
    assert response.content == b"fake-image-bytes"
    assert response.headers["content-type"] == "image/jpeg"


def test_get_attachment_works_after_submission(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    upload = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
        files={"photo": ("site.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    ).json()
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    db_session.commit()
    client.post(f"/worker/quotes/{quote_id}/submit")

    response = client.get(f"/worker/attachments/{upload['attachment_id']}")

    assert response.status_code == 200


def test_get_attachment_for_someone_elses_quote_returns_404(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    upload = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/reference-photos",
        files={"photo": ("site.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    ).json()

    other_worker = Worker(username="other2", name="Other Worker", hashed_password=hash_password("pw"))
    db_session.add(other_worker)
    db_session.commit()
    app.dependency_overrides[get_current_worker] = lambda: other_worker

    response = client.get(f"/worker/attachments/{upload['attachment_id']}")

    assert response.status_code == 404


def test_get_attachment_unknown_id_returns_404(client):
    response = client.get("/worker/attachments/does-not-exist")

    assert response.status_code == 404


def test_get_my_quote_includes_total_and_flags_fields(client, db_session, worker):
    quote_id, _item_id = _quote_with_item(client, db_session, worker)

    response = client.get(f"/worker/quotes/{quote_id}")

    body = response.json()
    assert body["total"] is None  # not priced yet — still a draft
    assert body["flags"] == []
    assert body["items"][0]["line_total"] is None


def test_manual_dimension_entry_resolves_immediately(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "height", "value_mm": 940}
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {"resolved": True, "value_mm": 940, "multi_reading": False, "reason": None, "conflict_values_mm": None}

    item = db_session.get(Item, item_id)
    assert item.height_mm == 940


def test_manual_dimension_entry_outranks_a_prior_ar_reading(client, db_session, worker, monkeypatch):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    monkeypatch.setattr(
        worker_quotes, "extract_single_reading", MagicMock(return_value=MagicMock(value_mm=2470, confidence=0.7))
    )
    client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/photos",
        data={"field": "width"},
        files={"photo": ("w.jpg", io.BytesIO(b"fake"), "image/jpeg")},
    )

    # A typed-in correction well outside the 15% tolerance of the AR reading
    # still resolves cleanly (not a conflict) — manual_entry outranks
    # ar_overlay in SOURCE_PRECEDENCE, so it wins outright rather than being
    # compared against it.
    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "width", "value_mm": 2650}
    )

    assert response.status_code == 200
    assert response.json()["resolved"] is True
    assert response.json()["value_mm"] == 2650

    item = db_session.get(Item, item_id)
    assert item.width_mm == 2650


def test_manual_dimension_entry_conflicts_with_a_disagreeing_manual_entry(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    client.post(f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "width", "value_mm": 2470})

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "width", "value_mm": 6050}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is False
    assert body["reason"] == "conflict"
    assert set(body["conflict_values_mm"]) == {2470, 6050}

    item = db_session.get(Item, item_id)
    assert item.width_mm is None


def test_add_item_stores_sill_height(client, db_session, worker):
    quote = _make_quote(db_session, worker)
    item_id = client.post(
        f"/worker/quotes/{quote.id}/items",
        json={"product_type": "awning", "material": "aluminium", "room": "Bathroom", "sill_height_mm": 400},
    ).json()["item_id"]

    item = db_session.get(Item, item_id)
    assert item.sill_height_mm == 400

    detail = client.get(f"/worker/quotes/{quote.id}").json()
    assert detail["items"][0]["sill_height_mm"] == 400


def test_cannot_add_items_or_photos_to_a_pending_approval_quote(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    quote = db_session.get(Quote, quote_id)
    quote.status = QuoteStatus.pending_approval
    db_session.commit()

    response = client.post(
        f"/worker/quotes/{quote_id}/items",
        json={"product_type": "awning", "material": "aluminium"},
    )
    assert response.status_code == 409

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "width", "value_mm": 2470}
    )
    assert response.status_code == 409


def test_can_add_items_and_dimensions_to_a_changes_requested_quote(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    quote = db_session.get(Quote, quote_id)
    quote.status = QuoteStatus.changes_requested
    db_session.commit()

    response = client.post(
        f"/worker/quotes/{quote_id}/items/{item_id}/dimensions", json={"field": "width", "value_mm": 2470}
    )
    assert response.status_code == 200

    response = client.post(
        f"/worker/quotes/{quote_id}/items",
        json={"product_type": "awning", "material": "aluminium"},
    )
    assert response.status_code == 200


def test_resubmit_rejects_when_not_changes_requested(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)  # still draft

    response = client.post(f"/worker/quotes/{quote_id}/resubmit", json={})

    assert response.status_code == 409


def test_resubmit_rejects_when_item_missing_dimensions(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    quote = db_session.get(Quote, quote_id)
    quote.status = QuoteStatus.changes_requested
    db_session.commit()

    response = client.post(f"/worker/quotes/{quote_id}/resubmit", json={})

    assert response.status_code == 422


def test_resubmit_succeeds_stores_note_and_enqueues_processing(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    item = db_session.get(Item, item_id)
    item.height_mm = 940
    item.width_mm = 2470
    quote = db_session.get(Quote, quote_id)
    quote.status = QuoteStatus.changes_requested
    db_session.commit()

    response = client.post(
        f"/worker/quotes/{quote_id}/resubmit", json={"note": "Added safety glass note as requested"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "extracted"
    worker_quotes.process_worker_submission.delay.assert_called_once_with(quote_id)

    quote = db_session.get(Quote, quote_id)
    assert len(quote.approval_comments) == 1
    assert quote.approval_comments[0].author == "tradie"
    assert quote.approval_comments[0].body == "Added safety glass note as requested"


def test_get_my_quote_includes_comment_thread(client, db_session, worker):
    quote_id, item_id = _quote_with_item(client, db_session, worker)
    db_session.add(
        ApprovalComment(quote_id=quote_id, author="owner", body="Needs safety glass", action="request_changes")
    )
    db_session.commit()

    detail = client.get(f"/worker/quotes/{quote_id}").json()

    assert len(detail["comments"]) == 1
    assert detail["comments"][0]["author"] == "owner"
    assert detail["comments"][0]["body"] == "Needs safety glass"
    assert detail["comments"][0]["action"] == "request_changes"


def test_set_property_details_updates_header_and_transitions_scheduled_to_draft(client, db_session, worker):
    quote = _make_quote(db_session, worker, status=QuoteStatus.scheduled)

    response = client.post(
        f"/worker/quotes/{quote.id}/property-details",
        json={
            "header": {"colour": "Surfmist", "glass": "double_glazed", "wind_rating": "1000"},
            "installation": {"building_type": "Residence", "asbestos": "no"},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"

    db_session.refresh(quote)
    assert quote.status == QuoteStatus.draft
    assert quote.header.colour == "Surfmist"
    assert quote.header.wind_rating == "1000"
    assert quote.installation.building_type == "Residence"
    assert quote.installation.asbestos == "no"


def test_set_property_details_never_overwrites_sales_supplied_client_fields(client, db_session, worker):
    quote = Quote(status=QuoteStatus.scheduled, assigned_tradie_id=worker.id)
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name="Sarah Williams", phone="0400 000 000"))
    db_session.commit()

    client.post(
        f"/worker/quotes/{quote.id}/property-details",
        json={"header": {"colour": "Surfmist"}, "installation": {}},
    )

    db_session.refresh(quote)
    assert quote.header.client_name == "Sarah Williams"
    assert quote.header.phone == "0400 000 000"
    assert quote.header.colour == "Surfmist"


def test_set_property_details_stays_editable_and_works_again_from_draft(client, db_session, worker):
    quote = _make_quote(db_session, worker, status=QuoteStatus.draft)

    response = client.post(
        f"/worker/quotes/{quote.id}/property-details",
        json={"header": {"colour": "Monument"}, "installation": {}},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "draft"  # unchanged, already draft


def test_set_property_details_can_be_called_twice_on_the_same_quote(client, db_session, worker):
    # Regression test: reassigning quote.installation to a brand-new
    # Installation() row while an old one already exists hits
    # installations.quote_id's UNIQUE constraint (SQLAlchemy doesn't
    # guarantee delete-before-insert ordering within one flush) — this
    # covers the tradie re-opening Property Details before moving on.
    quote = _make_quote(db_session, worker, status=QuoteStatus.scheduled)

    first = client.post(
        f"/worker/quotes/{quote.id}/property-details",
        json={"header": {"colour": "Monument"}, "installation": {"building_type": "Residence"}},
    )
    second = client.post(
        f"/worker/quotes/{quote.id}/property-details",
        json={"header": {"colour": "Surfmist"}, "installation": {"building_type": "Unit"}},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    db_session.refresh(quote)
    assert quote.header.colour == "Surfmist"
    assert quote.installation.building_type == "Unit"


def test_set_property_details_rejects_when_not_editable(client, db_session, worker):
    quote_id, _item_id = _quote_with_item(client, db_session, worker)
    quote = db_session.get(Quote, quote_id)
    quote.status = QuoteStatus.pending_approval
    db_session.commit()

    response = client.post(
        f"/worker/quotes/{quote_id}/property-details", json={"header": {}, "installation": {}}
    )

    assert response.status_code == 409


def test_report_missed_visit_sets_status_and_stores_reason(client, db_session, worker):
    quote = _make_quote(db_session, worker, status=QuoteStatus.scheduled)

    response = client.post(f"/worker/quotes/{quote.id}/missed", json={"reason": "weather"})

    assert response.status_code == 200
    assert response.json()["status"] == "missed"

    db_session.refresh(quote)
    assert quote.status == QuoteStatus.missed
    assert len(quote.approval_comments) == 1
    assert quote.approval_comments[0].author == "tradie"
    assert quote.approval_comments[0].action == "missed_visit"
    assert quote.approval_comments[0].body == "Weather"


def test_report_missed_visit_with_other_reason_includes_detail_text(client, db_session, worker):
    quote = _make_quote(db_session, worker, status=QuoteStatus.scheduled)

    response = client.post(
        f"/worker/quotes/{quote.id}/missed", json={"reason": "other", "other_detail": "Locked gate, no access"}
    )

    assert response.status_code == 200
    db_session.refresh(quote)
    assert quote.approval_comments[0].body == "Other: Locked gate, no access"


def test_report_missed_visit_rejects_when_not_scheduled(client, db_session, worker):
    quote = _make_quote(db_session, worker, status=QuoteStatus.draft)

    response = client.post(f"/worker/quotes/{quote.id}/missed", json={"reason": "weather"})

    assert response.status_code == 409
