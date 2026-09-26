from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Product, ProductBarcode, StockEntry, StockEvent, Store
from ..schemas import BarcodeLookupOut, PricePoint, ProductIn, ProductOut, ProductPatch
from ..services import barcodes as bc
from ..services.stock import get_product, in_stock

router = APIRouter(prefix="/api/households/{household_id}", tags=["products"])


def product_out(db: Session, p: Product) -> ProductOut:
    nxt = db.scalar(select(func.min(StockEntry.best_before)).where(
        StockEntry.product_id == p.id, StockEntry.quantity > 0))
    fields = {k: getattr(p, k) for k in ProductOut.model_fields if k not in ("barcodes", "in_stock", "next_best_before")}
    return ProductOut(**fields, barcodes=[b.barcode for b in p.barcodes], in_stock=in_stock(db, p.id),
                      next_best_before=nxt)


def _attach_barcodes(db: Session, household_id: str, product: Product, codes: list[str]) -> None:
    for raw in codes:
        code = bc.normalise(raw)
        if not code:
            raise HTTPException(422, f"Not a valid barcode: {raw!r}")
        taken = db.scalar(select(ProductBarcode).where(ProductBarcode.household_id == household_id,
                                                       ProductBarcode.barcode == code))
        if taken and taken.product_id != product.id:
            raise HTTPException(409, f"Barcode {code} already belongs to another product")
        if not taken:
            db.add(ProductBarcode(household_id=household_id, product_id=product.id, barcode=code))


@router.get("/products", response_model=list[ProductOut])
def list_products(q: str | None = None, include_archived: bool = False,
                  a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    stmt = select(Product).where(Product.household_id == a.household.id)
    if not include_archived:
        stmt = stmt.where(Product.archived.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Product.name.ilike(like), Product.brand.ilike(like), Product.category.ilike(like)))
    return [product_out(db, p) for p in db.scalars(stmt.order_by(Product.name))]


@router.post("/products", response_model=ProductOut, status_code=201)
def create_product(body: ProductIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    data = body.model_dump(exclude={"barcodes"})
    p = Product(household_id=a.household.id, **data)
    db.add(p)
    db.flush()
    _attach_barcodes(db, a.household.id, p, body.barcodes)
    db.commit()
    db.refresh(p)
    return product_out(db, p)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_one(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return product_out(db, get_product(db, a.household.id, product_id))


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(product_id: str, body: ProductPatch, a: HouseholdAccess = Depends(household_access),
                   db: Session = Depends(get_db)):
    p = get_product(db, a.household.id, product_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    return product_out(db, p)


@router.post("/products/{product_id}/barcodes", response_model=ProductOut)
def add_barcode(product_id: str, barcode: str = Query(...), a: HouseholdAccess = Depends(household_access),
                db: Session = Depends(get_db)):
    p = get_product(db, a.household.id, product_id)
    _attach_barcodes(db, a.household.id, p, [barcode])
    db.commit()
    db.refresh(p)
    return product_out(db, p)


@router.get("/barcodes/{barcode}", response_model=BarcodeLookupOut)
def lookup_barcode(barcode: str, refresh: bool = False, a: HouseholdAccess = Depends(household_access),
                   db: Session = Depends(get_db)):
    """What is this barcode? The household's own product wins; otherwise ask the public databases."""
    code = bc.normalise(barcode)
    if not code:
        raise HTTPException(422, "Not a valid barcode")
    link = db.scalar(select(ProductBarcode).where(ProductBarcode.household_id == a.household.id,
                                                  ProductBarcode.barcode == code))
    if link and not refresh:
        return BarcodeLookupOut(barcode=code, product=product_out(db, link.product), found=True, source="household",
                                name=link.product.name, brand=link.product.brand, image_url=link.product.image_url)
    hit = bc.lookup(db, code, refresh=refresh)
    return BarcodeLookupOut(barcode=code, product=product_out(db, link.product) if link else None, found=hit.found,
                            source=hit.source, name=hit.name, brand=hit.brand, quantity_text=hit.quantity_text,
                            image_url=hit.image_url, categories=hit.categories)


@router.get("/products/{product_id}/prices", response_model=list[PricePoint])
def price_history(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Every price paid for this product, newest first (from purchases and receipts)."""
    get_product(db, a.household.id, product_id)
    rows = db.execute(select(StockEvent, Store.name).outerjoin(Store, Store.id == StockEvent.store_id).where(
        StockEvent.product_id == product_id, StockEvent.kind == "purchase", StockEvent.unit_price.is_not(None),
    ).order_by(StockEvent.at.desc())).all()
    return [PricePoint(at=e.at, unit_price=e.unit_price, quantity=e.quantity, store_id=e.store_id, store_name=name)
            for e, name in rows]
