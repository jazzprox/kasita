from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Location, Product, StockEntry, StockEvent, Store
from ..schemas import ConsumeIn, OpenIn, PurchaseIn, StockEntryOut, StockEventOut, StockProductOut
from ..services import stock as svc
from .products import product_out

router = APIRouter(prefix="/api/households/{household_id}/stock", tags=["stock"])


def _check_ref(db: Session, model, ref_id: str | None, household_id: str, label: str) -> None:
    if ref_id:
        row = db.get(model, ref_id)
        if not row or row.household_id != household_id:
            raise HTTPException(404, f"{label} not found")


@router.get("", response_model=list[StockProductOut])
def overview(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Everything at home, grouped per product, soonest-expiring batches first."""
    entries = db.scalars(select(StockEntry).where(StockEntry.household_id == a.household.id, StockEntry.quantity > 0)).all()
    by_product: dict[str, list[StockEntry]] = {}
    for e in entries:
        by_product.setdefault(e.product_id, []).append(e)
    out = []
    for pid, es in by_product.items():
        p = db.get(Product, pid)
        es.sort(key=lambda e: (e.best_before or date.max, e.purchased_at))
        out.append(StockProductOut(product=product_out(db, p), total=sum(e.quantity for e in es),
                                   entries=[StockEntryOut.model_validate(e) for e in es]))
    out.sort(key=lambda s: (s.product.next_best_before or date.max, s.product.name.lower()))
    return out


@router.get("/expiring", response_model=list[StockProductOut])
def expiring(days: int = 5, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    limit = date.today() + timedelta(days=days)
    return [s for s in overview(a, db) if s.product.next_best_before and s.product.next_best_before <= limit]


@router.post("/purchase", response_model=StockEntryOut, status_code=201)
def purchase(body: PurchaseIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    p = svc.get_product(db, a.household.id, body.product_id)
    _check_ref(db, Location, body.location_id, a.household.id, "Location")
    _check_ref(db, Store, body.store_id, a.household.id, "Store")
    e = svc.purchase(db, a.household.id, a.user.id, p, body.quantity, best_before=body.best_before,
                     location_id=body.location_id, unit_price=body.unit_price, store_id=body.store_id,
                     purchased_at=body.purchased_at)
    db.commit()
    return e


@router.post("/consume")
def consume(body: ConsumeIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    p = svc.get_product(db, a.household.id, body.product_id)
    taken = svc.consume(db, a.household.id, a.user.id, p, body.quantity, spoiled=body.spoiled)
    db.commit()
    return {"consumed": taken, "remaining": svc.in_stock(db, p.id), "short_by": body.quantity - taken}


@router.post("/open", response_model=StockEntryOut)
def open_pack(body: OpenIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    p = svc.get_product(db, a.household.id, body.product_id)
    e = svc.open_one(db, a.household.id, a.user.id, p)
    if not e:
        raise HTTPException(409, "Nothing unopened in stock")
    db.commit()
    return e


@router.get("/events", response_model=list[StockEventOut])
def events(limit: int = 100, product_id: str | None = None, a: HouseholdAccess = Depends(household_access),
           db: Session = Depends(get_db)):
    stmt = select(StockEvent).where(StockEvent.household_id == a.household.id)
    if product_id:
        stmt = stmt.where(StockEvent.product_id == product_id)
    return db.scalars(stmt.order_by(StockEvent.at.desc()).limit(min(limit, 500))).all()
