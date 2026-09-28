from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Location, Product, StockEntry, StockEvent, Store
from ..schemas import ConsumeIn, EntryPatch, OpenIn, PurchaseIn, StockEntryOut, StockEventOut, StockProductOut, UndoIn
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
    ev = db.scalar(select(StockEvent).where(StockEvent.entry_id == e.id, StockEvent.kind == "purchase"))
    return StockEntryOut.model_validate(e).model_copy(update={"event_id": ev.id if ev else None})


@router.post("/consume")
def consume(body: ConsumeIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    p = svc.get_product(db, a.household.id, body.product_id)
    written: list = []
    taken = svc.consume(db, a.household.id, a.user.id, p, body.quantity, spoiled=body.spoiled, events=written)
    db.commit()
    return {"consumed": taken, "remaining": svc.in_stock(db, p.id), "short_by": body.quantity - taken,
            "event_ids": [ev.id for ev in written]}


@router.post("/undo")
def undo(body: UndoIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Reverse recent adds/uses (the pantry pass's minus button), all or nothing."""
    for event_id in body.event_ids:
        ev = db.get(StockEvent, event_id)
        if not ev or ev.household_id != a.household.id:
            raise HTTPException(404, "Stock event not found")
        svc.undo(db, a.household.id, ev)
    db.commit()
    return {"undone": len(body.event_ids)}


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



@router.get("/spending")
def spending(days: int = 30, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """What priced purchases (receipts, or prices typed when buying) cost, per category and store."""
    from ..services.digest import spending as calc
    return calc(db, a.household.id, days=max(1, min(days, 366)))



@router.patch("/entries/{entry_id}", response_model=StockEntryOut)
def patch_entry(entry_id: str, body: EntryPatch, a: HouseholdAccess = Depends(household_access),
                db: Session = Depends(get_db)):
    """Set a batch's best-before date, or move it (into a freezer: the frozen date starts today)."""
    e = db.get(StockEntry, entry_id)
    if not e or e.household_id != a.household.id:
        raise HTTPException(404, "Batch not found")
    fields = body.model_dump(exclude_unset=True)
    if "best_before" in fields:
        e.best_before = fields["best_before"]
    if "location_id" in fields and fields["location_id"] != e.location_id:
        _check_ref(db, Location, fields["location_id"], a.household.id, "Location")
        to = db.get(Location, fields["location_id"]) if fields["location_id"] else None
        e.location_id = fields["location_id"]
        e.frozen_at = (e.frozen_at or date.today()) if to is not None and to.is_freezer else None
    db.commit()
    return e


@router.post("/read-date")
async def read_date(file: UploadFile = File(...), a: HouseholdAccess = Depends(household_access),
                    db: Session = Depends(get_db)):
    """Photo of the date printed on a pack -> {"date": "YYYY-MM-DD" | null} (household's ChatGPT)."""
    from ..services import codex, identify
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Photo is larger than 20 MB")
    try:
        return identify.read_date(db, a.household.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except codex.CodexError as e:
        raise HTTPException(502, str(e)) from e
