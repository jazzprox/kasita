"""Prices from purchases (receipts, or typed when buying): where is it cheapest, what went up."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, ShoppingItem, StockEvent, Store

RISE_PCT = Decimal("0.10")      # a rise worth mentioning: at least 10%...
RISE_MIN = Decimal("0.25")      # ...and at least this much money


def latest_by_store(db: Session, household_id: str, days: int = 180) -> dict[str, dict[str, tuple[Decimal, datetime]]]:
    """product_id -> {store name: (latest unit price, when)} over the last `days`."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(StockEvent.product_id, Store.name, StockEvent.unit_price, StockEvent.at)
        .join(Store, Store.id == StockEvent.store_id)
        .where(StockEvent.household_id == household_id, StockEvent.kind == "purchase",
               StockEvent.unit_price.is_not(None), StockEvent.at >= since)
        .order_by(StockEvent.at)
    ).all()
    out: dict[str, dict[str, tuple[Decimal, datetime]]] = {}
    for pid, store, price, at in rows:  # oldest first, so the latest wins
        out.setdefault(pid, {})[store] = (price, at)
    return out


def cheapest_split(db: Session, household_id: str) -> list[dict]:
    """Open shopping items grouped by the store where each was cheapest last time."""
    latest = latest_by_store(db, household_id)
    items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == household_id,
                                                  ShoppingItem.done.is_(False)).order_by(ShoppingItem.created_at)).all()
    groups: dict[str, dict] = {}
    for it in items:
        prices = latest.get(it.product_id or "", {})
        if prices:
            store, (price, _) = min(prices.items(), key=lambda kv: kv[1][0])
            others = {s: float(p) for s, (p, _) in prices.items() if s != store}
        else:
            store, price, others = "Anywhere (no prices yet)", None, {}
        g = groups.setdefault(store, {"store": store, "items": [], "total": Decimal(0), "priced": 0})
        g["items"].append({"id": it.id, "name": it.name, "quantity": it.quantity, "price": price, "elsewhere": others})
        if price is not None:
            g["total"] += price * it.quantity
            g["priced"] += 1
    # stores with the most items first; "Anywhere" last
    return sorted(groups.values(), key=lambda g: (g["store"].startswith("Anywhere"), -len(g["items"])))


def price_changes(db: Session, household_id: str, days: int = 7) -> list[dict]:
    """Purchases in the last `days` that cost noticeably more than the previous time at the same store."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = db.execute(
        select(StockEvent.product_id, StockEvent.store_id, StockEvent.unit_price, StockEvent.at, Product.name, Store.name)
        .join(Product, Product.id == StockEvent.product_id)
        .join(Store, Store.id == StockEvent.store_id)
        .where(StockEvent.household_id == household_id, StockEvent.kind == "purchase",
               StockEvent.unit_price.is_not(None))
        .order_by(StockEvent.at)
    ).all()
    last: dict[tuple[str, str], Decimal] = {}
    seen: set[tuple[str, str]] = set()
    out = []
    for pid, sid, price, at, name, store in rows:
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
        key = (pid, sid)
        before = last.get(key)
        if at >= since and before and key not in seen and price - before >= max(RISE_MIN, before * RISE_PCT):
            out.append({"product": name, "store": store, "before": before, "now": price,
                        "pct": round(float((price - before) / before) * 100)})
            seen.add(key)
        last[key] = price
    return sorted(out, key=lambda x: -x["pct"])
