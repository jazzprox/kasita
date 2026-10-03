"""Your walk through a store, learned from the order you tick the shopping list there.

Every tick is kept (`ShoppingTick`) with the day it happened. A day's ticks at one
store are one trip; within a trip the first tick is position 0 and the last is 1.
Averaged over recent trips, each product (or free-text name, or category) gets a
place in that store's walk, and the open list can be sorted by it.

Which store? The app says so when you pick "I'm at ..." on the list. Otherwise the
day's receipt tells it later: ticks of things on that receipt are booked to its
store, and when it is the only receipt that day, the rest of the day's ticks too.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Receipt, ReceiptLine, ShoppingItem, ShoppingTick, Store

MAX_TRIPS = 20       # the most recent walks count; stores get rearranged
MIN_TICKS = 2        # one tick says nothing about order
BACKDATE_DAYS = 3    # an offline tick sent late may keep its own time, up to this old


def local_day(at: datetime) -> date:
    return (at + timedelta(hours=settings.local_utc_offset_hours)).date()


def _key(name: str) -> str:
    return " ".join(name.lower().split())[:255]


def record(db: Session, item: ShoppingItem, *, at: datetime | None = None, day: date | None = None,
           store_id: str | None = None) -> ShoppingTick:
    """Remember that `item` was ticked (at `at`, on the phone's calendar `day`, in `store_id`)."""
    now = datetime.now(timezone.utc)
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if at is None or not (now - timedelta(days=BACKDATE_DAYS) <= at <= now + timedelta(minutes=5)):
        at = now
    if day is None or abs((day - local_day(at)).days) > 1:
        day = local_day(at)
    tick = ShoppingTick(household_id=item.household_id, item_id=item.id, product_id=item.product_id,
                        name_key=_key(item.name), category=item.category, ticked_at=at, local_day=day,
                        store_id=store_id, store_source="app" if store_id else None)
    db.add(tick)
    return tick


def forget(db: Session, item: ShoppingItem) -> None:
    """Unticked again: that tick was a slip, not a step in the walk."""
    since = datetime.now(timezone.utc) - timedelta(days=BACKDATE_DAYS)
    db.execute(delete(ShoppingTick).where(ShoppingTick.household_id == item.household_id,
                                          ShoppingTick.item_id == item.id, ShoppingTick.ticked_at >= since))


def assign_from_receipt(db: Session, receipt: Receipt) -> int:
    """Book the receipt day's store-less ticks to the receipt's store. Returns how many."""
    if not receipt.store_id:
        return 0
    day = receipt.purchased_on or local_day(receipt.created_at)
    ticks = list(db.scalars(select(ShoppingTick).where(ShoppingTick.household_id == receipt.household_id,
                                                       ShoppingTick.local_day == day,
                                                       ShoppingTick.store_id.is_(None))))
    if not ticks:
        return 0
    on_receipt = set(db.scalars(select(ReceiptLine.product_id).where(ReceiptLine.receipt_id == receipt.id,
                                                                     ReceiptLine.product_id.is_not(None))))
    others = db.scalar(select(func.count()).select_from(Receipt).where(
        Receipt.household_id == receipt.household_id, Receipt.id != receipt.id,
        Receipt.purchased_on == day, Receipt.store_id.is_not(None), Receipt.store_id != receipt.store_id,
        Receipt.status == "confirmed"))
    n = 0
    for t in ticks:
        # one shop that day: all of it was there. Several: only what this receipt shows.
        if t.product_id in on_receipt or not others:
            t.store_id, t.store_source = receipt.store_id, "receipt"
            n += 1
    return n


def _trips(db: Session, household_id: str, store_id: str) -> list[list[ShoppingTick]]:
    days = list(db.scalars(
        select(ShoppingTick.local_day).where(ShoppingTick.household_id == household_id,
                                             ShoppingTick.store_id == store_id)
        .group_by(ShoppingTick.local_day).having(func.count() >= MIN_TICKS)
        .order_by(ShoppingTick.local_day.desc()).limit(MAX_TRIPS)))
    if not days:
        return []
    rows = db.scalars(select(ShoppingTick).where(ShoppingTick.household_id == household_id,
                                                 ShoppingTick.store_id == store_id,
                                                 ShoppingTick.local_day.in_(days))
                      .order_by(ShoppingTick.ticked_at))
    by_day: dict[date, list[ShoppingTick]] = {}
    for t in rows:
        by_day.setdefault(t.local_day, []).append(t)
    return list(by_day.values())


def positions(db: Session, household_id: str, store_id: str) -> dict:
    """{"trips": n, "product": {id: pos}, "name": {key: pos}, "category": {name: pos}}, pos 0..1."""
    sums: dict[str, dict[str, list[float]]] = {"product": {}, "name": {}, "category": {}}
    trips = _trips(db, household_id, store_id)
    for trip in trips:
        last = len(trip) - 1
        for i, t in enumerate(trip):
            pos = i / last
            for kind, key in (("product", t.product_id), ("name", t.name_key), ("category", t.category)):
                if key:
                    sums[kind].setdefault(key, []).append(pos)
    out: dict = {"trips": len(trips)}
    for kind, d in sums.items():
        out[kind] = {k: sum(v) / len(v) for k, v in d.items()}
    return out


def rank(item: ShoppingItem, pos: dict) -> float | None:
    """Where in the walk this item comes: its product, else its name, else its category; None = unknown."""
    if item.product_id and item.product_id in pos["product"]:
        return pos["product"][item.product_id]
    if _key(item.name) in pos["name"]:
        return pos["name"][_key(item.name)]
    if item.category and item.category in pos["category"]:
        return pos["category"][item.category]
    return None


def stores_walked(db: Session, household_id: str) -> list[dict]:
    """Stores with at least one learned walk, most recent first."""
    rows = db.execute(
        select(ShoppingTick.store_id, Store.name, func.count(func.distinct(ShoppingTick.local_day)),
               func.max(ShoppingTick.local_day))
        .join(Store, Store.id == ShoppingTick.store_id)
        .where(ShoppingTick.household_id == household_id)
        .group_by(ShoppingTick.store_id, Store.name)).all()
    return [{"id": sid, "name": name, "trips": n, "last": last.isoformat()}
            for sid, name, n, last in sorted(rows, key=lambda r: r[3], reverse=True)]


def route(db: Session, household_id: str, store_id: str | None) -> dict:
    """The open list in walk order for a store (the most recently walked one when none is given)."""
    walked = stores_walked(db, household_id)
    if store_id is None and walked:
        store_id = walked[0]["id"]
    store = db.get(Store, store_id) if store_id else None
    if store is None or store.household_id != household_id:
        return {"store_id": None, "store": None, "trips": 0, "rank": {}, "stores": walked}
    pos = positions(db, household_id, store.id)
    items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == household_id,
                                                  ShoppingItem.done.is_(False)))
    return {"store_id": store.id, "store": store.name, "trips": pos["trips"],
            "rank": {i.id: rank(i, pos) for i in items}, "stores": walked}
