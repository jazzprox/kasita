import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Product, ProductBarcode, StockEntry, StockEvent, Store
from ..schemas import CookIn, BarcodeLookupOut, PricePoint, ProductIn, ProductOut, ProductPatch
from ..services import barcodes as bc
from ..services import categories, codex
from ..services import contribute as contrib
from ..services import cook as cooking
from ..services import identify as ident
from ..services.stock import get_product, in_stock

router = APIRouter(prefix="/api/households/{household_id}", tags=["products"])


def _is_local(url: str | None) -> bool:
    return bool(url) and "/api/product-images/" in url


def _photo_source(url: str | None) -> str | None:
    return None if not url else ("yours" if _is_local(url) else "database")


def _runs_out(db: Session, p: Product) -> float | None:
    from ..services.stock import forecast
    fc = forecast(db, p)
    return round(fc[1], 1) if fc else None


def product_out(db: Session, p: Product) -> ProductOut:
    nxt = db.scalar(select(func.min(StockEntry.best_before)).where(
        StockEntry.product_id == p.id, StockEntry.quantity > 0))
    fields = {k: getattr(p, k) for k in ProductOut.model_fields if k not in ("barcodes", "in_stock", "next_best_before", "shareable", "runs_out_in_days",
                                                           "photo_source", "can_restore_photo")}
    return ProductOut(**fields, barcodes=[b.barcode for b in p.barcodes], in_stock=in_stock(db, p.id),
                      next_best_before=nxt, shareable=contrib.shareable_barcode(db, p) is not None,
                      runs_out_in_days=_runs_out(db, p), photo_source=_photo_source(p.image_url),
                      can_restore_photo=bool(p.db_image_url and p.image_url != p.db_image_url))


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
    if p.image_url and not _is_local(p.image_url):
        p.db_image_url = p.image_url  # created from a barcode lookup: that picture is the database's
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
    """Attach a barcode (e.g. to a product that came from a receipt). Fills in the photo, brand and
    category from the product databases where the product has none yet; never overwrites."""
    p = get_product(db, a.household.id, product_id)
    _attach_barcodes(db, a.household.id, p, [barcode])
    hit = bc.lookup(db, bc.normalise(barcode) or barcode)
    if hit.found:
        p.image_url = p.image_url or hit.image_url
        p.db_image_url = p.db_image_url or hit.image_url
        p.brand = p.brand or hit.brand
        p.category = p.category or categories.guess(hit.name, hit.categories) \
            or categories.SOURCE_DEFAULT.get(hit.source or "")
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
                                name=link.product.name, brand=link.product.brand, image_url=link.product.image_url,
                                category=link.product.category)
    hit = bc.lookup(db, code, refresh=refresh)
    hint = None if hit.found else bc.brand_hint(db, a.household.id, code)
    return BarcodeLookupOut(brand_hint=hint, barcode=code, product=product_out(db, link.product) if link else None, found=hit.found,
                            source=hit.source, name=hit.name, brand=hit.brand, quantity_text=hit.quantity_text,
                            image_url=hit.image_url, categories=hit.categories,
                            category=categories.guess(hit.name, hit.categories)
                            or categories.SOURCE_DEFAULT.get(hit.source or ""))


@router.get("/products/{product_id}/prices", response_model=list[PricePoint])
def price_history(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Every price paid for this product, newest first (from purchases and receipts)."""
    get_product(db, a.household.id, product_id)
    rows = db.execute(select(StockEvent, Store.name, StockEntry.purchased_at)
                      .outerjoin(Store, Store.id == StockEvent.store_id)
                      .outerjoin(StockEntry, StockEntry.id == StockEvent.entry_id).where(
        StockEvent.product_id == product_id, StockEvent.kind == "purchase", StockEvent.unit_price.is_not(None),
    )).all()
    # newest first by the day it was bought (a receipt's date), not the day it was booked
    rows = sorted(rows, key=lambda r: (r[2] or r[0].at.date(), r[0].at), reverse=True)
    return [PricePoint(at=e.at, on=bought or e.at.date(), unit_price=e.unit_price, quantity=e.quantity,
                       store_id=e.store_id, store_name=name) for e, name, bought in rows]


@router.get("/categories", response_model=list[str])
def category_list(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Kasita's categories plus any other ones this household already uses."""
    used = db.scalars(select(Product.category).where(Product.household_id == a.household.id,
                                                     Product.category.is_not(None)).distinct()).all()
    return categories.CATEGORIES + sorted(c for c in used if c and c not in categories.CATEGORIES)


@router.post("/products/identify")
async def identify_product(file: UploadFile = File(...), a: HouseholdAccess = Depends(household_access),
                           db: Session = Depends(get_db)):
    """Photo of a pack -> suggested name, brand, size, category (via the household's ChatGPT).
    Nothing is created; the app opens the New-product form with these values."""
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Photo is larger than 20 MB")
    try:
        return ident.identify(db, a.household.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except codex.CodexError as e:
        raise HTTPException(502, str(e)) from e


public = APIRouter(tags=["products"])


@public.get("/api/product-images/{household_id}/{name}", include_in_schema=False)
def product_image(household_id: str, name: str):
    """Product photos taken in the app. No login, like the Open Food Facts images: the file
    name is 128 random bits, so it can't be guessed."""
    if not re.fullmatch(r"[0-9a-f-]{36}", household_id) or not re.fullmatch(r"[0-9a-f]{32}\.jpg", name):
        raise HTTPException(404, "Not found")
    path = Path(ident.product_images_dir(household_id)) / name
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


@router.post("/products/{product_id}/contribute")
def contribute_product(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Add this product (name, brand, category, your photo) to the Open Food Facts family."""
    p = get_product(db, a.household.id, product_id)
    try:
        return contrib.contribute(db, p)
    except contrib.ContributeError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/cook")
def what_can_i_cook(body: CookIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Meal ideas from what is at home, soon-expiring things first (the household's ChatGPT)."""
    try:
        return cooking.suggest(db, a.household.id, body.note)
    except codex.CodexError as e:
        raise HTTPException(502, str(e)) from e



def _drop_local_photo(image_url: str | None) -> None:
    """Delete a photo Kasita stored (never touches Open Food Facts pictures, which are just links)."""
    if image_url and "/api/product-images/" in image_url:
        household, name = image_url.split("/api/product-images/", 1)[1].split("/", 1)
        if re.fullmatch(r"[0-9a-f]{32}\.jpg", name):
            (ident.product_images_dir(household) / name).unlink(missing_ok=True)


@router.post("/products/{product_id}/photo", response_model=ProductOut)
async def set_photo(product_id: str, file: UploadFile = File(...), a: HouseholdAccess = Depends(household_access),
                    db: Session = Depends(get_db)):
    """Take or pick a new picture for the product (replaces the old one)."""
    p = get_product(db, a.household.id, product_id)
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "Photo is larger than 20 MB")
    try:
        name, _ = ident.store_photo(a.household.id, data)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    old = p.image_url
    if old and not _is_local(old) and not p.db_image_url:
        p.db_image_url = old  # keep the database photo so it can be put back
    p.image_url = f"{settings.public_url.rstrip('/')}/api/product-images/{a.household.id}/{name}"
    db.commit()
    _drop_local_photo(old)
    return product_out(db, p)


@router.delete("/products/{product_id}/photo", response_model=ProductOut)
def remove_photo(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    p = get_product(db, a.household.id, product_id)
    old, p.image_url = p.image_url, None
    db.commit()
    _drop_local_photo(old)
    return product_out(db, p)



@router.post("/products/{product_id}/photo/restore", response_model=ProductOut)
def restore_photo(product_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Put the product database's picture back (after it was replaced or removed)."""
    p = get_product(db, a.household.id, product_id)
    if not p.db_image_url:
        raise HTTPException(409, "There is no database photo for this product")
    old, p.image_url = p.image_url, p.db_image_url
    db.commit()
    if old != p.image_url:
        _drop_local_photo(old)
    return product_out(db, p)


@router.get("/widget")
def widget(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """What the Android home-screen widget shows (fetched every 30 minutes with a read-only key)."""
    from datetime import date as _date

    from ..models import ShoppingItem
    open_items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == a.household.id,
                                                       ShoppingItem.done.is_(False))
                            .order_by(ShoppingItem.created_at)).all()
    soon_rows = db.execute(
        select(Product.name, func.min(StockEntry.best_before))
        .join(StockEntry, StockEntry.product_id == Product.id)
        .where(Product.household_id == a.household.id, StockEntry.quantity > 0, StockEntry.best_before.is_not(None),
               StockEntry.frozen_at.is_(None))
        .group_by(Product.id, Product.name)).all()
    today = _date.today()
    soon = [n for n, bb in sorted(soon_rows, key=lambda r: r[1]) if (bb - today).days <= 2][:4]
    return {"shopping_title": f"Shopping list ({len(open_items)})",
            "shopping": "\n".join(f"• {i.name}" for i in open_items[:8]) or "Nothing to buy",
            "soon": f"Use soon: {', '.join(soon)}" if soon else "",
            # the tickable list (widgets from build 37 on)
            "items": [{"id": i.id, "name": i.name, "quantity": float(i.quantity)} for i in open_items[:60]]}


@router.post("/widget/tick/{item_id}")
def widget_tick(item_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Tick an item off from the home-screen widget. The only write its read-only key may do.
    Ticking something already ticked (a retry after a lost answer) is fine."""
    from ..models import ShoppingItem
    from ..services import route
    item = db.get(ShoppingItem, item_id)
    if item is None or item.household_id != a.household.id:
        raise HTTPException(404, "Item not found")
    if not item.done:
        tick = route.record(db, item)
        item.done, item.done_at = True, tick.ticked_at
        db.commit()
    return {"id": item.id, "done": True}
