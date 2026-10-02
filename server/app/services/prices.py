"""Prices from purchases (receipts, or typed when buying): where is it cheapest, what went up."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, ShoppingItem, StockEntry, StockEvent, Store

RISE_PCT = Decimal("0.10")      # a rise worth mentioning: at least 10%...
RISE_MIN = Decimal("0.25")      # ...and at least this much money


FRESH_DAYS = 120   # a price older than this says little about today's
USUAL_DAYS = 365   # "where you usually buy it": most purchases over this long


def _day(entry_day: date | None, at: datetime) -> date:
    return entry_day or at.date()


def store_prices(db: Session, household_id: str, product_ids: list[str] | None = None,
                 fresh_days: int = FRESH_DAYS) -> dict[str, dict]:
    """Per product: the latest fresh price at each store and the store it is usually bought at.

    product_id -> {"prices": {store_id: {"store_id", "store", "price", "on"}},
                   "usual": store_id | None}
    Purchase day is the receipt's date (the batch's purchased_at), not when it was booked."""
    today = date.today()
    fresh_since, usual_since = today - timedelta(days=fresh_days), today - timedelta(days=USUAL_DAYS)
    stmt = (select(StockEvent.product_id, StockEvent.store_id, Store.name, StockEvent.unit_price, StockEvent.at,
                   StockEntry.purchased_at)
            .join(Store, Store.id == StockEvent.store_id)
            .outerjoin(StockEntry, StockEntry.id == StockEvent.entry_id)
            .where(StockEvent.household_id == household_id, StockEvent.kind == "purchase",
                   StockEvent.at >= datetime.combine(usual_since, time.min, tzinfo=timezone.utc)
                   - timedelta(days=30)))
    if product_ids is not None:
        stmt = stmt.where(StockEvent.product_id.in_(product_ids))
    rows = sorted(db.execute(stmt).all(), key=lambda r: (_day(r[5], r[4]), r[4]))  # oldest first: latest wins
    out: dict[str, dict] = {}
    counts: dict[str, dict[str, list]] = {}
    for pid, sid, store, price, at, bought in rows:
        day = _day(bought, at)
        if day < usual_since:
            continue
        c = counts.setdefault(pid, {}).setdefault(sid, [0, day])
        c[0], c[1] = c[0] + 1, day
        p = out.setdefault(pid, {"prices": {}, "usual": None})
        if price is not None and day >= fresh_since:
            p["prices"][sid] = {"store_id": sid, "store": store, "price": price, "on": day}
    for pid, by_store in counts.items():
        # the most purchases; a tie goes to the most recent
        out[pid]["usual"] = max(by_store.items(), key=lambda kv: (kv[1][0], kv[1][1]))[0]
    return out


def compare(info: dict | None) -> dict:
    """Cheapest fresh price vs the usual store, and a hint when another store was cheaper.

    Same product only: Kasita has no pack sizes, so prices are per the product's own unit."""
    out = {"cheapest_store_id": None, "cheapest_store": None, "cheapest_price": None, "usual_store_id": None,
           "usual_store": None, "usual_price": None, "saving": None, "hint": None, "prices": []}
    if not info:
        return out
    prices = info["prices"]
    usual = info["usual"]
    out["prices"] = sorted(prices.values(), key=lambda p: (p["price"], p["store"]))
    if usual in prices:
        out["usual_store_id"], out["usual_store"], out["usual_price"] = \
            usual, prices[usual]["store"], prices[usual]["price"]
    if not prices:
        return out
    # cheapest; on a tie the usual store, then the most recent price
    best = min(prices.values(), key=lambda p: (p["price"], p["store_id"] != usual, -p["on"].toordinal()))
    out["cheapest_store_id"], out["cheapest_store"], out["cheapest_price"] = \
        best["store_id"], best["store"], best["price"]
    up = out["usual_price"]
    if up is not None and best["store_id"] != usual and best["price"] < up:
        out["saving"] = up - best["price"]
        out["hint"] = (f"{out['saving']:.2f} cheaper at {best['store']} "
                       f"(last {best['price']:.2f} vs {up:.2f})")
    return out


def _open_items(db: Session, household_id: str) -> list[ShoppingItem]:
    return list(db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == household_id,
                                                      ShoppingItem.done.is_(False))
                           .order_by(ShoppingItem.created_at)))


def shopping_prices(db: Session, household_id: str) -> list[dict]:
    """Every open shopping item with where it was cheapest lately and where it is usually bought."""
    items = _open_items(db, household_id)
    info = store_prices(db, household_id, [i.product_id for i in items if i.product_id])
    return [{"id": it.id, "name": it.name, "product_id": it.product_id, "quantity": it.quantity,
             **compare(info.get(it.product_id) if it.product_id else None)} for it in items]


def cheapest_split(db: Session, household_id: str) -> list[dict]:
    """Open shopping items grouped by the store where each was cheapest lately (fresh prices only)."""
    groups: dict[str, dict] = {}
    for it in shopping_prices(db, household_id):
        price = it["cheapest_price"]
        store = it["cheapest_store"] or "Anywhere (no prices yet)"
        others = {p["store"]: float(p["price"]) for p in it["prices"] if p["store_id"] != it["cheapest_store_id"]}
        g = groups.setdefault(store, {"store": store, "store_id": it["cheapest_store_id"], "items": [],
                                      "total": Decimal(0), "priced": 0})
        g["items"].append({"id": it["id"], "name": it["name"], "quantity": it["quantity"], "price": price,
                           "elsewhere": others, "hint": it["hint"]})
        if price is not None:
            g["total"] += price * it["quantity"]
            g["priced"] += 1
    # stores with the most items first; "Anywhere" last
    return sorted(groups.values(), key=lambda g: (g["store_id"] is None, -len(g["items"])))


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
