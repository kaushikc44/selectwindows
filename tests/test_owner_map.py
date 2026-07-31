# tests/test_owner_map.py
"""Anthony's job map (maps branch) — GET /owner/quotes/map. Owner-only,
geocodes each in-flight quote's house address to a NSW pin, cache-first so
re-opens don't re-geocode. Live Nominatim is mocked out so these run offline.
"""
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
    GeocodeCache,
    Item,
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


def _quote(db_session, status, client_address, tradie=None, client_name="Sarah Williams", delivery_address=None):
    quote = Quote(status=status, assigned_tradie_id=tradie.id if tradie else None)
    db_session.add(quote)
    db_session.flush()
    db_session.add(
        QuoteHeader(
            quote_id=quote.id,
            client_name=client_name,
            client_address=client_address,
            delivery_address=delivery_address,
        )
    )
    db_session.add(
        Item(
            quote_id=quote.id,
            item_no=1,
            description_raw="aluminium awning window, bathroom",
            product_type=ProductType.awning,
            material=Material.aluminium,
            height_mm=900,
            width_mm=600,
        )
    )
    db_session.commit()
    return quote


def test_owner_map_requires_owner_role(db_session, tradie, monkeypatch):
    """Only Anthony (owner) can see job locations — a tradie token is 403."""
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: tradie
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/owner/quotes/map")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_owner_map_returns_geocoded_pin(client, db_session, tradie, monkeypatch):
    """A pending-approval job at a known address becomes a "pending" pin
    pinpointed at the geocoded lat/lng."""
    _quote(db_session, QuoteStatus.pending_approval, "12 Smith St, Newtown NSW 2042", tradie)
    monkeypatch.setattr("app.api.owner_quotes.geocode_address", lambda addr: (-33.8976, 151.1797))

    response = client.get("/owner/quotes/map")

    assert response.status_code == 200
    body = response.json()
    assert body["unmapped"] == 0
    assert len(body["pins"]) == 1
    pin = body["pins"][0]
    assert pin["category"] == "pending"
    assert pin["status"] == "pending_approval"
    assert pin["lat"] == pytest.approx(-33.8976)
    assert pin["lng"] == pytest.approx(151.1797)
    assert pin["client_name"] == "Sarah Williams"
    assert pin["address"] == "12 smith st, newtown nsw 2042"


def test_owner_map_categorises_ongoing_work(client, db_session, tradie, monkeypatch):
    """An approved job and a scheduled site visit are "ongoing"; a pending
    one is "pending"; rejected never appears."""
    _quote(db_session, QuoteStatus.pending_approval, "1 Main St, Newtown NSW", tradie)
    _quote(db_session, QuoteStatus.approved, "2 Main St, Newtown NSW", tradie)
    _quote(db_session, QuoteStatus.scheduled, "3 Main St, Newtown NSW", tradie)
    _quote(db_session, QuoteStatus.rejected, "4 Main St, Newtown NSW", tradie)

    coords = {
        "1 main st, newtown nsw": (-33.89, 151.18),
        "2 main st, newtown nsw": (-33.90, 151.19),
        "3 main st, newtown nsw": (-33.91, 151.20),
    }
    monkeypatch.setattr("app.api.owner_quotes.geocode_address", lambda addr: coords.get(addr))

    body = client.get("/owner/quotes/map").json()

    by_address = {p["address"]: p for p in body["pins"]}
    assert by_address["1 main st, newtown nsw"]["category"] == "pending"
    assert by_address["2 main st, newtown nsw"]["category"] == "ongoing"
    assert by_address["3 main st, newtown nsw"]["category"] == "ongoing"
    # rejected is dead work, not ongoing — never pinned.
    assert "4 main st, newtown nsw" not in by_address
    assert len(body["pins"]) == 3


def test_owner_map_uses_cache_and_does_not_re_geocode(client, db_session, tradie, monkeypatch):
    """Two jobs at the same address → one live geocode, the second hits the
    cache. The whole point of GeocodeCache (Nominatim is 1 req/s)."""
    _quote(db_session, QuoteStatus.pending_approval, "12 Smith St, Newtown NSW", tradie, client_name="A")
    _quote(db_session, QuoteStatus.approved, "12 Smith St, Newtown NSW", tradie, client_name="B")

    calls = {"n": 0}

    def fake_geocode(addr):
        calls["n"] += 1
        return (-33.8976, 151.1797)

    monkeypatch.setattr("app.api.owner_quotes.geocode_address", fake_geocode)

    body = client.get("/owner/quotes/map").json()

    assert calls["n"] == 1
    assert len(body["pins"]) == 2
    # Cache row persisted so a re-open stays at zero live calls.
    cached = db_session.query(GeocodeCache).all()
    assert len(cached) == 1
    assert cached[0].resolved is True

    calls["n"] = 0
    body2 = client.get("/owner/quotes/map").json()
    assert calls["n"] == 0
    assert len(body2["pins"]) == 2


def test_owner_map_counts_unmapped_when_no_address(client, db_session, tradie, monkeypatch):
    """A job with no house address entered can't be pinpointed — surfaced in
    `unmapped`, not silently dropped."""
    _quote(db_session, QuoteStatus.pending_approval, None, tradie)
    monkeypatch.setattr("app.api.owner_quotes.geocode_address", lambda addr: None)

    body = client.get("/owner/quotes/map").json()

    assert body["pins"] == []
    assert body["unmapped"] == 1


def test_owner_map_caches_unresolvable_so_no_retry(client, db_session, tradie, monkeypatch):
    """An address Nominatim can't resolve is cached as resolved=False so a
    later map open doesn't burn another rate-limited call on it."""
    _quote(db_session, QuoteStatus.pending_approval, "Nowhere Real, NSW", tradie)
    calls = {"n": 0}

    def fake_geocode(addr):
        calls["n"] += 1
        return None

    monkeypatch.setattr("app.api.owner_quotes.geocode_address", fake_geocode)

    body = client.get("/owner/quotes/map").json()
    assert body["unmapped"] == 1
    assert body["pins"] == []
    first_calls = calls["n"]

    body2 = client.get("/owner/quotes/map").json()
    assert body2["unmapped"] == 1
    # No additional live lookup on the re-open.
    assert calls["n"] == first_calls


def test_owner_map_caps_live_lookups_per_request(client, db_session, tradie, monkeypatch):
    """More uncached jobs than GEOCODE_MAX_LOOKUPS_PER_REQUEST → only that
    many geocoded live this request, the rest counted unmapped (filled in on
    a later pass). Respects Nominatim's rate limit."""
    for i in range(12):
        _quote(db_session, QuoteStatus.pending_approval, f"{i} Cap St, Sydney NSW", tradie)

    calls = {"n": 0}

    def fake_geocode(addr):
        calls["n"] += 1
        return (-33.86, 151.21)

    monkeypatch.setattr("app.api.owner_quotes.geocode_address", fake_geocode)

    from app.api.owner_quotes import settings as oq_settings

    cap = oq_settings.GEOCODE_MAX_LOOKUPS_PER_REQUEST
    body = client.get("/owner/quotes/map").json()

    assert calls["n"] == cap
    assert len(body["pins"]) == cap
    assert body["unmapped"] == 12 - cap


def test_owner_map_falls_back_to_delivery_address(client, db_session, tradie, monkeypatch):
    """If the install address is missing, the delivery address is pinpointed."""
    _quote(
        db_session,
        QuoteStatus.approved,
        client_address=None,
        tradie=tradie,
        delivery_address="5 Dock St, Sydney NSW 2000",
    )
    monkeypatch.setattr("app.api.owner_quotes.geocode_address", lambda addr: (-33.86, 151.21))

    body = client.get("/owner/quotes/map").json()

    assert len(body["pins"]) == 1
    assert body["pins"][0]["address"] == "5 dock st, sydney nsw 2000"