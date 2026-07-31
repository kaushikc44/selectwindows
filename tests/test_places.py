# tests/test_places.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import get_current_worker, hash_password
from app.db import get_db
from app.geocode import normalise_address
from app.main import app
from app.models import Base, GeocodeCache, Worker, WorkerRole


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def worker(db_session):
    w = Worker(username="salesrep", name="Sales Rep", hashed_password=hash_password("pw"), role=WorkerRole.sales)
    db_session.add(w)
    db_session.commit()
    return w


@pytest.fixture()
def client(db_session, worker, monkeypatch):
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_worker] = lambda: worker
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_autocomplete_returns_suggestions(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.places._google_autocomplete",
        lambda input_: [{"place_id": "abc", "description": "12 Main St, Newtown NSW"}, {"place_id": "def", "description": "12 Main Rd, Sydney NSW"}],
    )
    response = client.get("/places/autocomplete", params={"input": "12 Main"})

    assert response.status_code == 200
    assert response.json() == [
        {"place_id": "abc", "description": "12 Main St, Newtown NSW"},
        {"place_id": "def", "description": "12 Main Rd, Sydney NSW"},
    ]


def test_details_returns_address_and_caches_coords(client, db_session, monkeypatch):
    monkeypatch.setattr(
        "app.api.places._google_details",
        lambda place_id: {"formatted_address": "12 Main St, Newtown NSW 2042", "lat": -33.8976, "lng": 151.1797},
    )

    response = client.get("/places/details", params={"place_id": "abc"})

    assert response.status_code == 200
    body = response.json()
    assert body["formatted_address"] == "12 Main St, Newtown NSW 2042"
    assert body["lat"] == -33.8976
    assert body["lng"] == 151.1797

    # The lat/lng must be cached under the same normalised key the owner map
    # reads, so the next map open pins without a Nominatim lookup.
    row = db_session.scalars(
        select(GeocodeCache).where(GeocodeCache.address == normalise_address("12 Main St, Newtown NSW 2042"))
    ).first()
    assert row is not None
    assert row.resolved is True
    assert row.lat == -33.8976
    assert row.lng == 151.1797


def test_details_updates_existing_cache_row(client, db_session, monkeypatch):
    # An unresolved cache row already exists (e.g. Nominatim couldn't pin it);
    # selecting the place via Google should update it in place rather than
    # create a duplicate (the address column is unique).
    db_session.add(
        GeocodeCache(address=normalise_address("12 Main St, Newtown NSW 2042"), lat=None, lng=None, resolved=False)
    )
    db_session.commit()

    monkeypatch.setattr(
        "app.api.places._google_details",
        lambda place_id: {"formatted_address": "12 Main St, Newtown NSW 2042", "lat": -33.8976, "lng": 151.1797},
    )

    response = client.get("/places/details", params={"place_id": "abc"})
    assert response.status_code == 200

    rows = db_session.scalars(
        select(GeocodeCache).where(GeocodeCache.address == normalise_address("12 Main St, Newtown NSW 2042"))
    ).all()
    assert len(rows) == 1  # no duplicate
    assert rows[0].resolved is True
    assert rows[0].lat == -33.8976


def test_returns_503_when_key_not_configured(client, monkeypatch):
    # Real _google_autocomplete (not monkeypatched) calls _require_key, which
    # raises 503 before any network call when the key is blank.
    monkeypatch.setattr("app.api.places.settings.GOOGLE_PLACES_API_KEY", "")
    response = client.get("/places/autocomplete", params={"input": "12 Main"})
    assert response.status_code == 503
    assert "GOOGLE_PLACES_API_KEY" in response.json()["detail"]


def test_requires_authentication(db_session, monkeypatch):
    # No get_current_worker override → real JWT bearer dependency → 401
    # without a token. Mirrors the require-role test in test_sales_quotes.py.
    def _get_db_override():
        yield db_session

    monkeypatch.setattr("app.main.create_all", lambda: None)
    app.dependency_overrides[get_db] = _get_db_override
    try:
        with TestClient(app) as test_client:
            response = test_client.get("/places/autocomplete", params={"input": "12 Main"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401