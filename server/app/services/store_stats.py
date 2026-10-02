"""Where you shop: visits and spending per store, from booked receipts."""
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, Receipt, ReceiptLine, Store


def _receipt_total(r: Receipt) -> Decimal | None:
    if r.total is not None:
        return r.total
    totals = [ln.line_total for ln in r.lines if ln.line_total is not None and not ln.skip]
    return sum(totals) if totals else None


def _receipts(db: Session, household_id: str, days: int | None, store_id: str | None = None) -> list[Receipt]:
    stmt = select(Receipt).where(Receipt.household_id == household_id, Receipt.status == "confirmed",
                                 Receipt.store_id.is_not(None))
    if store_id:
        stmt = stmt.where(Receipt.store_id == store_id)
    if days:
        stmt = stmt.where(Receipt.purchased_on >= date.today() - timedelta(days=days))
    return list(db.scalars(stmt))


def _summary(receipts: list[Receipt]) -> dict:
    totals = [t for t in (_receipt_total(r) for r in receipts) if t is not None]
    spent = sum(totals, Decimal(0))
    days = [r.purchased_on or r.created_at.date() for r in receipts]
    return {"visits": len(receipts), "total": spent,
            "average": (spent / len(totals)).quantize(Decimal("0.01")) if totals else None,
            "first_visit": min(days) if days else None, "last_visit": max(days) if days else None}


def map_stores(db: Session, household_id: str, days: int | None = None) -> list[dict]:
    """Every store with its pin (if any) and how much was spent there: the map's pins."""
    by_store: dict[str, list[Receipt]] = defaultdict(list)
    for r in _receipts(db, household_id, days):
        by_store[r.store_id].append(r)
    out = []
    for s in db.scalars(select(Store).where(Store.household_id == household_id).order_by(Store.name)):
        out.append({"id": s.id, "name": s.name, "address": s.address, "lat": s.lat, "lon": s.lon,
                    "location_source": s.location_source, **_summary(by_store.get(s.id, []))})
    return out


def store_summary(db: Session, household_id: str, store: Store, days: int | None = None, top: int = 8) -> dict:
    """One store: visits, total spent, average basket and what you buy there most."""
    receipts = _receipts(db, household_id, days, store.id)
    lines = [ln for r in receipts for ln in r.lines if not ln.skip]
    names = {p.id: p.name for p in db.scalars(select(Product).where(
        Product.id.in_({ln.product_id for ln in lines if ln.product_id})))}
    count: Counter = Counter()
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for ln in lines:
        name = names.get(ln.product_id) or ln.name or ln.raw_text
        count[name] += 1
        if ln.line_total is not None:
            spent[name] += ln.line_total
    top_items = [{"name": n, "times": c, "spent": spent.get(n, Decimal(0))}
                 for n, c in sorted(count.items(), key=lambda kv: (-kv[1], -spent.get(kv[0], 0), kv[0]))[:top]]
    return {"id": store.id, "name": store.name, **_summary(receipts), "top_items": top_items}
