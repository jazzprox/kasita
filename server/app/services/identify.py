"""Name a product from a photo of its pack, with the household's ChatGPT.

For barcodes no database knows (local brands like Goisco, imports nobody has
entered): the person photographs the front, ChatGPT reads the label, and the
New-product form opens pre-filled. The photo is kept as the product's picture
under a random name, served without login like the Open Food Facts images are.
"""
import base64
import io
import uuid
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
