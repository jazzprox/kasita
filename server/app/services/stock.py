"""Stock rules, kept out of the HTTP layer so receipts and the API share them."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Location, Product, ShoppingItem, StockEntry, StockEvent


def get_product(db: Session, household_id: str, product_id: str) -> Product:
    p = db.get(Product, product_id)
    if not p or p.household_id != household_id:
        raise HTTPException(404, "Product not found")
    return p


def in_stock(db: Session, product_id: str) -> Decimal:
    total = db.scalar(select(func.coalesce(func.sum(StockEntry.quantity), 0)).where(
        StockEntry.product_id == product_id, StockEntry.quantity > 0))
    return Decimal(total or 0)


def purchase(db: Session, household_id: str, user_id: str | None, product: Product, quantity: Decimal, *,
             best_before: date | None = None, location_id: str | None = None, unit_price: Decimal | None = None,
             store_id: str | None = None, purchased_at: date | None = None,
             receipt_line_id: str | None = None) -> StockEntry:
    bought = purchased_at or date.today()
    if best_before is None and product.shelf_life_days:
        best_before = bought + timedelta(days=product.shelf_life_days)
    entry = StockEntry(household_id=household_id, product_id=product.id, quantity=quantity, best_before=best_before,
                       location_id=location_id or product.default_location_id, unit_price=unit_price,
                       store_id=store_id, purchased_at=bought, receipt_line_id=receipt_line_id)
    loc = db.get(Location, entry.location_id) if entry.location_id else None
    if loc is not None and loc.is_freezer:
        entry.frozen_at = bought
    db.add(entry)
    db.flush()
    db.add(StockEvent(household_id=household_id, product_id=product.id, entry_id=entry.id, kind="purchase",
                      quantity=quantity, unit_price=unit_price, store_id=store_id, user_id=user_id))
    # bought it: tick matching automatic shopping-list items
    for item in db.scalars(select(ShoppingItem).where(ShoppingItem.product_id == product.id, ShoppingItem.done.is_(False))):
        item.done = True
        item.done_at = datetime.now(timezone.utc)
    return entry


def _consume_order(entries: list[StockEntry]) -> list[StockEntry]:
    # use opened packs first, then whatever expires soonest, then the oldest purchase
    return sorted(entries, key=lambda e: (e.opened_at is None, e.best_before or date.max, e.purchased_at))


def consume(db: Session, household_id: str, user_id: str | None, product: Product, quantity: Decimal,
            spoiled: bool = False, events: list | None = None) -> Decimal:
    """Take `quantity` out of stock. Returns how much was actually available.
    Pass a list as `events` to get the StockEvents written (for undo)."""
    entries = _consume_order(list(db.scalars(select(StockEntry).where(
        StockEntry.product_id == product.id, StockEntry.quantity > 0))))
    remaining = quantity
    for e in entries:
        if remaining <= 0:
            break
        take = min(e.quantity, remaining)
        e.quantity -= take
        remaining -= take
        ev = StockEvent(household_id=household_id, product_id=product.id, entry_id=e.id,
                        kind="spoil" if spoiled else "consume", quantity=take, user_id=user_id)
        db.add(ev)
        if events is not None:
            events.append(ev)
    taken = quantity - remaining
    db.flush()
    refill_if_low(db, household_id, product)
    return taken


def open_one(db: Session, household_id: str, user_id: str | None, product: Product) -> StockEntry | None:
    entries = [e for e in _consume_order(list(db.scalars(select(StockEntry).where(
        StockEntry.product_id == product.id, StockEntry.quantity > 0)))) if e.opened_at is None]
    if not entries:
        return None
    e = entries[0]
    e.opened_at = date.today()
    if product.open_days:
        # once open it keeps open_days: that becomes its date if sooner than the printed one
        by = e.opened_at + timedelta(days=product.open_days)
        e.best_before = min(e.best_before, by) if e.best_before else by
    db.add(StockEvent(household_id=household_id, product_id=product.id, entry_id=e.id, kind="open",
                      quantity=Decimal(0), user_id=user_id))
    return e


def forecast(db: Session, product: Product, now: datetime | None = None) -> tuple[float, float] | None:
    """(units used per day, days until it runs out) from the last 120 days of use, or None
    when there is too little history to say (fewer than 2 uses, or under 14 days of data)."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=120)
    uses = db.execute(select(StockEvent.quantity, StockEvent.at).where(
        StockEvent.product_id == product.id, StockEvent.kind.in_(("consume", "spoil")), StockEvent.at >= since)).all()
    if len(uses) < 2:
        return None
    first = db.scalar(select(func.min(StockEvent.at)).where(StockEvent.product_id == product.id,
                                                             StockEvent.at >= since))
    first = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
    span = (now - first).total_seconds() / 86400
    if span < 14:
        return None
    rate = float(sum(q for q, _ in uses)) / span
    if rate <= 0:
        return None
    return rate, float(in_stock(db, product.id)) / rate


RUN_OUT_DAYS = 4  # put it on the list when the forecast says it runs out within this many days


def refill_if_low(db: Session, household_id: str, product: Product) -> ShoppingItem | None:
    """Put a product on the shopping list when stock drops below its minimum, or when its usage
    says it will run out within RUN_OUT_DAYS (once; an open item is not duplicated)."""
    if product.archived:
        return None
    have = in_stock(db, product.id)
    low = bool(product.min_stock) and have < product.min_stock
    fc = None if low else forecast(db, product)
    if not low and not (fc and fc[1] <= RUN_OUT_DAYS):
        return None
    open_item = db.scalar(select(ShoppingItem).where(ShoppingItem.product_id == product.id, ShoppingItem.done.is_(False)))
    if open_item:
        return open_item
    qty = max(product.min_stock - have, Decimal(1)) if low else Decimal(1)
    item = ShoppingItem(household_id=household_id, product_id=product.id, name=product.name, quantity=qty,
                        auto=True, note=None if low else "running out soon")
    db.add(item)
    return item


def undo(db: Session, household_id: str, event: StockEvent) -> None:
    """Reverse one stock event and delete it: a purchase removes the batch it created
    (only while nothing has been taken from it); a consume/spoil puts the quantity back."""
    entry = db.get(StockEntry, event.entry_id) if event.entry_id else None
    if event.kind == "purchase":
        if entry is not None:
            others = db.scalar(select(func.count()).select_from(StockEvent).where(
                StockEvent.entry_id == entry.id, StockEvent.id != event.id))
            if others or entry.quantity != event.quantity:
                raise HTTPException(409, "Some of that has been used since; use 'Used one' instead")
            db.delete(entry)
    elif event.kind in ("consume", "spoil"):
        if entry is None:
            raise HTTPException(409, "That batch no longer exists")
        entry.quantity += event.quantity
    else:
        raise HTTPException(409, f"A '{event.kind}' cannot be undone here")
    db.delete(event)
