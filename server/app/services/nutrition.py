"""The basket's health: priced purchases grouped by Open Food Facts' Nutri-Score (a..e) and
NOVA group (4 = ultra-processed). Only barcoded products can be rated; the rest is "unrated"."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BarcodeCache, Household, Product, ProductBarcode, StockEvent


def ratings(db: Session, product_ids: set[str]) -> dict[str, dict]:
    """product id -> {"nutriscore", "nova", "sugars"} from the first rated barcode."""
    rows = db.execute(select(ProductBarcode.product_id, BarcodeCache.nutriscore, BarcodeCache.nova,
                             BarcodeCache.nutrients)
                      .join(BarcodeCache, BarcodeCache.barcode == ProductBarcode.barcode)
                      .where(ProductBarcode.product_id.in_(product_ids), BarcodeCache.found.is_(True))).all()
    out: dict[str, dict] = {}
    for pid, grade, nova, nutrients in rows:
        r = out.setdefault(pid, {"nutriscore": None, "nova": None, "sugars": None})
        r["nutriscore"] = r["nutriscore"] or grade
        r["nova"] = r["nova"] or nova
        if r["sugars"] is None and nutrients and nutrients.get("sugars") is not None:
            r["sugars"] = nutrients["sugars"]
    return out


def report(db: Session, household_id: str, days: int = 30) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(select(StockEvent.product_id, StockEvent.quantity, StockEvent.unit_price, Product.name)
                      .join(Product, Product.id == StockEvent.product_id)
                      .where(StockEvent.household_id == household_id, StockEvent.kind == "purchase",
                             StockEvent.unit_price.is_not(None), StockEvent.at >= since)).all()
    rate = ratings(db, {r[0] for r in rows})
    grades = {g: Decimal(0) for g in ("a", "b", "c", "d", "e", "unrated")}
    nova = {n: Decimal(0) for n in (1, 2, 3, 4)}
    by_product: dict[str, list] = {}
    total = Decimal(0)
    for pid, qty, price, name in rows:
        amount = (qty * price).quantize(Decimal("0.01"))
        total += amount
        r = rate.get(pid, {})
        grades[r.get("nutriscore") or "unrated"] += amount
        if r.get("nova"):
            nova[r["nova"]] += amount
        b = by_product.setdefault(pid, [name, Decimal(0), r.get("nutriscore"), r.get("nova"), r.get("sugars")])
        b[1] += amount
    rated = total - grades["unrated"]
    worst = sorted((b for b in by_product.values() if b[2] in ("d", "e")), key=lambda b: -b[1])[:8]
    h = db.get(Household, household_id)

    def pct(x: Decimal, of: Decimal) -> int | None:
        return round(float(x / of) * 100) if of else None
    return {
        "days": days, "currency": h.currency if h else "XCG", "total": total, "rated": rated,
        "rated_pct": pct(rated, total),
        "by_grade": [{"grade": g, "amount": v, "pct": pct(v, rated) if g != "unrated" else pct(v, total)}
                     for g, v in grades.items()],
        "by_nova": [{"nova": n, "amount": v, "pct": pct(v, sum(nova.values(), Decimal(0)))} for n, v in nova.items()],
        "ultra_processed_pct": pct(nova[4], sum(nova.values(), Decimal(0))),
        "top_d_e": [{"name": b[0], "amount": b[1], "nutriscore": b[2], "nova": b[3], "sugars": b[4]} for b in worst],
    }
