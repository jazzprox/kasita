from datetime import date as Date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Bill
from ..schemas import (BillOut, BillPatch, BillsBooked, BillsIn, BillsLinkIn, BillsRecordIn, SecuroAccount,
                       SecuroCandidate)
from ..services import bills as svc
from ..services import securo
from ..services.receipts import store_images

router = APIRouter(prefix="/api/households/{household_id}/bills", tags=["bills"])

MAX_UPLOAD = 20 * 1024 * 1024
MAX_PAGES = 4


def _get(db: Session, a: HouseholdAccess, bill_id: str) -> Bill:
    b = db.get(Bill, bill_id)
    if not b or b.household_id != a.household.id:
        raise HTTPException(404, "Bill not found")
    return b


def _many(db: Session, a: HouseholdAccess, ids: list[str]) -> list[Bill]:
    bills = [_get(db, a, i) for i in dict.fromkeys(ids)]
    booked = [b for b in bills if b.securo_transaction_id]
    if booked:
        raise HTTPException(409, f"{booked[0].biller or 'A bill'} is already booked in Securo")
    return bills


def bill_out(b: Bill) -> BillOut:
    return BillOut(id=b.id, status=b.status, error=b.error, biller=b.biller, lines=b.lines or [], total=b.total,
                   currency=b.currency, period=b.period, bill_date=b.bill_date, due_date=b.due_date,
                   account_ref=b.account_ref, securo_transaction_id=b.securo_transaction_id, created_at=b.created_at)


def _securo_error(e: securo.SecuroError) -> HTTPException:
    return HTTPException(502, str(e))


@router.get("", response_model=list[BillOut])
def list_bills(limit: int = 100, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    rows = db.scalars(select(Bill).where(Bill.household_id == a.household.id)
                      .order_by(Bill.created_at.desc()).limit(min(limit, 300))).all()
    return [bill_out(b) for b in rows]


@router.post("", response_model=BillOut, status_code=201)
async def upload(background: BackgroundTasks, file: list[UploadFile] = File(...),
                 a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """One bill: a photo, or its pages as several `file` parts in order. Read in the background:
    poll GET until status is read or failed."""
    if len(file) > MAX_PAGES:
        raise HTTPException(413, f"At most {MAX_PAGES} pages per bill")
    parts = []
    for f in file:
        data = await f.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "A photo is larger than 20 MB")
        parts.append(data)
    try:
        path = store_images(a.household.id, parts, folder=svc.bills_dir(a.household.id))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    b = Bill(household_id=a.household.id, image_path=path, status="reading", uploaded_by=a.user.id,
             currency=a.household.currency, lines=[])
    db.add(b)
    db.commit()
    background.add_task(svc.parse, b.id)
    return bill_out(b)


@router.get("/securo-accounts", response_model=list[SecuroAccount])
def securo_accounts(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    try:
        return [SecuroAccount(id=x["id"], name=x.get("name") or "?", type=x.get("type"), currency=x.get("currency"))
                for x in securo.accounts(securo.conn_for(db, a.household.id))]
    except securo.SecuroError as e:
        raise _securo_error(e) from e


@router.post("/payment-candidates", response_model=list[SecuroCandidate])
def payment_candidates(body: BillsIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Securo payments that match the sum of these bills (paid together)."""
    bills = _many(db, a, body.bill_ids)
    try:
        conn = securo.conn_for(db, a.household.id)
        return svc.candidates(bills, securo.transactions(conn, *svc.search_window(bills)))
    except securo.SecuroError as e:
        raise _securo_error(e) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


def _booked(db: Session, bills: list[Bill], transaction_id: str, skipped: list[str]) -> BillsBooked:
    for b in bills:
        b.securo_transaction_id, b.status = transaction_id, "linked"
    db.commit()
    return BillsBooked(transaction_id=transaction_id, note=svc.note(bills), skipped=skipped,
                       bills=[bill_out(b) for b in bills])


@router.post("/link", response_model=BillsBooked)
def link(body: BillsLinkIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Book the bills on an existing Securo payment: photos, Utilities, breakdown note."""
    bills = _many(db, a, body.bill_ids)
    try:
        svc.total_of(bills)
        conn = securo.conn_for(db, a.household.id)
        skipped = svc.link(conn, bills, body.transaction_id, attach_photos=body.attach_photos,
                           set_category=body.set_category, add_note=body.add_note)
    except securo.SecuroError as e:
        raise _securo_error(e) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _booked(db, bills, body.transaction_id, skipped)


@router.post("/record", response_model=BillsBooked, status_code=201)
def record(body: BillsRecordIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """No payment in Securo (cash, or it never came in): create it, then book the bills on it."""
    bills = _many(db, a, body.bill_ids)
    if body.date > Date.today():
        raise HTTPException(422, "The payment date is in the future")
    try:
        conn = securo.conn_for(db, a.household.id)
        tid = svc.record(conn, bills, body.account_id, body.date, body.description)
        skipped = svc.link(conn, bills, tid, set_category=False)
    except securo.SecuroError as e:
        raise _securo_error(e) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return _booked(db, bills, tid, skipped)


@router.get("/{bill_id}", response_model=BillOut)
def get_bill(bill_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return bill_out(_get(db, a, bill_id))


@router.get("/{bill_id}/image")
def image(bill_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    b = _get(db, a, bill_id)
    if not b.image_path or not Path(b.image_path).is_file():
        raise HTTPException(404, "No photo")
    return FileResponse(b.image_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.patch("/{bill_id}", response_model=BillOut)
def patch(bill_id: str, body: BillPatch, a: HouseholdAccess = Depends(household_access),
          db: Session = Depends(get_db)):
    b = _get(db, a, bill_id)
    data = body.model_dump(exclude_unset=True)
    if "lines" in data:
        data["lines"] = [{"service": ln["service"].strip().lower(), "amount": f"{ln['amount']:.2f}"}
                         for ln in data["lines"] or []]
    if data.get("currency"):
        data["currency"] = data["currency"].upper()
    for k, v in data.items():
        setattr(b, k, v)
    if b.status in ("reading", "failed") and b.total is not None:
        b.status, b.error = "read", None  # typed in by hand
    db.commit()
    return bill_out(b)


@router.post("/{bill_id}/parse", response_model=BillOut)
def reparse(bill_id: str, background: BackgroundTasks, a: HouseholdAccess = Depends(household_access),
            db: Session = Depends(get_db)):
    b = _get(db, a, bill_id)
    if b.securo_transaction_id:
        raise HTTPException(409, "This bill is already booked in Securo")
    b.status, b.error = "reading", None
    db.commit()
    background.add_task(svc.parse, b.id)
    return bill_out(b)


@router.delete("/{bill_id}/securo-link", response_model=BillOut)
def unlink(bill_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Forget the link in Kasita (Securo keeps the photo and note; remove those there if needed)."""
    b = _get(db, a, bill_id)
    b.securo_transaction_id, b.status = None, "read"
    db.commit()
    return bill_out(b)


@router.delete("/{bill_id}", status_code=204)
def delete(bill_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    b = _get(db, a, bill_id)
    if b.image_path:
        Path(b.image_path).unlink(missing_ok=True)
    db.delete(b)
    db.commit()
