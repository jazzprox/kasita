from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Product, ShoppingItem, Store
from ..schemas import ShoppingIn, ShoppingOut, ShoppingPatch
from ..services import route
from ..services.stock import get_product, refill_if_low

router = APIRouter(prefix="/api/households/{household_id}/shopping", tags=["shopping"])


def _item(db: Session, household_id: str, item_id: str) -> ShoppingItem:
    item = db.get(ShoppingItem, item_id)
    if not item or item.household_id != household_id:
        raise HTTPException(404, "Item not found")
    return item


@router.get("", response_model=list[ShoppingOut])
def list_items(include_done: bool = False, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    stmt = select(ShoppingItem).where(ShoppingItem.household_id == a.household.id)
    if not include_done:
        stmt = stmt.where(ShoppingItem.done.is_(False))
    return db.scalars(stmt.order_by(ShoppingItem.done, ShoppingItem.created_at)).all()


@router.post("", response_model=ShoppingOut, status_code=201)
def add_item(body: ShoppingIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    name = (body.name or "").strip()
    if body.product_id:
        name = name or get_product(db, a.household.id, body.product_id).name
    if not name:
        raise HTTPException(422, "Give a name or a product")
    item = ShoppingItem(household_id=a.household.id, product_id=body.product_id, name=name, quantity=body.quantity,
                        note=body.note, added_by=a.user.id)
    db.add(item)
    db.commit()
    return item


@router.patch("/{item_id}", response_model=ShoppingOut)
def update_item(item_id: str, body: ShoppingPatch, a: HouseholdAccess = Depends(household_access),
                db: Session = Depends(get_db)):
    item = _item(db, a.household.id, item_id)
    data = body.model_dump(exclude_unset=True)
    at, day, store_id = data.pop("ticked_at", None), data.pop("local_day", None), data.pop("store_id", None)
    if store_id:
        store = db.get(Store, store_id)
        if not store or store.household_id != a.household.id:
            raise HTTPException(404, "Store not found")
    if "done" in data and data["done"] != item.done:
        if data["done"]:
            tick = route.record(db, item, at=at, day=day, store_id=store_id)
            item.done_at = tick.ticked_at
        else:
            route.forget(db, item)
            item.done_at = None
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    return item


@router.get("/route")
def walk_order(store_id: str | None = None, a: HouseholdAccess = Depends(household_access),
               db: Session = Depends(get_db)):
    """The open list's place in your walk through a store (learned from the order you tick things there).
    {"store_id", "store", "trips", "rank": {item_id: 0..1 | null}, "stores": [walked stores]}"""
    return route.route(db, a.household.id, store_id)


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    db.delete(_item(db, a.household.id, item_id))
    db.commit()


@router.post("/clear-done", status_code=204)
def clear_done(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    db.execute(delete(ShoppingItem).where(ShoppingItem.household_id == a.household.id, ShoppingItem.done.is_(True)))
    db.commit()


@router.post("/refill", response_model=list[ShoppingOut])
def refill(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Add everything below its minimum stock or forecast to run out within days (skips items already on the list)."""
    added = []
    for p in db.scalars(select(Product).where(Product.household_id == a.household.id, Product.archived.is_(False))):
        item = refill_if_low(db, a.household.id, p)
        if item is not None:
            added.append(item)
    db.commit()
    return added



@router.get("/prices")
def prices(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Each open item: the latest price per store (last 120 days), the cheapest store, the store it is
    usually bought at, and a hint when another store was cheaper ("1.20 cheaper at Mangusa...")."""
    from ..services.prices import shopping_prices
    return shopping_prices(db, a.household.id)


@router.get("/by-store")
def by_store(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """The open list split by the store where each item was cheapest lately (receipt prices, last 120 days)."""
    from ..services.prices import cheapest_split
    return cheapest_split(db, a.household.id)


@router.get("/market")
def market_hints(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Open items that a shop with online prices lists: {item_id: {store, price, on_sale, previous_price...}}."""
    from ..services import market
    return market.shopping_market(db, a.household.id)
