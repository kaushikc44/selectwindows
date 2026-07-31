# app/geocode.py
"""Address → lat/lng geocoding for Anthony's job map (maps branch).

Nominatim (OpenStreetMap) is free and needs no API key, which fits this PoC —
no Google/Mapbox billing. Two constraints shape the design:

  * Nominatim's usage policy is 1 request/second. A single map open can show
    many jobs, so we throttle live lookups and cap how many uncached addresses
    one request will resolve (see app/config.py::GEOCODE_MAX_LOOKUPS_PER_REQUEST).
    Cached results (app/models.py::GeocodeCache) return instantly and don't
    count against the rate limit.
  * This is NSW, Australia only. We bias the search with a NSW viewbox +
    `bounded=1` and `countrycodes=au`, then defensively re-check the returned
    point is inside the NSW bounding box — a wrong-state pin is worse than no
    pin, since Anthony is pinpointing houses to visit.
"""

import re
import threading
import time

import httpx

from app.config import settings

# NSW mainland bounding box (lon/lat). Source: standard NSW state extents,
# mainland only — Lord Howe Island (~159°E) is deliberately excluded; nobody
# is driving to a job there from the mainland.
NSW_WEST = 140.99
NSW_EAST = 153.99
NSW_NORTH = -28.16
NSW_SOUTH = -37.51

# Nominatim viewbox is "<left_lon>,<top_lat>,<right_lon>,<bottom_lat>".
NSW_VIEWBOX = f"{NSW_WEST},{NSW_NORTH},{NSW_EAST},{NSW_SOUTH}"

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Rate-limit machinery — module-global so concurrent requests share it.
_last_call_lock = threading.Lock()
_last_call_at: float = 0.0
_MIN_INTERVAL = 1.05  # seconds between live Nominatim calls (policy: 1/s)

_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(timeout=10.0, headers={"User-Agent": settings.GEOCODE_USER_AGENT})
    return _client


def normalise_address(raw: str | None) -> str:
    """Canonical form used for both the GeocodeCache key and lookup — case
    and whitespace insensitive so "12 Main St, Newtown NSW" and
    "12 main st  newton nsw" hit one row."""
    if not raw:
        return ""
    s = raw.strip().lower()
    s = re.sub(r"\s+", " ", s)
    # Collapse ", ," → "," and trim trailing commas/whitespace that come from
    # partial form fields being concatenated.
    s = re.sub(r",\s*,", ",", s)
    s = s.strip(" ,")
    return s


def _in_nsw(lat: float, lng: float) -> bool:
    return NSW_SOUTH <= lat <= NSW_NORTH and NSW_WEST <= lng <= NSW_EAST


def _throttle() -> None:
    """Block until at least _MIN_INTERVAL has elapsed since the last live
    call. Serialised by _last_call_lock so two threads don't both sleep and
    then fire together."""
    with _last_call_lock:
        global _last_call_at
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def geocode_address(address: str) -> tuple[float, float] | None:
    """Pinpoint a NSW address as (lat, lng), or None if it can't be resolved
    or the result falls outside NSW. Network call — caller is responsible for
    throttling/capping (see resolve_for_map below)."""
    if not settings.GEOCODE_ENABLED:
        return None
    _throttle()
    try:
        resp = _get_client().get(
            _NOMINATIM_URL,
            params={
                "q": address,
                "format": "jsonv2",
                "countrycodes": "au",
                "viewbox": NSW_VIEWBOX,
                "bounded": "1",
                "addressdetails": "1",
                "limit": "1",
            },
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data:
            return None
        hit = data[0]
        lat = float(hit["lat"])
        lng = float(hit["lon"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None
    if not _in_nsw(lat, lng):
        return None
    return lat, lng