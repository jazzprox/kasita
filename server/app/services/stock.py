"""Stock rules, kept out of the HTTP layer so receipts and the API share them."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, ShoppingItem, StockEntry, StockEvent


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
            spoiled: bool = False) -> Decimal:
    """Take `quantity` out of stock. Returns how much was actually available."""
    entries = _consume_order(list(db.scalars(select(StockEntry).where(
        StockEntry.product_id == product.id, StockEntry.quantity > 0))))
    remaining = quantity
    for e in entries:
        if remaining <= 0:
            break
        take = min(e.quantity, remaining)
        e.quantity -= take
        remaining -= take
        db.add(StockEvent(household_id=household_id, product_id=product.id, entry_id=e.id,
                          kind="spoil" if spoiled else "consume", quantity=take, user_id=user_id))
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
    db.add(StockEvent(household_id=household_id, product_id=product.id, entry_id=e.id, kind="open",
                      quantity=Decimal(0), user_id=user_id))
    return e


def refill_if_low(db: Session, household_id: str, product: Product) -> ShoppingItem | None:
    """Put a product on the shopping list when stock drops below its minimum (once)."""
    if not product.min_stock or product.archived:
        return None
    have = in_stock(db, product.id)
    if have >= product.min_stock:
        return None
    open_item = db.scalar(select(ShoppingItem).where(ShoppingItem.product_id == product.id, ShoppingItem.done.is_(False)))
    if open_item:
        return open_item
    item = ShoppingItem(household_id=household_id, product_id=product.id, name=product.name,
                        quantity=max(product.min_stock - have, Decimal(1)), auto=True)
    db.add(item)
    return item
