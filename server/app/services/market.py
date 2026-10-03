"""Prices that shops publish online, matched to your products by barcode.

Mangusa Hypermarket (Curaçao's biggest supermarket) runs a WooCommerce web shop whose public store API lists
15,000+ products with barcodes and prices; its robots.txt allows crawling. Its SKU is the product's barcode WITHOUT
the check digit, left-padded to 13 (EAN-8 codes are padded as they are). We never mirror the catalogue: only the
barcodes this Kasita knows are asked for, one request per second, from a nightly job.

A SKU shows up as several entries: the product (often price 0, a placeholder), "(1 piece)" and a case "(24 pieces)".
The single-unit price is what we keep; when only a case exists, case price / pieces (noted).
"""
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import MarketPrice, MarketPriceChange, Product, ProductBarcode

log = logging.getLogger("kasita.market")
RETAILERS = {"mangusa": {"name": "Mangusa Hypermarket", "api": "https://www.mangusahypermarket.com/wp-json/wc/store/v1/products"}}
PAUSE_SECONDS = 1.0           # politeness: at most one request a second
STALE_DAYS = 3                # an offer not re-confirmed for this long is shown as "last seen ..."
_PIECES = re.compile(r"\((\d+)\s*pieces?\)\s*$", re.I)


def skus(barcode: str) -> list[str]:
    """The SKUs a barcode could be listed under, most likely first."""
    if not barcode.isdigit() or barcode.startswith("W") or len(barcode) < 6:
        return []
    out = [barcode.rjust(13, "0")]
    if len(barcode) in (12, 13):
        out.insert(0, barcode[:-1].rjust(13, "0"))  # UPC-A / EAN-13 without the check digit
    return list(dict.fromkeys(out))


def _money(minor: str | int, unit: int) -> Decimal:
    return (Decimal(str(minor)) / (Decimal(10) ** unit)).quantize(Decimal("0.01"))


def pick_offer(items: list[dict]) -> dict | None:
    """From the entries sharing one SKU, the single-unit offer: {"price","regular","on_sale","in_stock","pack_note",
    "name","url","image","category"}; None when nothing has a price."""
    best, case = None, None
    for it in items:
        pr = it.get("prices") or {}
        unit = int(pr.get("currency_minor_unit", 2))
        try:
            price = _money(pr.get("price", 0), unit)
        except Exception:  # noqa: BLE001
            continue
        if price <= 0:
            continue
        pieces = _PIECES.search(it.get("name", ""))
        n = int(pieces.group(1)) if pieces else 1
        regular = _money(pr.get("regular_price") or pr.get("price"), unit)
        cats = [c["name"] for c in it.get("categories") or []]
        offer = {"price": price, "regular": regular, "on_sale": bool(it.get("on_sale")) and price < regular,
                 "in_stock": bool(it.get("is_in_stock", True)), "pack_note": None,
                 "name": _PIECES.sub("", it.get("name", "")).strip(), "url": it.get("permalink"),
                 "image": ((it.get("images") or [{}])[0] or {}).get("src"),
                 "category": (cats[-1] if cats else None), "currency": pr.get("currency_code", "XCG")}
        if n == 1:
            if best is None or it.get("on_sale"):
                best = offer
        elif case is None or n > case[0]:
            case = (n, offer)
    if best:
        return best
    if case:
        n, o = case
        o = dict(o, price=(o["price"] / n).quantize(Decimal("0.01")), regular=(o["regular"] / n).quantize(Decimal("0.01")),
                 pack_note=f"case of {n}: {o['price']}")
        return o
    return None


def fetch_offer(client: httpx.Client, retailer: str, barcode: str) -> tuple[str, dict] | None:
    """(sku, offer) for the barcode at the retailer, or None when it isn't listed."""
    for sku in skus(barcode):
        r = client.get(RETAILERS[retailer]["api"], params={"sku": sku, "per_page": 20})
        if r.status_code != 200:
            raise httpx.HTTPStatusError(f"{r.status_code}", request=r.request, response=r)
        offer = pick_offer([x for x in r.json() if x.get("sku") == sku])
        if offer:
            return sku, offer
        time.sleep(PAUSE_SECONDS)
    return None


def store(db: Session, retailer: str, sku: str, offer: dict) -> bool:
    """Upsert the latest offer; log a change row when the price or sale flag moved. Returns True if it changed."""
    now = datetime.now(timezone.utc)
    row = db.scalar(select(MarketPrice).where(MarketPrice.retailer == retailer, MarketPrice.sku == sku))
    changed = row is None or row.price != offer["price"] or row.on_sale != offer["on_sale"]
    if row is None:
        row = MarketPrice(retailer=retailer, sku=sku, first_seen=now)
        db.add(row)
    row.name, row.price, row.regular_price = offer["name"][:255], offer["price"], offer["regular"]
    row.on_sale, row.in_stock, row.pack_note = offer["on_sale"], offer["in_stock"], offer["pack_note"]
    row.currency, row.url, row.image_url, row.category = offer["currency"], offer["url"], offer["image"], offer["category"]
    row.fetched_at = now
    if changed:
        db.add(MarketPriceChange(retailer=retailer, sku=sku, price=offer["price"], on_sale=offer["on_sale"], at=now))
    return changed


def refresh_all(db: Session, retailer: str = "mangusa", client: httpx.Client | None = None) -> dict:
    """Ask the retailer about every distinct barcode in this Kasita. Safe to run daily."""
    codes = sorted({c for (c,) in db.execute(select(ProductBarcode.barcode).join(Product, Product.id == ProductBarcode.product_id)
                                             .where(Product.archived.is_(False)))})
    own = client is None
    client = client or httpx.Client(timeout=30, follow_redirects=True,
                                    headers={"User-Agent": f"Kasita/1.0 price check ({settings.off_contact})"})
    found = changed = failed = 0
    try:
        for code in codes:
            if not skus(code):
                continue
            try:
                hit = fetch_offer(client, retailer, code)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("market %s: %s failed (%s)", retailer, code, e.__class__.__name__)
                failed += 1
                if failed >= 5:
                    break  # the shop is having a bad day: stop, try tomorrow
                continue
            if hit:
                found += 1
                changed += store(db, retailer, hit[0], hit[1])
            time.sleep(PAUSE_SECONDS)
        db.commit()
    finally:
        if own:
            client.close()
    return {"barcodes": len(codes), "found": found, "changed": changed, "failed": failed}


def offers_for_product(db: Session, product: Product) -> list[dict]:
    """Latest offers for the product's barcodes, with the previous price and the first time it was seen."""
    out, seen = [], set()
    for b in product.barcodes:
        for sku in skus(b.barcode):
            for row in db.scalars(select(MarketPrice).where(MarketPrice.sku == sku)):
                if (row.retailer, row.sku) in seen:
                    continue
                seen.add((row.retailer, row.sku))
                prev = db.scalar(select(MarketPriceChange.price).where(
                    MarketPriceChange.retailer == row.retailer, MarketPriceChange.sku == row.sku,
                    MarketPriceChange.price != row.price).order_by(MarketPriceChange.at.desc()).limit(1))
                fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
                out.append({"retailer": row.retailer, "store": RETAILERS[row.retailer]["name"], "name": row.name,
                            "price": row.price, "regular_price": row.regular_price, "on_sale": row.on_sale,
                            "in_stock": row.in_stock, "pack_note": row.pack_note, "currency": row.currency,
                            "url": row.url, "previous_price": prev, "checked": fetched,
                            "stale": fetched < datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)})
    return out


def shopping_market(db: Session, household_id: str) -> dict[str, dict]:
    """item id -> the offer for open shopping-list items that have one (for the list's hints)."""
    from ..models import ShoppingItem
    out = {}
    for it in db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == household_id,
                                                    ShoppingItem.done.is_(False), ShoppingItem.product_id.is_not(None))):
        offers = offers_for_product(db, it.product)
        if offers:
            o = min(offers, key=lambda x: x["price"])
            out[it.id] = {k: o[k] for k in ("store", "price", "regular_price", "on_sale", "in_stock", "currency", "url",
                                            "previous_price", "stale")}
    return out


def digest(db: Session, household_id: str) -> str | None:
    """Weekly note: products you own that are on sale, or moved >= 10% since last week, with the shop's price."""
    week = datetime.now(timezone.utc) - timedelta(days=8)
    lines = []
    for p in db.scalars(select(Product).where(Product.household_id == household_id, Product.archived.is_(False))):
        for o in offers_for_product(db, p):
            if o["stale"] or not o["in_stock"]:
                continue
            prev = o["previous_price"]
            moved = prev and abs(o["price"] - prev) / prev >= Decimal("0.10") and o["checked"] >= week
            if o["on_sale"]:
                lines.append(f"{p.name}: {o['price']} at {o['store']} (was {o['regular_price']}), on sale")
            elif moved:
                lines.append(f"{p.name}: {'down' if o['price'] < prev else 'up'} to {o['price']} (was {prev}) at {o['store']}")
    return ("Online prices for things you buy:\n" + "\n".join(f"• {x}" for x in lines[:12])) if lines else None
