from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Location, Product, Receipt, ReceiptLine, Store
from ..schemas import (ConfirmIn, ConfirmOut, ReceiptLineIn, ReceiptLineOut, ReceiptLinePatch, ReceiptOut,
                       ReceiptPatch, SecuroCandidate, SecuroLinkIn)
from ..services import receipts as svc
from ..services import securo
from .stock import _check_ref

router = APIRouter(prefix="/api/households/{household_id}/receipts", tags=["receipts"])

MAX_UPLOAD = 20 * 1024 * 1024


def _get(db: Session, a: HouseholdAccess, receipt_id: str) -> Receipt:
    r = db.get(Receipt, receipt_id)
    if not r or r.household_id != a.household.id:
        raise HTTPException(404, "Receipt not found")
    return r


def _line(db: Session, r: Receipt, line_id: str) -> ReceiptLine:
    line = db.get(ReceiptLine, line_id)
    if not line or line.receipt_id != r.id:
        raise HTTPException(404, "Line not found")
    return line


def _editable(r: Receipt) -> None:
    if r.status == "confirmed":
        raise HTTPException(409, "This receipt is already booked")


def receipt_out(db: Session, r: Receipt, with_lines: bool = False) -> ReceiptOut:
    totals = [ln.line_total for ln in r.lines if ln.line_total is not None]
    out = ReceiptOut(id=r.id, status=r.status, error=r.error, store_id=r.store_id, store_name=r.store_name,
                     purchased_on=r.purchased_on, total=r.total, currency=r.currency, created_at=r.created_at,
                     securo_transaction_id=r.securo_transaction_id, line_count=len(r.lines), lines_total=sum(totals) if totals else None)
    if with_lines:
        names = {p.id: p.name for p in db.scalars(select(Product).where(
            Product.id.in_([ln.product_id for ln in r.lines if ln.product_id])))}
        out.lines = [ReceiptLineOut.model_validate(ln).model_copy(update={"product_name": names.get(ln.product_id)})
                     for ln in r.lines]
    return out


@router.get("", response_model=list[ReceiptOut])
def list_receipts(limit: int = 50, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    rows = db.scalars(select(Receipt).where(Receipt.household_id == a.household.id)
                      .order_by(Receipt.created_at.desc()).limit(min(limit, 200))).all()
    return [receipt_out(db, r) for r in rows]


@router.post("", response_model=ReceiptOut, status_code=201)
async def upload(background: BackgroundTasks, file: UploadFile = File(...),
                 a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Upload a photo; it is read in the background (poll GET until status is parsed or failed)."""
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "Photo is larger than 20 MB")
    try:
        path = svc.store_image(a.household.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    r = Receipt(household_id=a.household.id, image_path=path, status="new", uploaded_by=a.user.id,
                currency=a.household.currency)
    db.add(r)
    db.commit()
    background.add_task(svc.parse, r.id)
    return receipt_out(db, r)


@router.get("/{receipt_id}", response_model=ReceiptOut)
def get_receipt(receipt_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return receipt_out(db, _get(db, a, receipt_id), with_lines=True)


@router.get("/{receipt_id}/image")
def image(receipt_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    r = _get(db, a, receipt_id)
    if not r.image_path or not Path(r.image_path).is_file():
        raise HTTPException(404, "No photo")
    return FileResponse(r.image_path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.post("/{receipt_id}/parse", response_model=ReceiptOut)
def reparse(receipt_id: str, background: BackgroundTasks, a: HouseholdAccess = Depends(household_access),
            db: Session = Depends(get_db)):
    """Read the photo again (after connecting ChatGPT, or when the first read was poor)."""
    r = _get(db, a, receipt_id)
    _editable(r)
    r.status, r.error = "new", None
    db.commit()
    background.add_task(svc.parse, r.id)
    return receipt_out(db, r)


@router.patch("/{receipt_id}", response_model=ReceiptOut)
def patch_receipt(receipt_id: str, body: ReceiptPatch, a: HouseholdAccess = Depends(household_access),
                  db: Session = Depends(get_db)):
    r = _get(db, a, receipt_id)
    _editable(r)
    fields = body.model_dump(exclude_unset=True)
    if "store_id" in fields:
        _check_ref(db, Store, fields["store_id"], a.household.id, "Store")
    for k, v in fields.items():
        setattr(r, k, v)
    db.commit()
    return receipt_out(db, r, with_lines=True)


@router.post("/{receipt_id}/lines", response_model=ReceiptOut, status_code=201)
def add_line(receipt_id: str, body: ReceiptLineIn, a: HouseholdAccess = Depends(household_access),
             db: Session = Depends(get_db)):
    r = _get(db, a, receipt_id)
    _editable(r)
    _check_ref(db, Product, body.product_id, a.household.id, "Product")
    r.lines.append(ReceiptLine(position=max([ln.position for ln in r.lines], default=-1) + 1,
                               matched_by="user" if body.product_id else None, **body.model_dump()))
    db.commit()
    return receipt_out(db, r, with_lines=True)


@router.patch("/{receipt_id}/lines/{line_id}", response_model=ReceiptLineOut)
def patch_line(receipt_id: str, line_id: str, body: ReceiptLinePatch, a: HouseholdAccess = Depends(household_access),
               db: Session = Depends(get_db)):
    r = _get(db, a, receipt_id)
    _editable(r)
    line = _line(db, r, line_id)
    fields = body.model_dump(exclude_unset=True)
    if fields.pop("clear_product", False):
        line.product_id, line.matched_by = None, None
    if fields.get("product_id"):
        _check_ref(db, Product, fields["product_id"], a.household.id, "Product")
        line.matched_by = "user"
    for k, v in fields.items():
        if v is not None or k in ("unit_price", "line_total", "name"):
            setattr(line, k, v)
    db.commit()
    p = db.get(Product, line.product_id) if line.product_id else None
    return ReceiptLineOut.model_validate(line).model_copy(update={"product_name": p.name if p else None})


@router.delete("/{receipt_id}/lines/{line_id}", status_code=204)
def delete_line(receipt_id: str, line_id: str, a: HouseholdAccess = Depends(household_access),
                db: Session = Depends(get_db)):
    r = _get(db, a, receipt_id)
    _editable(r)
    r.lines.remove(_line(db, r, line_id))
    db.commit()


@router.post("/{receipt_id}/confirm", response_model=ConfirmOut)
def confirm(receipt_id: str, body: ConfirmIn | None = None, a: HouseholdAccess = Depends(household_access),
            db: Session = Depends(get_db)):
    """Add the reviewed lines to stock with their prices, and learn the receipt names."""
    body = body or ConfirmIn()
    r = _get(db, a, receipt_id)
    _editable(r)
    if r.status != "parsed":
        raise HTTPException(409, "The receipt has not been read yet")
    _check_ref(db, Location, body.location_id, a.household.id, "Location")
    result = svc.confirm(db, r, a.user.id, create_missing=body.create_missing, location_id=body.location_id)
    db.commit()
    return result


@router.delete("/{receipt_id}", status_code=204)
def delete_receipt(receipt_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Deletes the receipt and its photo. Stock already booked from it stays."""
    r = _get(db, a, receipt_id)
    if r.image_path:
        Path(r.image_path).unlink(missing_ok=True)
    db.delete(r)
    db.commit()


# --- Securo: which card payment was this? ------------------------------------------
@router.get("/{receipt_id}/securo-candidates", response_model=list[SecuroCandidate])
def securo_candidates(receipt_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Card payments in Securo with this receipt's amount around its date, best match first."""
    r = _get(db, a, receipt_id)
    try:
        conn = securo.conn_for(db, a.household.id)
        return securo.candidates(db, r, securo.transactions(conn, *securo.search_window(r)))
    except securo.SecuroError as e:
        raise HTTPException(502, str(e)) from e


@router.post("/{receipt_id}/securo-link", response_model=ReceiptOut)
def securo_link(receipt_id: str, body: SecuroLinkIn, a: HouseholdAccess = Depends(household_access),
                db: Session = Depends(get_db)):
    """Link the receipt to a Securo payment; optionally attach the photo and add an item summary to its note."""
    r = _get(db, a, receipt_id)
    try:
        conn = securo.conn_for(db, a.household.id)
        txns = securo.transactions(conn, *securo.search_window(r))
        t = next((t for t in txns if t["id"] == body.transaction_id), None)
        if t is None:
            raise HTTPException(404, "That payment is not near this receipt's date")
        photo = Path(r.image_path).read_bytes() if body.attach_photo and r.image_path and Path(r.image_path).is_file() \
            else None
        name = f"receipt-{(r.purchased_on or r.created_at.date()).isoformat()}.jpg"
        securo.link(conn, t["id"], photo=photo, photo_name=name,
                    note=securo.summary_note(db, r) if body.add_note else None, existing_notes=t.get("notes"))
    except securo.SecuroError as e:
        raise HTTPException(502, str(e)) from e
    r.securo_transaction_id = t["id"]
    db.commit()
    return receipt_out(db, r, with_lines=True)


@router.delete("/{receipt_id}/securo-link", response_model=ReceiptOut)
def securo_unlink(receipt_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Forget the link in Kasita (the photo and note stay in Securo)."""
    r = _get(db, a, receipt_id)
    r.securo_transaction_id = None
    db.commit()
    return receipt_out(db, r, with_lines=True)
