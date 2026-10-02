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
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Product, Receipt, ReceiptAlias, ReceiptLine, Store
from . import categories, chatgpt, codex, departments
from . import stock as stock_svc

log = logging.getLogger(__name__)

INSTRUCTIONS = """You read photos of shop receipts (mostly supermarkets in Curaçao) and reply with ONLY a JSON object, no prose, no code fences:
{"store": string|null, "date": "YYYY-MM-DD"|null, "currency": string|null, "total": number|null,
 "lines": [{"text": string, "name": string, "quantity": number, "unit_price": number|null, "line_total": number|null, "kind": "item"|"department"|"fee"|"deposit"}]}

- "text": the product line exactly as printed (abbreviations and all), without the price.
- "name": a short, plain product name a person would write on a shopping list, in English, keeping the brand when it is printed, with size if printed (e.g. "Goisco toilet paper 12 rolls", "Whole milk 1 L").
- "quantity": number of units bought; for weighed items the weight in kg. Default 1.
- "line_total": what was paid for that line after any discount on that item. Fold item discounts / savings / "korting" lines into the item they belong to instead of listing them. Ignore discounts on the whole receipt.
- kind "department": the line names a shop DEPARTMENT or product group instead of a product. Small shops
  (Chinese minimarkets, snacks, toko's) ring items up by POS department key, so the line says what KIND of thing
  was sold, never which product. Examples: "COMESTIBELS", "KOMESTIBEL", "FRUTA / BERDURA", "AROS / BONCHI",
  "WEBU / ARINA", "BIBIDA", "KARNI", "LECHI / KESO", "SERBES", "LIMPIEZA" (Papiamentu); "COMESTIBLES",
  "ABARROTES", "VIVERES", "FRUTAS Y VERDURAS", "CARNES", "BEBIDAS", "LACTEOS" (Spanish); "LEVENSMIDDELEN",
  "KRUIDENIERS", "GROENTE / FRUIT", "VLEES", "ZUIVEL", "DRANKEN", "DIVERSEN" (Dutch); "GROCERY", "PRODUCE",
  "DEPT 3", "MISC" (English). A brand, a size or a specific product ("LECHI KRIOYO 1L", "ARROZ BLANCO 5LB",
  "BANANA") is an "item". For a department line, "name" is a plain description of the group in English
  (e.g. "Fruit and vegetables", "Rice and beans", "Groceries").
- Bag fees, bottle or crate deposits, service charges: kind "fee" or "deposit". Leave out subtotals, tax (OB) lines, payment method, change, loyalty points and cashier info.
- "total": the amount paid for the whole receipt.
- "currency": ISO code. NAf, ANG, Cg, XCG and "fl" all mean the Caribbean guilder: use "XCG". "$" or USD: "USD".
- Check your work: the line totals should add up to the total paid. If they don't, look again for a missed or doubled line.
- Numbers use a dot as decimal separator. Use null when something is not readable; never invent lines.
- If the photo is not a receipt or cannot be read at all, reply {"error": "<short reason>"}."""


def receipts_dir(household_id: str) -> Path:
    d = Path(settings.upload_dir) / "receipts" / household_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _open(data: bytes) -> Image.Image:
    try:
        return ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("That file is not an image Kasita can read") from e


def _tall(img: Image.Image) -> bool:
    return img.height > img.width * 1.5


def store_images(household_id: str, parts: list[bytes], folder: Path | None = None) -> str:
    """One receipt photo, or several parts of a long receipt taken top to bottom.

    A normal photo is kept as before (longest side <= receipt_max_px). Parts and
    tall panoramas keep their text size instead: every part is scaled to the same
    width (<= receipt_strip_width) and they are stacked into one long strip, with
    a dark bar where one photo ends and the next begins.
    """
    imgs = [_open(d) for d in parts]
    if len(imgs) == 1 and not _tall(imgs[0]):
        img = imgs[0]
        img.thumbnail((settings.receipt_max_px, settings.receipt_max_px))
    else:
        width = min(settings.receipt_strip_width, min(i.width for i in imgs))
        scaled = [i.resize((width, max(1, round(i.height * width / i.width)))) for i in imgs]
        bar = 16
        height = sum(i.height for i in scaled) + bar * (len(scaled) - 1)
        if height > settings.receipt_strip_max_height:
            raise ValueError("That receipt is too long for one scan: split it into two receipts")
        img = Image.new("RGB", (width, height), (40, 40, 40))
        y = 0
        for i in scaled:
            img.paste(i, (0, y))
            y += i.height + bar
    path = (folder or receipts_dir(household_id)) / f"{uuid.uuid4()}.jpg"
    img.save(path, "JPEG", quality=85, optimize=True)
    return str(path)


def store_image(household_id: str, data: bytes) -> str:
    return store_images(household_id, [data])


def sections(jpeg: bytes, max_sections: int = 10) -> list[bytes]:
    """A tall strip as overlapping sections the vision model can read at full size.

    Vision models shrink big images to fit roughly 2048 px, which turns a long
    strip's text to mush, so each section is about 1.3x as tall as wide, and
    consecutive sections overlap by 15% so no line is cut in half unseen.
    """
    img = Image.open(io.BytesIO(jpeg))
    w, h = img.size
    if h <= w * 1.5:
        return [jpeg]
    tile = int(w * 1.3)
    while True:
        step = int(tile * 0.85)
        count = 1 + max(0, -(-(h - tile) // step))
        if count <= max_sections:
            break
        tile = int(tile * 1.25)
    out = []
    for n in range(count):
        top = min(n * step, h - tile)
        buf = io.BytesIO()
        img.crop((0, top, w, top + tile)).save(buf, "JPEG", quality=88)
        out.append(buf.getvalue())
    return out


def read_with_chatgpt(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Ask the household's ChatGPT to read the receipt. Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    currency = _household_currency(db, household_id)
    parts = sections(jpeg)
    intro = f"Read this receipt. If no currency is printed, assume {currency}."
    if len(parts) > 1:
        intro += (f" It is long, so it comes as {len(parts)} overlapping sections, top to bottom. A line at the"
                  " bottom of one section that shows again at the top of the next is the SAME line: list it once."
                  " A dark bar marks where one photo ended and the next began; those photos overlap too.")
    content = [{"type": "input_text", "text": intro}] + [
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(p).decode(),
         "detail": "high"} for p in parts]
    text = codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS, content)
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
            line.department = is_department(db, receipt, line, ai_says=raw.get("kind") == "department")
            if not line.department:
                match_line(db, receipt, line, products)
    receipt.status = "parsed"
    receipt.error = None


def _store_alias(db: Session, household_id: str, store_id: str | None, key: str) -> ReceiptAlias | None:
    return db.scalar(select(ReceiptAlias).where(ReceiptAlias.household_id == household_id,
                                                ReceiptAlias.store_id.is_(None) if store_id is None
                                                else ReceiptAlias.store_id == store_id,
                                                ReceiptAlias.text_key == key))


def is_department(db: Session, receipt: Receipt, line: ReceiptLine, *, ai_says: bool = False) -> bool:
    """Is this line a shop department ("COMESTIBELS") rather than a product? See services/departments.

    Learned for this store wins; then a product this household taught for exactly this text at this
    store (someone said "not a department" and booked it); then the AI's flag and the word list."""
    key = text_key(line.raw_text)
    if not key:
        return False
    if departments.learned(db, receipt.household_id, receipt.store_id, key):
        return True
    if receipt.store_id and _store_alias(db, receipt.household_id, receipt.store_id, key):
        return False
    return ai_says or departments.is_department_text(line.raw_text)


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
    added, created, skipped, spending = 0, 0, 0, 0
    # What THIS receipt has already created, keyed the way aliases are keyed.
    #
    # A shop rings two of the same thing up as two lines of quantity 1, not
    # one line of quantity 2 — a real receipt here printed PINEAPPLE CHUNKS
    # twice (at 8.62 and 7.89) and CERES TROPICAL BLAST 1LT twice. Aliases are
    # matched when the receipt is PARSED and only written by `remember()` at
    # the end of this loop, so the second line could never see what the first
    # one had just made, and each pair became two separate products with the
    # same name. Every later feature then treats them as different things:
    # stock is split, the shopping list offers both, and a barcode can only be
    # attached to one of them (they are unique per household).
    #
    # The quantities still land on the one product, because `purchase()` is
    # called per line either way.
    made: dict[str, Product] = {}
    for line in receipt.lines:
        if line.skip:
            skipped += 1
            continue
        key_raw = text_key(line.raw_text)
        dept = line.department or bool(key_raw and departments.learned(db, hid, receipt.store_id, key_raw))
        if dept and not line.product_id:
            # a department nobody scanned: what it was is unknown, so it counts as spending only
            line.spending_only = True
        if line.spending_only:
            line.product_id, line.matched_by = None, None
            line.spending_category = line.spending_category or departments.default_category(line.raw_text, line.name)
            spending += 1
            continue
        product = db.get(Product, line.product_id) if line.product_id else None
        if product is None or product.household_id != hid:
            if not create_missing:
                skipped += 1
                continue
            key = text_key(line.name or line.raw_text)
            product = made.get(key) if key else None
            if product is not None:
                # A second line of something this receipt already created.
                line.product_id = product.id
            else:
                weighed = line.quantity != line.quantity.to_integral_value()
                name = (line.name or line.raw_text.title())[:255]
                product = Product(household_id=hid, name=name, unit="kg" if weighed else "pcs",
                                  category=categories.guess(name))
                db.add(product)
                db.flush()
                line.product_id = product.id
                if key:
                    made[key] = product
                created += 1
        unit_price = line.unit_price
        if unit_price is None and line.line_total is not None:
            unit_price = (line.line_total / line.quantity).quantize(Decimal("0.01"))
        stock_svc.purchase(db, hid, user_id, product, line.quantity, location_id=location_id, unit_price=unit_price,
                           store_id=receipt.store_id, purchased_at=receipt.purchased_on, receipt_line_id=line.id)
        if dept:
            departments.learn(db, hid, receipt.store_id, key_raw)  # next time it is known without the AI
        else:
            remember(db, hid, receipt.store_id, line.raw_text, product.id)
        added += 1
    receipt.status = "confirmed"
    receipt.confirmed_at = datetime.now(timezone.utc)
    return {"added": added, "created_products": created, "skipped": skipped, "spending_only": spending}


def remember(db: Session, household_id: str, store_id: str | None, raw_text: str, product_id: str) -> None:
    """Learn "this store prints this text for this product". The same text booked as a DIFFERENT
    product means it is a department, not a product: it is then never auto-linked again."""
    key = text_key(raw_text)
    if not key:
        return
    row = _store_alias(db, household_id, store_id, key)
    if row and row.product_id != product_id:
        db.delete(row)
        departments.learn(db, household_id, store_id, key)
        return
    if row:
        row.product_id = product_id
    else:
        db.add(ReceiptAlias(household_id=household_id, store_id=store_id, text_key=key, product_id=product_id))
    db.flush()

