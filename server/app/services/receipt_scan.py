"""Scan a pack to say what a receipt line was.

Small shops print departments ("COMESTIBELS 7.99"), so the only way to know
the product is the pack itself. `resolve` turns a barcode into a household
product: one this household already has, or a new one made from the product
databases without any form. `pick_line` is for scanning a whole bag at once:
it chooses which open line of the receipt the scanned product most likely is.
"""
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BarcodeCache, Product, ProductBarcode, Receipt, ReceiptLine, StockEvent
from . import barcodes as bc
from . import categories, departments
from .receipts import text_key


@dataclass
class Resolved:
    status: str  # known | created | unknown
    barcode: str
    product: Product | None = None
    hit: BarcodeCache | None = None


def resolve(db: Session, household_id: str, barcode: str) -> Resolved:
    """The household's product for this barcode; creates it from the databases when they know it."""
    code = bc.normalise(barcode)
    if not code:
        raise ValueError("Not a valid barcode")
    link = db.scalar(select(ProductBarcode).where(ProductBarcode.household_id == household_id,
                                                  ProductBarcode.barcode == code))
    if link:
        p = link.product
        p.archived = False  # bought it again
        return Resolved("known", code, p)
    hit = bc.lookup(db, code)
    if not hit.found:
        return Resolved("unknown", code, hit=hit)
    name = hit.name or f"Barcode {code}"
    size = (hit.quantity_text or "").strip()
    if size and size.lower().replace(" ", "") not in name.lower().replace(" ", ""):
        name = f"{name} {size}"
    p = Product(household_id=household_id, name=name[:255], brand=hit.brand, image_url=hit.image_url,
                db_image_url=hit.image_url,
                category=categories.guess(hit.name, hit.categories) or categories.SOURCE_DEFAULT.get(hit.source or ""))
    db.add(p)
    db.flush()
    db.add(ProductBarcode(household_id=household_id, product_id=p.id, barcode=code))
    db.flush()
    return Resolved("created", code, p, hit)


def last_price(db: Session, product_id: str, store_id: str | None) -> Decimal | None:
    """What this product cost last time: at this store if it was bought there, else anywhere."""
    base = select(StockEvent.unit_price).where(StockEvent.product_id == product_id, StockEvent.kind == "purchase",
                                               StockEvent.unit_price.is_not(None)).order_by(StockEvent.at.desc())
    if store_id:
        here = db.scalar(base.where(StockEvent.store_id == store_id).limit(1))
        if here is not None:
            return here
    return db.scalar(base.limit(1))


def unit_of(line: ReceiptLine) -> Decimal | None:
    if line.unit_price is not None:
        return line.unit_price
    if line.line_total is not None and line.quantity:
        return (line.line_total / line.quantity).quantize(Decimal("0.01"))
    return None


def open_lines(receipt: Receipt) -> list[ReceiptLine]:
    """Lines a scan may land on: not skipped, not spending only, not yet linked (a guess still counts as open)."""
    return [ln for ln in receipt.lines
            if not ln.skip and not ln.spending_only and (ln.product_id is None or ln.matched_by == "guess")]


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score(db: Session, receipt: Receipt, line: ReceiptLine, product: Product,
          price: Decimal | None) -> tuple[int, str | None]:
    """How likely `line` is `product`, and the main reason, in plain words."""
    points: list[tuple[int, str | None]] = []
    unit = unit_of(line)
    if line.product_id == product.id:
        points.append((100, "Kasita had guessed this line"))
    # the same product scanned again: the twin of the line it already landed on
    for other in receipt.lines:
        if other is line or other.product_id != product.id or other.matched_by == "guess":
            continue
        if text_key(other.raw_text) == text_key(line.raw_text) and unit is not None and unit_of(other) == unit:
            points.append((60, "same text and price as the one you just scanned"))
            break
    if price is not None and unit is not None and price > 0:
        diff = abs(unit - price)
        if diff <= Decimal("0.01"):
            points.append((50, "same price as last time"))
        elif diff <= price * Decimal("0.10"):
            points.append((30, "close to the price last time"))
        elif diff <= price * Decimal("0.25"):
            points.append((10, None))
    if line.department:
        cats = departments.likely_categories(line.raw_text, line.name)
        if product.category and product.category in cats:
            points.append((20 - 2 * cats.index(product.category), f"{product.category} fits this department"))
    else:
        names = [line.name or "", line.raw_text]
        wanted = [product.name] + ([f"{product.brand} {product.name}"] if product.brand else [])
        if max(_similar(a, b) for a in names if a for b in wanted) >= 0.6:
            points.append((40, "the name matches"))
        else:
            points.append((-15, None))  # this line names something else
    total = sum(p for p, _ in points)
    best = max((p for p in points if p[1]), default=None, key=lambda p: p[0])
    return total, best[1] if best else None


def pick_line(db: Session, receipt: Receipt, product: Product) -> tuple[ReceiptLine | None, str | None]:
    """The open line the scanned product most likely is (ties: the first on the receipt)."""
    candidates = open_lines(receipt)
    if not candidates:
        return None, None
    price = last_price(db, product.id, receipt.store_id)
    scored = [(score(db, receipt, ln, product, price), ln) for ln in candidates]
    (points, reason), line = max(scored, key=lambda s: (s[0][0], -s[1].position))
    if points <= 0:
        return line, "first open line"
    return line, reason or "best guess"


def link(line: ReceiptLine, product: Product) -> None:
    line.product_id, line.matched_by = product.id, "scan"
    line.skip, line.spending_only = False, False
