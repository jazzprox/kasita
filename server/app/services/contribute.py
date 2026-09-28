"""Give back: add a product that no database knew to the Open Food Facts family.

Open Food Facts, Open Beauty Facts, Open Products Facts and Open Pet Food Facts
share one account system and the same write API (Product Opener). Contributions
go in under the household owner's own account (KASITA_OFF_USER_ID/_PASSWORD) and
become public under the Open Database Licence, which is the point.
"""
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import BarcodeCache, Product, ProductBarcode
from .barcodes import USER_AGENT

SITE_FOR = {"Personal care": "openbeautyfacts", "Household & cleaning": "openproductsfacts",
            "Pet": "openpetfoodfacts"}


class ContributeError(Exception):
    pass


def site_for(category: str | None) -> str:
    return SITE_FOR.get(category or "", "openfoodfacts")


def base_url(site: str) -> str:
    # KASITA_OFF_WRITE_HOST=openfoodfacts.net sends everything to the public staging server instead
    host = settings.off_write_host or f"{site}.org"
    return f"https://world.{host}"


def shareable_barcode(db: Session, product: Product) -> str | None:
    """A barcode of this product that no database knows yet (else None: nothing to give)."""
    for b in db.scalars(select(ProductBarcode).where(ProductBarcode.product_id == product.id)):
        hit = db.get(BarcodeCache, b.barcode)
        if not (hit and hit.found):
            return b.barcode
    return None


def _local_photo(image_url: str | None) -> Path | None:
    if not image_url or "/api/product-images/" not in image_url:
        return None
    household, name = image_url.split("/api/product-images/", 1)[1].split("/", 1)
    from .identify import product_images_dir
    path = product_images_dir(household) / name
    return path if path.is_file() else None


def contribute(db: Session, product: Product, client: httpx.Client | None = None) -> dict:
    if not (settings.off_user_id and settings.off_password):
        raise ContributeError("Open Food Facts isn't set up on this Kasita server yet (it needs a free OFF account)")
    code = shareable_barcode(db, product)
    if not code:
        raise ContributeError("Every barcode of this product is already in a product database")
    site = site_for(product.category)
    auth = {"user_id": settings.off_user_id, "password": settings.off_password}
    own = client is None
    client = client or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})
    try:
        r = client.post(f"{base_url(site)}/cgi/product_jqm2.pl", data={
            **auth, "code": code, "lang": "en", "product_name": product.name, "brands": product.brand or "",
            "categories": product.category or "", "comment": "Added with Kasita, a self-hosted pantry app"})
        if r.status_code != 200 or r.json().get("status") != 1:
            raise ContributeError(f"{site} did not accept it: {r.text[:160]}")
        photo = _local_photo(product.image_url)
        if photo:
            img = client.post(f"{base_url(site)}/cgi/product_image_upload.pl",
                              data={**auth, "code": code, "imagefield": "front_en"},
                              files={"imgupload_front_en": (photo.name, photo.read_bytes(), "image/jpeg")})
            if img.status_code != 200:
                raise ContributeError(f"The product was added, but the photo upload failed ({img.status_code})")
    except httpx.HTTPError as e:
        raise ContributeError(f"{site} could not be reached") from e
    finally:
        if own:
            client.close()
    # our own cache now knows it too, from the source it will be found in
    row = db.get(BarcodeCache, code) or BarcodeCache(barcode=code)
    row.found, row.source, row.name, row.brand = True, site, product.name, product.brand
    row.categories = product.category
    db.merge(row)
    db.commit()
    return {"site": site, "barcode": code, "photo": bool(_local_photo(product.image_url)),
            "url": f"https://world.{site}.org/product/{code}"}
