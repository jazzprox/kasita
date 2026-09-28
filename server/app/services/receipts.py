"""Receipt photo → line items → stock.

1. `store_image` shrinks the photo and keeps it.
2. `parse` asks the AI to read it (see `read_with_chatgpt`) and matches each
   line to a product: first by what this household confirmed before at this
   store (`ReceiptAlias`), then by a name guess the user reviews.
3. `confirm` turns the reviewed lines into purchases (prices go into the
   price history) and remembers each line → product for next time.
"""
import base64
import io
import json
import logging
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Product, Receipt, ReceiptAlias, ReceiptLine, Store
from . import categories, chatgpt, codex
from . import stock as stock_svc

log = logging.getLogger(__name__)

INSTRUCTIONS = """You read photos of shop receipts (mostly supermarkets in Curaçao) and reply with ONLY a JSON object, no prose, no code fences:
{"store": string|null, "date": "YYYY-MM-DD"|null, "currency": string|null, "total": number|null,
 "lines": [{"text": string, "name": string, "quantity": number, "unit_price": number|null, "line_total": number|null, "kind": "item"|"fee"|"deposit"}]}

- "text": the product line exactly as printed (abbreviations and all), without the price.
- "name": a short, plain product name a person would write on a shopping list, in English, keeping the brand when it is printed, with size if printed (e.g. "Goisco toilet paper 12 rolls", "Whole milk 1 L").
- "quantity": number of units bought; for weighed items the weight in kg. Default 1.
- "line_total": what was paid for that line after any discount on that item. Fold item discounts / savings / "korting" lines into the item they belong to instead of listing them. Ignore discounts on the whole receipt.
- Bag fees, bottle or crate deposits, service charges: kind "fee" or "deposit". Leave out subtotals, tax (OB) lines, payment method, change, loyalty points and cashier info.
- "total": the amount paid for the whole receipt.
- "currency": ISO code. NAf, ANG, Cg, XCG and "fl" all mean the Caribbean guilder: use "XCG". "$" or USD: "USD".
- Numbers use a dot as decimal separator. Use null when something is not readable; never invent lines.
- If the photo is not a receipt or cannot be read at all, reply {"error": "<short reason>"}."""


def receipts_dir(household_id: str) -> Path:
    d = Path(settings.upload_dir) / "receipts" / household_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_image(household_id: str, data: bytes) -> str:
    """Normalise to an upright JPEG no longer than `receipt_max_px`; returns the path."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("That file is not an image Kasita can read") from e
    img.thumbnail((settings.receipt_max_px, settings.receipt_max_px))
    path = receipts_dir(household_id) / f"{uuid.uuid4()}.jpg"
    img.save(path, "JPEG", quality=85, optimize=True)
    return str(path)


def read_with_chatgpt(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Ask the household's ChatGPT to read the receipt. Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    currency = _household_currency(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS, [
        {"type": "input_text", "text": f"Read this receipt. If no currency is printed, assume {currency}."},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
         "detail": "high"},
    ])
    return extract_json(text)


def extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("The AI did not return a readable answer")
    return json.loads(m.group(0))


def _household_currency(db: Session, household_id: str) -> str:
    from ..models import Household
    h = db.get(Household, household_id)
    return h.currency if h else "XCG"


def _num(v) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v).replace(",", ".")).quantize(Decimal("0.001"))
    except (InvalidOperation, ValueError):
        return None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def text_key(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^0-9A-Z ]+", " ", text.upper())).strip()[:255]


def find_store(db: Session, household_id: str, printed: str | None) -> Store | None:
    if not printed:
        return None
    wanted = printed.strip().lower()
    stores = db.scalars(select(Store).where(Store.household_id == household_id)).all()
    for s in stores:
        if s.name.lower() == wanted or (s.payee_match and s.payee_match.lower() in wanted) or s.name.lower() in wanted \
                or wanted in s.name.lower():
            return s
    return None


def _guess(name: str, products: list[Product]) -> Product | None:
    wanted = name.lower()
    best, score = None, 0.0
    for p in products:
        candidates = [p.name.lower()] + ([f"{p.brand} {p.name}".lower()] if p.brand else [])
        s = max(SequenceMatcher(None, wanted, c).ratio() for c in candidates)
        if s > score:
            best, score = p, s
    return best if score >= 0.72 else None


def apply_parsed(db: Session, receipt: Receipt, parsed: dict) -> None:
    """Fill a receipt from the AI's answer and match lines to products."""
    if parsed.get("error"):
        raise ValueError(f"The AI could not read this receipt: {parsed['error']}")
    receipt.raw = parsed
    receipt.store_name = (parsed.get("store") or "")[:120] or None
    receipt.purchased_on = _date(parsed.get("date")) or receipt.purchased_on
    receipt.currency = (parsed.get("currency") or "")[:3].upper() or _household_currency(db, receipt.household_id)
    receipt.total = _num(parsed.get("total"))
    if not receipt.store_id:
        store = find_store(db, receipt.household_id, receipt.store_name)
        receipt.store_id = store.id if store else None
    receipt.lines.clear()
    db.flush()
    products = db.scalars(select(Product).where(Product.household_id == receipt.household_id,
                                                Product.archived.is_(False))).all()
    for i, raw in enumerate(parsed.get("lines") or []):
        text = str(raw.get("text") or raw.get("name") or "").strip()[:255]
        if not text:
            continue
        qty = _num(raw.get("quantity")) or Decimal(1)
        if qty <= 0:
            qty = Decimal(1)
        total = _num(raw.get("line_total"))
        unit = _num(raw.get("unit_price"))
        if unit is None and total is not None:
            unit = (total / qty).quantize(Decimal("0.01"))
        line = ReceiptLine(position=i, raw_text=text, name=(raw.get("name") or "")[:255] or None, quantity=qty,
                           unit_price=unit, line_total=total, skip=raw.get("kind") in ("fee", "deposit"))
        receipt.lines.append(line)
        if not line.skip:
            match_line(db, receipt, line, products)
    receipt.status = "parsed"
    receipt.error = None


def match_line(db: Session, receipt: Receipt, line: ReceiptLine, products: list[Product]) -> None:
    key = text_key(line.raw_text)
    aliases = db.scalars(select(ReceiptAlias).where(ReceiptAlias.household_id == receipt.household_id,
                                                    ReceiptAlias.text_key == key)).all()
    # the same text at the same store is certain; at another store it is still a good bet
    alias = next((a for a in aliases if a.store_id == receipt.store_id), None) or (aliases[0] if aliases else None)
    if alias:
        line.product_id, line.matched_by = alias.product_id, "alias"
        return
    guess = _guess(line.name or line.raw_text, products)
    if guess:
        line.product_id, line.matched_by = guess.id, "guess"


def parse(receipt_id: str) -> None:
    """Background job: read the photo with the AI. Uses its own session."""
    with SessionLocal() as db:
        receipt = db.get(Receipt, receipt_id)
        if not receipt or receipt.status == "confirmed":
            return
        try:
            jpeg = Path(receipt.image_path).read_bytes()
            parsed = read_with_chatgpt(db, receipt.household_id, jpeg)
            apply_parsed(db, receipt, parsed)
        except Exception as e:  # noqa: BLE001  (shown to the user on the receipt)
            db.rollback()
            receipt = db.get(Receipt, receipt_id)
            receipt.status = "failed"
            receipt.error = str(e)[:500] if isinstance(e, (ValueError, codex.CodexError)) else "Reading the receipt failed"
            log.warning("receipt %s failed: %r", receipt_id, e)
        db.commit()


def confirm(db: Session, receipt: Receipt, user_id: str | None, *, create_missing: bool = True,
            location_id: str | None = None) -> dict:
    """Book the reviewed lines as purchases and learn their names for next time."""
    hid = receipt.household_id
    if not receipt.store_id and receipt.store_name:
        store = find_store(db, hid, receipt.store_name)
        if not store:
            store = Store(household_id=hid, name=receipt.store_name.strip().title()[:120])
            db.add(store)
            db.flush()
        receipt.store_id = store.id
    added, created, skipped = 0, 0, 0
    for line in receipt.lines:
        if line.skip:
            skipped += 1
            continue
        product = db.get(Product, line.product_id) if line.product_id else None
        if product is None or product.household_id != hid:
            if not create_missing:
                skipped += 1
                continue
            weighed = line.quantity != line.quantity.to_integral_value()
            name = (line.name or line.raw_text.title())[:255]
            product = Product(household_id=hid, name=name, unit="kg" if weighed else "pcs",
                              category=categories.guess(name))
            db.add(product)
            db.flush()
            line.product_id = product.id
            created += 1
        unit_price = line.unit_price
        if unit_price is None and line.line_total is not None:
            unit_price = (line.line_total / line.quantity).quantize(Decimal("0.01"))
        stock_svc.purchase(db, hid, user_id, product, line.quantity, location_id=location_id, unit_price=unit_price,
                           store_id=receipt.store_id, purchased_at=receipt.purchased_on, receipt_line_id=line.id)
        remember(db, hid, receipt.store_id, line.raw_text, product.id)
        added += 1
    receipt.status = "confirmed"
    return {"added": added, "created_products": created, "skipped": skipped}


def remember(db: Session, household_id: str, store_id: str | None, raw_text: str, product_id: str) -> None:
    key = text_key(raw_text)
    if not key:
        return
    row = db.scalar(select(ReceiptAlias).where(ReceiptAlias.household_id == household_id,
                                               ReceiptAlias.store_id.is_(None) if store_id is None
                                               else ReceiptAlias.store_id == store_id,
                                               ReceiptAlias.text_key == key))
    if row:
        row.product_id = product_id
    else:
        db.add(ReceiptAlias(household_id=household_id, store_id=store_id, text_key=key, product_id=product_id))
    db.flush()

