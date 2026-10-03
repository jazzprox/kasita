"""Name a product from a photo of its pack, with the household's ChatGPT.

For barcodes no database knows (local brands like Goisco, imports nobody has
entered): the person photographs the front, ChatGPT reads the label, and the
New-product form opens pre-filled. The photo is kept as the product's picture
under a random name, served without login like the Open Food Facts images are.
"""
import base64
import io
import uuid
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from ..config import settings
from . import categories, chatgpt, codex
from .receipts import extract_json

INSTRUCTIONS = f"""You identify a household product from a photo of its packaging and reply with ONLY a JSON object:
{{"name": string, "brand": string|null, "size": string|null, "category": string|null, "readable": true|false}}

- "name": what a person would write on a shopping list, in English, with the brand if it is part of how
  people name it and the size when printed (e.g. "Roland unseasoned rice vinegar 500 ml").
- "brand": the brand as printed. "size": net quantity as printed ("500 ml", "16.9 fl oz", "12 rolls").
- "category": exactly one of: {", ".join(categories.CATEGORIES)}.
- If the photo does not show a product label you can read, reply {{"readable": false}}."""


def product_images_dir(household_id: str) -> Path:
    d = Path(settings.upload_dir) / "products" / household_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_photo(household_id: str, data: bytes) -> tuple[str, bytes]:
    """Upright JPEG, at most 1000 px; returns (file name, jpeg bytes)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("That file is not an image Kasita can read") from e
    img.thumbnail((1000, 1000))
    name = f"{uuid.uuid4().hex}.jpg"
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    (product_images_dir(household_id) / name).write_bytes(buf.getvalue())
    return name, buf.getvalue()


def ask_chatgpt(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS, [
        {"type": "input_text", "text": "What product is this?"},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
         "detail": "high"},
    ], timeout=90)
    return extract_json(text)


def identify(db: Session, household_id: str, data: bytes) -> dict:
    name, jpeg = store_photo(household_id, data)
    got = ask_chatgpt(db, household_id, jpeg)
    image_url = f"{settings.public_url.rstrip('/')}/api/product-images/{household_id}/{name}"
    if got.get("readable") is False or not got.get("name"):
        return {"found": False, "image_url": image_url}
    category = got.get("category") if got.get("category") in categories.CATEGORIES \
        else categories.guess(got.get("name"))
    return {"found": True, "name": str(got["name"])[:255], "brand": (got.get("brand") or None),
            "quantity_text": (got.get("size") or None), "category": category, "image_url": image_url}


DATE_INSTRUCTIONS = """You read the best-before / use-by / expiry date printed on food or household packaging.
Reply with ONLY a JSON object: {"date": "YYYY-MM-DD" or null, "printed": "the text as printed" or null}
- Formats vary: 12/10/2026, 12.10.26, 2026-10-12, OCT 12 2026, 12 OCT, EXP 10/2026, BB 12OCT26, "Best before end: 10 2026".
- Day/month order: most packs here are European or Latin American (day first); US imports print month first
  (e.g. 10/12/2026 on a US brand is October 12). Choose the reading that is a plausible future date.
- Only a month and year: use the LAST day of that month. No year: the next occurrence of that day.
- Ignore production dates (PROD, MFG, L/lot numbers). No readable date: {"date": null}."""


def ask_date(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), DATE_INSTRUCTIONS, [
        {"type": "input_text", "text": f"Today is {date.today().isoformat()}. What date is printed?"},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
         "detail": "high"},
    ], timeout=60)
    return extract_json(text)


def read_date(db: Session, household_id: str, data: bytes) -> dict:
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("That file is not an image Kasita can read") from e
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    got = ask_date(db, household_id, buf.getvalue())
    try:
        d = date.fromisoformat(str(got.get("date"))[:10]) if got.get("date") else None
    except ValueError:
        d = None
    return {"date": d.isoformat() if d else None, "printed": got.get("printed")}


LABEL_INSTRUCTIONS = """You read a deli / butcher / scale label (cheese, meat, fish, produce weighed in the store).
Reply with ONLY a JSON object:
{"name": string|null, "weight": number|null, "weight_unit": "kg"|"g"|"lb"|"oz"|null,
 "price_per": number|null, "price_per_unit": "kg"|"100g"|"lb"|null, "total": number|null,
 "best_before": "YYYY-MM-DD"|null, "packed_on": "YYYY-MM-DD"|null}
- "name": the product as printed, readable English if you can (e.g. "Gouda cheese young").
- Numbers as printed, decimal point (Curaçao and Dutch labels print 1,25 for 1.25).
- "price_per": the unit price (per kg, per 100 g or per lb as printed); "total": the amount to pay.
- Dates: day first unless the label is clearly US style. Missing values: null."""


def ask_label(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), LABEL_INSTRUCTIONS, [
        {"type": "input_text", "text": f"Today is {date.today().isoformat()}. Read this label."},
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
         "detail": "high"},
    ], timeout=60)
    return extract_json(text)


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


def read_label(db: Session, household_id: str, data: bytes) -> dict:
    """{"name", "weight_kg", "price_per_kg", "total", "best_before", "packed_on"}: what the scale printed,
    in kilos. Missing parts are worked out from the others (weight = total / price per kg...)."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise ValueError("That file is not an image Kasita can read") from e
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    got = ask_label(db, household_id, buf.getvalue())
    w = _num(got.get("weight"))
    w = None if w is None else {"g": w / 1000, "lb": w * 0.453592, "oz": w * 0.0283495}.get(
        (got.get("weight_unit") or "kg").lower(), w)
    per = _num(got.get("price_per"))
    per = None if per is None else {"100g": per * 10, "lb": per / 0.453592}.get(
        (got.get("price_per_unit") or "kg").lower(), per)
    total = _num(got.get("total"))
    if w is None and per and total:
        w = total / per
    if per is None and w and total:
        per = total / w
    if total is None and w and per:
        total = w * per

    def day(v):
        try:
            return date.fromisoformat(str(v)[:10]).isoformat() if v else None
        except ValueError:
            return None
    return {"name": got.get("name"), "weight_kg": round(w, 3) if w else None,
            "price_per_kg": round(per, 2) if per else None, "total": round(total, 2) if total else None,
            "best_before": day(got.get("best_before")), "packed_on": day(got.get("packed_on"))}
