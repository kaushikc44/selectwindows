# app/api/places.py
"""Server-side proxy to the Google Places API for the address autocomplete
picker in the Sales (new job) and Owner (edit quote) screens — see
mobile/src/components/AddressAutocomplete.tsx. The Google API key lives in
app/config.py::GOOGLE_PLACES_API_KEY and is never bundled into the mobile
app, so the app can't leak it.

Two endpoints, both gated by get_current_worker (any logged-in role — both
Sales and Owner edit addresses, so neither require_sales nor require_owner
is the right gate):

  GET /places/autocomplete?input=…  → [{place_id, description}, …]
  GET /places/details?place_id=…    → {formatted_address, lat, lng}

The details endpoint has a side effect: it upserts the place's lat/lng into
app/models.py::GeocodeCache, keyed by app/geocode.py::normalise_address of
the formatted_address — the same key app/api/owner_quotes.py::_map_address
uses to look coords up for Anthony's job map. So the moment a Sales rep
selects a place, the map can pin it on the next open with no extra
Nominatim lookup. This deliberately reuses the existing geocoding cache
rather than adding a parallel one.

Uses Google's legacy Places Autocomplete/Details JSON endpoints (simple
GETs, still supported). Swapping to the Places API (New) later would only
mean rewriting the two _google_* helpers below — the router shape stays.
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_worker
from app.config import settings
from app.db import get_db
from app.geocode import normalise_address
from app.models import GeocodeCache, Worker

router = APIRouter(prefix="/places", tags=["places"])

_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=10.0)
    return _client


def _require_key() -> str:
    key = settings.GOOGLE_PLACES_API_KEY
    if not key:
        raise HTTPException(status_code=503, detail="GOOGLE_PLACES_API_KEY not configured")
    return key


def _google_autocomplete(input_: str) -> list[dict]:
    """Raw call to Google Places Autocomplete. Module-level so tests can
    monkeypatch it (matching the function-level mock style in
    tests/test_owner_map.py) without touching httpx transport."""
    resp = _get_client().get(
        _AUTOCOMPLETE_URL,
        params={
            "input": input_,
            "key": _require_key(),
            "components": "country:au",  # bias to Australia — NSW-only map still rejects out-of-state pins downstream
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="google places autocomplete request failed")
    data = resp.json()
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        # e.g. INVALID_REQUEST, REQUEST_DENIED — surface the Google status so
        # the app shows something useful, not a generic 502.
        raise HTTPException(status_code=502, detail=f"google places error: {data.get('status')}")
    return [
        {"place_id": p["place_id"], "description": p["description"]}
        for p in data.get("predictions", [])
    ]


def _google_details(place_id: str) -> dict:
    """Raw call to Google Place Details → {formatted_address, lat, lng}.
    Module-level for the same monkeypatch reason as _google_autocomplete."""
    resp = _get_client().get(
        _DETAILS_URL,
        params={
            "place_id": place_id,
            "key": _require_key(),
            "fields": "formatted_address,geometry",
        },
    )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="google places details request failed")
    data = resp.json()
    if data.get("status") != "OK":
        raise HTTPException(status_code=502, detail=f"google places error: {data.get('status')}")
    result = data.get("result") or {}
    location = (result.get("geometry") or {}).get("location") or {}
    return {
        "formatted_address": result.get("formatted_address", ""),
        "lat": location.get("lat"),
        "lng": location.get("lng"),
    }


@router.get("/autocomplete", response_model=list[dict])
def autocomplete(
    input: str = Query(..., min_length=1),
    worker: Worker = Depends(get_current_worker),
) -> list[dict]:
    return _google_autocomplete(input)


@router.get("/details")
def details(
    place_id: str = Query(..., min_length=1),
    worker: Worker = Depends(get_current_worker),
    db: Session = Depends(get_db),
) -> dict:
    result = _google_details(place_id)
    address = result.get("formatted_address") or ""
    lat = result.get("lat")
    lng = result.get("lng")

    # Upsert the GeocodeCache so the owner's job map pins this address on
    # the next open without a Nominatim lookup. Keyed on the same
    # normalise_address the map's read path uses. Best-effort — a cache
    # miss here just means the map falls back to live geocoding later.
    if address and lat is not None and lng is not None:
        key = normalise_address(address)
        row = db.scalars(select(GeocodeCache).where(GeocodeCache.address == key)).first()
        if row is None:
            row = GeocodeCache(address=key, lat=lat, lng=lng, resolved=True)
            db.add(row)
        else:
            row.lat = lat
            row.lng = lng
            row.resolved = True
        db.commit()

    return {"formatted_address": address, "lat": lat, "lng": lng}