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
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import BarcodeCache

log = logging.getLogger("kasita.barcodes")

SOURCES = [
    ("openfoodfacts", "https://world.openfoodfacts.org"),
    ("openproductsfacts", "https://world.openproductsfacts.org"),
    ("openbeautyfacts", "https://world.openbeautyfacts.org"),
]
FIELDS = ("product_name,product_name_en,generic_name,brands,quantity,image_front_url,image_url,categories,"
          "nutriscore_grade,nova_group,nutriments")
# per-100 g/ml values kept from Open Food Facts' "nutriments"
NUTRIENTS = {"kcal": "energy-kcal_100g", "sugars": "sugars_100g", "fat": "fat_100g",
             "saturated_fat": "saturated-fat_100g", "salt": "salt_100g", "protein": "proteins_100g",
             "fiber": "fiber_100g"}
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
    grade = (p.get("nutriscore_grade") or "").lower()
    try:
        nova = int(p.get("nova_group")) if p.get("nova_group") not in (None, "") else None
    except (TypeError, ValueError):
        nova = None
    raw = p.get("nutriments") or {}
    nutrients = {}
    for k, field in NUTRIENTS.items():
        try:
            if raw.get(field) not in (None, ""):
                nutrients[k] = round(float(raw[field]), 2)
        except (TypeError, ValueError):
            pass
    return {
        "source": source,
        "name": name[:255],
        "brand": ((p.get("brands") or "").split(",")[0].strip() or None),
        "quantity_text": (p.get("quantity") or None),
        "image_url": p.get("image_front_url") or p.get("image_url"),
        "categories": p.get("categories"),
        "nutriscore": grade if grade in ("a", "b", "c", "d", "e") else None,
        "nova": nova if nova in (1, 2, 3, 4) else None,
        "nutrients": nutrients or None,
    }


RETRY_HOURS = 6  # how long a "not found" is trusted when some database could not be asked


class Incomplete(Exception):
    """No database had the product, but at least one could not be asked (timeout, error,
    daily limit). Not a real "not found", so it must not be remembered for 30 days."""


_kroger_token: tuple[str, float] | None = None  # (token, expires at)


def kroger_id(barcode: str) -> str | None:
    """Kroger keys products by the barcode WITHOUT its check digit, left-padded to 13:
    UPC-A 049000028904 -> 0004900002890. Only 12/13-digit codes."""
    if len(barcode) not in (12, 13):
        return None
    return barcode[:-1].rjust(13, "0")


def _kroger(client: httpx.Client, barcode: str) -> dict | None:
    """Kroger's product catalogue: strong on US groceries (the imports on Curaçao shelves)."""
    global _kroger_token
    pid = kroger_id(barcode)
    if not pid or not settings.kroger_client_id:
        return None
    import time
    try:
        if not _kroger_token or _kroger_token[1] < time.time() + 60:
            t = client.post("https://api.kroger.com/v1/connect/oauth2/token",
                            auth=(settings.kroger_client_id, settings.kroger_client_secret),
                            data={"grant_type": "client_credentials", "scope": "product.compact"})
            if t.status_code != 200:
                log.warning("barcode %s: kroger token refused (%s)", barcode, t.status_code)
                raise Incomplete
            b = t.json()
            _kroger_token = (b["access_token"], time.time() + int(b.get("expires_in", 1800)))
        r = client.get(f"https://api.kroger.com/v1/products/{pid}",
                       headers={"Authorization": f"Bearer {_kroger_token[0]}", "Accept": "application/json"})
    except httpx.HTTPError as e:
        log.warning("barcode %s: kroger unreachable (%s)", barcode, e)
        raise Incomplete from e
    if r.status_code in (400, 404):
        return None
    if r.status_code != 200:
        log.warning("barcode %s: kroger answered %s", barcode, r.status_code)
        raise Incomplete
    p = (r.json() or {}).get("data") or {}
    if not p.get("description"):
        return None
    image = None
    for img in p.get("images") or []:
        sizes = {s.get("size"): s.get("url") for s in img.get("sizes") or []}
        url = sizes.get("large") or sizes.get("medium") or next(iter(sizes.values()), None)
        if url and (img.get("perspective") == "front" or image is None):
            image = url
    return {
        "source": "kroger",
        "name": p["description"][:255],
        "brand": p.get("brand") or None,
        "quantity_text": ((p.get("items") or [{}])[0].get("size") or None),
        "image_url": image,
        "categories": ", ".join(p.get("categories") or []) or None,
    }


def _upcitemdb(client: httpx.Client, barcode: str) -> dict | None:
    """Last resort: UPCitemdb's keyless trial tier (100 lookups/day, strong on US non-food)."""
    try:
        r = client.get("https://api.upcitemdb.com/prod/trial/lookup", params={"upc": barcode})
    except httpx.HTTPError as e:
        log.warning("barcode %s: upcitemdb unreachable (%s)", barcode, e)
        raise Incomplete from e
    if r.status_code == 429:
        log.info("barcode %s: upcitemdb daily limit reached", barcode)
        raise Incomplete
    if r.status_code != 200:
        log.warning("barcode %s: upcitemdb answered %s", barcode, r.status_code)
        raise Incomplete
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


def _upcdatabase(client: httpx.Client, barcode: str) -> dict | None:
    """Last fallback: upcdatabase.org free plan (100/day). Thin data (often just a brand-ish
    title), so it is only asked when every other source came up empty."""
    if not settings.upcdatabase_token:
        return None
    try:
        # the key goes in the query string: their API rejects it as a Bearer header
        r = client.get(f"https://api.upcdatabase.org/product/{barcode}",
                       params={"apikey": settings.upcdatabase_token})
    except httpx.HTTPError as e:
        log.warning("barcode %s: upcdatabase unreachable (%s)", barcode, e)
        raise Incomplete from e
    if r.status_code == 429:
        raise Incomplete
    try:
        d = r.json()
    except ValueError:
        raise Incomplete
    if not d.get("success"):
        msg = ((d.get("error") or {}).get("message") or "").lower()
        if "not found" in msg:
            return None
        log.warning("barcode %s: upcdatabase error (%s)", barcode, msg[:80])
        raise Incomplete
    title = (d.get("title") or d.get("description") or "").strip()
    if not title:
        return None
    images = d.get("images") or []
    return {
        "source": "upcdatabase",
        "name": title[:255],
        "brand": d.get("brand") or None,
        "quantity_text": d.get("size") or None,
        "image_url": images[0] if isinstance(images, list) and images else None,
        "categories": d.get("category") or None,
    }


def fetch_remote(barcode: str, client: httpx.Client | None = None) -> dict | None:
    own = client is None
    client = client or httpx.Client(timeout=8, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    failed = False
    try:
        for source, base in SOURCES:
            try:
                r = client.get(f"{base}/api/v2/product/{barcode}.json", params={"fields": FIELDS})
            except httpx.HTTPError as e:
                log.warning("barcode %s: %s unreachable (%s)", barcode, source, e)
                failed = True
                continue
            if r.status_code == 404:
                continue
            if r.status_code != 200:
                log.warning("barcode %s: %s answered %s", barcode, source, r.status_code)
                failed = True
                continue
            hit = _parse(source, r.json())
            if hit:
                return hit
        # Kroger first (spares UPCitemdb's 100/day); upcdatabase last (thin data, 100/day)
        for extra in (_kroger, _upcitemdb, _upcdatabase):
            try:
                hit = extra(client, barcode)
            except Incomplete:
                failed = True
                continue
            if hit:
                return hit
        if failed:
            raise Incomplete
        return None
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
    now = datetime.now(timezone.utc)
    try:
        hit = (fetch or fetch_remote)(barcode)
        checked_at = now
    except Incomplete:
        if cached and cached.found:
            return cached  # an older real answer beats a failed refresh
        hit = None
        # remember this "not found" for RETRY_HOURS only: date it so it expires then
        checked_at = now - timedelta(days=settings.barcode_cache_days) + timedelta(hours=RETRY_HOURS)
    row = cached or BarcodeCache(barcode=barcode)
    row.found = bool(hit)
    for k in ("source", "name", "brand", "quantity_text", "image_url", "categories", "nutriscore", "nova",
              "nutrients"):
        setattr(row, k, (hit or {}).get(k))
    row.fetched_at = checked_at
    db.merge(row)
    db.commit()
    return db.get(BarcodeCache, barcode)


def _gtin13(code: str) -> str | None:
    return code.rjust(13, "0") if code.isdigit() and len(code) in (12, 13) else None


def brand_hint(db: Session, household_id: str, barcode: str) -> str | None:
    """The maker of an unknown barcode, from its GS1 company prefix.

    Every barcode starts with its owner's company number (041224... = Roland). If
    known products (this household's, or found in the public databases) share a long
    enough start with it AND all agree on one brand, that brand is a safe guess.
    US/Canada codes (leading 0) need 7 shared digits, others 8 (their prefixes are longer).
    """
    from ..models import Product, ProductBarcode  # local: models import this module's settings
    target = _gtin13(barcode)
    if not target:
        return None
    pairs = [(b, br) for b, br in db.execute(
        select(ProductBarcode.barcode, Product.brand).join(Product, Product.id == ProductBarcode.product_id)
        .where(ProductBarcode.household_id == household_id, Product.brand.is_not(None)))]
    pairs += [(b, br) for b, br in db.execute(
        select(BarcodeCache.barcode, BarcodeCache.brand).where(BarcodeCache.found.is_(True),
                                                             BarcodeCache.brand.is_not(None)))]
    need = 7 if target.startswith("0") else 8
    best, brands = 0, set()
    for code, brand in pairs:
        other = _gtin13(code)
        if not other or other == target:
            continue
        n = 0
        while n < 12 and other[n] == target[n]:
            n += 1
        if n < need:
            continue
        name = brand.split(",")[0].strip()
        if n > best:
            best, brands = n, {name.lower(): name}
        elif n == best:
            brands[name.lower()] = name
    return next(iter(brands.values())) if best and len(brands) == 1 else None
