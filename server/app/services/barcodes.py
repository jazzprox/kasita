"""Barcode lookup against the Open Food Facts family of databases.

Food is in Open Food Facts; household goods (toilet paper, detergent) are in
Open Products Facts; cosmetics in Open Beauty Facts. We ask them in that
order, then UPCitemdb's free tier as a last resort, and cache the answer,
found or not, so a scanned barcode costs at most one round of requests per
`barcode_cache_days`. Local store brands are in none of them: those become
household products the first time someone names them.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from ..config import settings
from ..models import BarcodeCache

log = logging.getLogger("kasita.barcodes")

SOURCES = [
    ("openfoodfacts", "https://world.openfoodfacts.org"),
    ("openproductsfacts", "https://world.openproductsfacts.org"),
    ("openbeautyfacts", "https://world.openbeautyfacts.org"),
]
FIELDS = "product_name,product_name_en,generic_name,brands,quantity,image_front_url,image_url,categories"
USER_AGENT = f"Kasita/0.1 ({settings.off_contact})"  # their API asks for an identifying User-Agent


def normalise(barcode: str) -> str | None:
    code = re.sub(r"\D", "", barcode or "")
    return code if 6 <= len(code) <= 18 else None


def _parse(source: str, data: dict) -> dict | None:
    if data.get("status") != 1:
        return None
    p = data.get("product") or {}
    name = (p.get("product_name") or p.get("product_name_en") or p.get("generic_name") or "").strip()
    if not name:
        return None
    return {
        "source": source,
        "name": name[:255],
        "brand": ((p.get("brands") or "").split(",")[0].strip() or None),
        "quantity_text": (p.get("quantity") or None),
        "image_url": p.get("image_front_url") or p.get("image_url"),
        "categories": p.get("categories"),
    }


def _upcitemdb(client: httpx.Client, barcode: str) -> dict | None:
    """Last resort: UPCitemdb's keyless trial tier (100 lookups/day, strong on US non-food)."""
    try:
        r = client.get("https://api.upcitemdb.com/prod/trial/lookup", params={"upc": barcode})
    except httpx.HTTPError as e:
        log.warning("barcode %s: upcitemdb unreachable (%s)", barcode, e)
        return None
    if r.status_code == 429:
        log.info("barcode %s: upcitemdb daily limit reached", barcode)
        return None
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    if not items or not items[0].get("title"):
        return None
    it = items[0]
    return {
        "source": "upcitemdb",
        "name": it["title"][:255],
        "brand": it.get("brand") or None,
        "quantity_text": it.get("size") or None,
        "image_url": (it.get("images") or [None])[0],
        "categories": it.get("category") or None,
    }


def fetch_remote(barcode: str, client: httpx.Client | None = None) -> dict | None:
    own = client is None
    client = client or httpx.Client(timeout=8, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    try:
        for source, base in SOURCES:
            try:
                r = client.get(f"{base}/api/v2/product/{barcode}.json", params={"fields": FIELDS})
            except httpx.HTTPError as e:
                log.warning("barcode %s: %s unreachable (%s)", barcode, source, e)
                continue
            if r.status_code == 404:
                continue
            if r.status_code != 200:
                log.warning("barcode %s: %s answered %s", barcode, source, r.status_code)
                continue
            hit = _parse(source, r.json())
            if hit:
                return hit
        return _upcitemdb(client, barcode)
    finally:
        if own:
            client.close()


def lookup(db: Session, barcode: str, *, refresh: bool = False, fetch=None) -> BarcodeCache:
    """Cached lookup. `fetch` is resolved at call time so tests can replace `fetch_remote`."""
    cached = db.get(BarcodeCache, barcode)
    fresh_until = datetime.now(timezone.utc) - timedelta(days=settings.barcode_cache_days)
    if cached and not refresh:
        fetched = cached.fetched_at if cached.fetched_at.tzinfo else cached.fetched_at.replace(tzinfo=timezone.utc)
        if fetched > fresh_until:
            return cached
    hit = (fetch or fetch_remote)(barcode)
    row = cached or BarcodeCache(barcode=barcode)
    row.found = bool(hit)
    for k in ("source", "name", "brand", "quantity_text", "image_url", "categories"):
        setattr(row, k, (hit or {}).get(k))
    row.fetched_at = datetime.now(timezone.utc)
    db.merge(row)
    db.commit()
    return db.get(BarcodeCache, barcode)
