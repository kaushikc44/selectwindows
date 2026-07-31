# tests/test_owner_quotes.py
import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_worker, hash_password
from app.db import get_db
from app.main import app
from app.models import (
    Base,
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
    w = Worker(username="marcus", name="Marcus Chen", hashed_password=hash_password("pw"))
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def client(db_session, owner, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: owner
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _quote(db_session, tradie=None, status=QuoteStatus.pending_approval, client_name="Sarah Williams") -> Quote:
    quote = Quote(status=status, assigned_tradie_id=tradie.id if tradie else None)
    db_session.add(quote)
    db_session.flush()
    db_session.add(QuoteHeader(quote_id=quote.id, client_name=client_name))
    db_session.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window, bathroom",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
            sill_height_mm=400,
        )
    )
    db_session.commit()
    return quote


def test_owner_endpoints_require_owner_role(db_session, tradie, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: tradie
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/owner/quotes")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_list_owner_queue_returns_pending_approval_quotes(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.get("/owner/quotes")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["quote_id"] == quote.id
    assert body[0]["client_name"] == "Sarah Williams"
    assert body[0]["tradie_name"] == "Marcus Chen"


def test_list_owner_queue_excludes_draft_quotes(client, db_session, tradie):
    _quote(db_session, tradie, status=QuoteStatus.draft)

    response = client.get("/owner/quotes")

    assert response.json() == []


def test_get_owner_quote_detail_includes_flags_items_and_sill_height(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    quote.flags = '[{"code": "as1288_safety_glass", "message": "Item 1: AS1288 Grade A safety glass mandatory"}]'
    db_session.commit()

    response = client.get(f"/owner/quotes/{quote.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["flags"][0]["code"] == "as1288_safety_glass"
    assert body["items"][0]["sill_height_mm"] == 400
    assert body["tradie_name"] == "Marcus Chen"
    assert body["agent_notes"] == []


def test_get_owner_quote_detail_includes_full_pricing_and_materials_breakdown(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    quote.items_subtotal = Decimal("500.00")
    quote.installation_subtotal = Decimal("150.00")
    quote.gst_amount = Decimal("65.00")
    quote.total = Decimal("715.00")
    quote.header.phone = "0400 000 000"
    quote.header.colour = "Surfmist"
    quote.installation = Installation(quote_id=quote.id, building_type="Residence", scaffold="yes")
    quote.items[0].qty = 2
    quote.items[0].unit_price = Decimal("250.00")
    quote.items[0].enrichment_json = json.dumps(
        {
            "glass_spec": "6mm single toughened",
            "hardware": ["lock", "hinge"],
            "frame_components": ["sill", "jamb"],
            "sealant_and_fixings": ["silicone"],
            "notes": "standard spec",
        }
    )
    db_session.commit()

    response = client.get(f"/owner/quotes/{quote.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["items_subtotal"] == "500.00"
    assert body["installation_subtotal"] == "150.00"
    assert body["gst_amount"] == "65.00"
    assert body["total"] == "715.00"
    assert body["header"]["phone"] == "0400 000 000"
    assert body["header"]["colour"] == "Surfmist"
    assert body["installation"]["building_type"] == "Residence"
    assert body["installation"]["scaffold"] == "yes"
    item = body["items"][0]
    assert item["qty"] == 2
    assert item["unit_price"] == "250.00"
    assert item["glass_spec"] == "6mm single toughened"
    assert item["hardware"] == ["lock", "hinge"]
    assert item["frame_components"] == ["sill", "jamb"]
    assert item["sealant_and_fixings"] == ["silicone"]
    assert item["enrichment_notes"] == "standard spec"


def test_get_owner_quote_404_for_a_draft_quote(client, db_session, tradie):
    quote = _quote(db_session, tradie, status=QuoteStatus.draft)

    response = client.get(f"/owner/quotes/{quote.id}")

    assert response.status_code == 404


def test_post_comment_approve_sets_status_approved(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "Looks good", "action": "approve"})

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.approved
    assert len(quote.approval_comments) == 1
    assert quote.approval_comments[0].author == "owner"
    assert quote.approval_comments[0].action == "approve"


def test_post_comment_reject_sets_status_rejected(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "Not viable", "action": "reject"})

    assert response.status_code == 200
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.rejected


def test_post_comment_request_changes_sets_status_and_creates_lesson(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.post(
        f"/owner/quotes/{quote.id}/comments",
        json={"body": "Needs safety glass for the low sill", "action": "request_changes"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "changes_requested"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.changes_requested

    lessons = db_session.query(LearnedLesson).all()
    assert len(lessons) == 1
    assert lessons[0].fix_summary == "Needs safety glass for the low sill"
    assert lessons[0].source_comment_id == quote.approval_comments[0].id


def test_post_plain_comment_does_not_change_status(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "Just checking in", "action": "comment"})

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.pending_approval
    assert len(quote.approval_comments) == 1
    assert quote.approval_comments[0].action is None


def test_post_comment_action_rejected_when_quote_already_approved(client, db_session, tradie):
    quote = _quote(db_session, tradie, status=QuoteStatus.approved)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "too late", "action": "approve"})

    assert response.status_code == 409


def test_post_comment_allowed_on_already_approved_quote(client, db_session, tradie):
    # A plain comment (no status transition) should still be addable to a
    # quote outside the actionable statuses — only approve/reject/
    # request_changes require pending_approval or needs_manual.
    quote = _quote(db_session, tradie, status=QuoteStatus.approved)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "great job", "action": "comment"})

    assert response.status_code == 200


def test_undo_auto_approval_with_reject(client, db_session, tradie):
    # An auto-approved quote (sitting in `approved` without Anthony clicking
    # Approve) is reversible — he can reject it to undo the auto-approval.
    quote = _quote(db_session, tradie, status=QuoteStatus.approved)

    response = client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "wrong call", "action": "reject"})

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.rejected


def test_undo_auto_approval_with_request_changes_creates_lesson(client, db_session, tradie):
    # Sending back an auto-approved quote works the same as a normal
    # request_changes — it records a LearnedLesson so the agent learns from
    # the undo, closing the loop on score-based auto-approval.
    quote = _quote(db_session, tradie, status=QuoteStatus.approved)

    response = client.post(
        f"/owner/quotes/{quote.id}/comments",
        json={"body": "Shouldn't have been auto-approved — low sill needs safety glass", "action": "request_changes"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "changes_requested"
    db_session.refresh(quote)
    assert quote.status == QuoteStatus.changes_requested
    lessons = db_session.query(LearnedLesson).all()
    assert len(lessons) == 1
    assert lessons[0].fix_summary == "Shouldn't have been auto-approved — low sill needs safety glass"


def test_get_owner_quote_returns_comment_thread(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    client.post(f"/owner/quotes/{quote.id}/comments", json={"body": "first pass", "action": "comment"})

    response = client.get(f"/owner/quotes/{quote.id}")

    assert len(response.json()["comments"]) == 1
    assert response.json()["comments"][0]["body"] == "first pass"


def _item_edit(item_id=None, **overrides) -> dict:
    base = {
        "item_id": item_id,
        "delete": False,
        "product_type": "awning",
        "material": "aluminium",
        "room": "Bathroom",
        "config_code": None,
        "qty": 1,
        "width_mm": 600,
        "height_mm": 900,
        "sill_height_mm": 400,
        "glass_spec": "",
        "hardware": [],
        "frame_components": [],
        "sealant_and_fixings": [],
        "enrichment_notes": None,
    }
    base.update(overrides)
    return base


def test_edit_quote_updates_header_and_installation(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah W. Williams", "colour": "Monument"},
            "installation": {"building_type": "Unit", "asbestos": "no"},
            "items": [_item_edit(item_id)],
        },
    )

    assert response.status_code == 200
    db_session.refresh(quote)
    assert quote.header.client_name == "Sarah W. Williams"
    assert quote.header.colour == "Monument"
    assert quote.installation.building_type == "Unit"
    assert quote.installation.asbestos == "no"


def test_edit_quote_updates_item_dimensions_and_recomputes_total(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit(item_id, width_mm=2400, height_mm=1800)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["width_mm"] == 2400
    assert body["items"][0]["height_mm"] == 1800
    assert body["total"] is not None


def test_edit_quote_adds_a_new_item(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit(item_id), _item_edit(None, room="Kitchen")],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 2
    assert [item["item_no"] for item in body["items"]] == [1, 2]


def test_edit_quote_deletes_an_item_and_renumbers(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id
    # start with two items
    client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit(item_id), _item_edit(None, room="Kitchen")],
        },
    )
    db_session.refresh(quote)
    first_id, second_id = [item.id for item in quote.items]

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit(first_id, delete=True), _item_edit(second_id)],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["item_no"] == 1
    assert body["items"][0]["item_id"] == second_id


def test_edit_quote_materials_override_uses_owner_edit_source_and_no_ai_flag(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit(item_id, glass_spec="6mm toughened, verified on site")],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["glass_spec"] == "6mm toughened, verified on site"
    assert not any(f["code"] in ("llm_material_estimate", "default_spec") for f in body["flags"])

    item = db_session.get(Item, item_id)
    assert json.loads(item.enrichment_json)["source"] == "owner_edit"


def test_edit_quote_rejects_when_not_actionable(client, db_session, tradie):
    quote = _quote(db_session, tradie, status=QuoteStatus.approved)
    item_id = quote.items[0].id

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={"header": {"client_name": "Sarah Williams"}, "installation": {}, "items": [_item_edit(item_id)]},
    )

    assert response.status_code == 409


def test_edit_quote_unknown_item_id_returns_404(client, db_session, tradie):
    quote = _quote(db_session, tradie)

    response = client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={
            "header": {"client_name": "Sarah Williams"},
            "installation": {},
            "items": [_item_edit("does-not-exist")],
        },
    )

    assert response.status_code == 404


def test_edit_quote_logs_an_approval_comment(client, db_session, tradie):
    quote = _quote(db_session, tradie)
    item_id = quote.items[0].id

    client.post(
        f"/owner/quotes/{quote.id}/edit",
        json={"header": {"client_name": "Sarah Williams"}, "installation": {}, "items": [_item_edit(item_id)]},
    )

    db_session.refresh(quote)
    edit_comments = [c for c in quote.approval_comments if c.action == "edit"]
    assert len(edit_comments) == 1
    assert edit_comments[0].author == "owner"
