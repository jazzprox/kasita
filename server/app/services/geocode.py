"""Find stores on the map with OpenStreetMap's Nominatim.

Nominatim's usage policy: an identifying User-Agent, at most one request per second, and
cache what you get. Each search is cached here (found or not) in `GeocodeCache`; a miss is
asked again only after `geocode_retry_days`. A store the user placed by hand is never
geocoded again.

Curaçao addresses are written street first, number last ("Cas Coraweg 78") and often
geocode poorly, so a store is tried as: the address as printed, then the structured street
("78 Cas Coraweg", which is how Nominatim wants a structured street), then the store's name.
Nothing found = the store stays off the map until someone places it.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import GeocodeCache, Store
from .receipts import split_address

log = logging.getLogger("kasita.geocode")

_lock = threading.Lock()
_last_call = 0.0


def nominatim_search(params: dict) -> list[dict]:
    """One request to Nominatim's /search, at most one per second across the whole server.
    Tests replace this function."""
    global _last_call
    with _lock:
        wait = 1.05 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            r = httpx.get(f"{settings.nominatim_url.rstrip('/')}/search",
                          params={**params, "format": "jsonv2", "limit": 1,
                                  "countrycodes": settings.nominatim_country},
                          headers={"User-Agent": settings.nominatim_user_agent}, timeout=15)
            r.raise_for_status()
            return r.json()
        finally:
            _last_call = time.monotonic()


def _cached_search(db: Session, params: dict) -> tuple[float, float] | None:
    key = "&".join(f"{k}={v}" for k, v in sorted(params.items())).lower()[:400]
    row = db.get(GeocodeCache, key)
    now = datetime.now(timezone.utc)
    if row is not None:
        fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
        if row.lat is not None or now - fetched < timedelta(days=settings.geocode_retry_days):
            return (row.lat, row.lon) if row.lat is not None else None
    try:
        hits = nominatim_search(params)
    except (httpx.HTTPError, ValueError) as e:
        log.warning("nominatim search failed: %r", e)
        return None  # not cached: a network hiccup is not an answer
    hit = hits[0] if hits else None
    lat, lon = (float(hit["lat"]), float(hit["lon"])) if hit else (None, None)
    if row is None:
        row = GeocodeCache(query=key)
        db.add(row)
    row.lat, row.lon, row.fetched_at = lat, lon, now
    row.label = (hit.get("display_name") or "")[:400] if hit else None
    db.flush()
    return (lat, lon) if hit else None


def searches(store: Store) -> list[dict]:
    """What to ask Nominatim for this store, best first."""
    out = []
    if store.address:
        out.append({"q": f"{store.address}, Curaçao"})
        street, number = split_address(store.address)
        if number:
            out.append({"street": f"{number} {street}", "country": "Curaçao"})
    if store.name:
        out.append({"q": f"{store.name}, Curaçao"})
    return out


def geocode_store(db: Session, store: Store) -> bool:
    """Put the store on the map from its address or name. True when it got a location.
    Never touches a store placed by hand."""
    if not settings.nominatim_url or store.location_source == "manual":
        return False
    for params in searches(store):
        found = _cached_search(db, params)
        if found:
            store.lat, store.lon = found
            store.location_source = "geocoded"
            return True
    return False


def geocode_store_id(store_id: str) -> None:
    """Background job (after a receipt or an edit gave a store its address). Own session."""
    with SessionLocal() as db:
        store = db.get(Store, store_id)
        if store is not None:
            try:
                geocode_store(db, store)
                db.commit()
            except Exception as e:  # noqa: BLE001  (a map pin is never worth failing for)
                log.warning("geocoding store %s failed: %r", store_id, e)
                db.rollback()


def geocode_all(db: Session, *, redo: bool = False) -> list[tuple[str, str]]:
    """Every store without a location (or, with `redo`, every geocoded one too). Never manual pins."""
    stmt = select(Store).where(Store.location_source.is_distinct_from("manual"))
    if not redo:
        stmt = stmt.where(Store.lat.is_(None))
    out = []
    for store in db.scalars(stmt.order_by(Store.name)):
        ok = geocode_store(db, store)
        db.commit()
        out.append((store.name, f"{store.lat:.5f}, {store.lon:.5f}" if ok else "not found"))
    return out
