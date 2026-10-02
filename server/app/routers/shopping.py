from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Product, ShoppingItem
from ..schemas import ShoppingIn, ShoppingOut, ShoppingPatch
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
    if "done" in data:
        item.done_at = datetime.now(timezone.utc) if data["done"] else None
    for k, v in data.items():
        setattr(item, k, v)
    db.commit()
    return item


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
