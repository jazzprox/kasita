import io
from datetime import date, timedelta

import httpx
from PIL import Image

from app.config import settings
from app.db import SessionLocal
from app.models import BarcodeCache, Product
from app.services import contribute as contrib
from app.services import cook
from app.services import identify as ident


def test_cook_sends_pantry_with_expiry_and_cleans_answer(client, jazz, monkeypatch):
    h, hid = jazz
    base = f"/api/households/{hid}"
    pid = client.post(f"{base}/products", json={"name": "Chicken wings"}, headers=h).json()["id"]
    client.post(f"{base}/stock/purchase", json={"product_id": pid, "quantity": 6,
                                                "best_before": (date.today() + timedelta(days=1)).isoformat()},
                headers=h)
    seen = {}

    def fake(db, hh, prompt):
        seen["prompt"] = prompt
        return {"ideas": [{"title": "BBQ wings", "minutes": 35, "uses": ["Chicken wings"], "missing": ["lime"],
                           "steps": ["Season", "Bake"], "why": "the wings expire tomorrow"}, {"no": "title"}]}

    monkeypatch.setattr(cook, "ask_chatgpt", fake)
    r = client.post(f"{base}/cook", json={"note": "quick"}, headers=h).json()
    assert "Chicken wings (6 pcs), expires in 1 days" in seen["prompt"] and "Wishes: quick" in seen["prompt"]
    assert [i["title"] for i in r["ideas"]] == ["BBQ wings"] and r["ideas"][0]["missing"] == ["lime"]


def test_cook_with_empty_pantry_does_not_ask(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(cook, "ask_chatgpt", lambda *a: (_ for _ in ()).throw(AssertionError("asked")))
    assert client.post(f"/api/households/{hid}/cook", json={}, headers=h).json() == {"ideas": [], "pantry": 0}


def test_contribute_product_with_photo(client, jazz, monkeypatch, tmp_path):
    h, hid = jazz
    base = f"/api/households/{hid}"
    monkeypatch.setattr(settings, "off_user_id", "jazz")
    monkeypatch.setattr(settings, "off_password", "pw")
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), "gold").save(buf, "JPEG")
    name, _ = ident.store_photo(hid, buf.getvalue())
    photo_url = f"https://kasita.example/api/product-images/{hid}/{name}"
    p = client.post(f"{base}/products", json={"name": "Roland rice vinegar 500 ml", "brand": "Roland",
                                              "category": "Pantry", "image_url": photo_url,
                                              "barcodes": ["041224705272"]}, headers=h).json()
    assert p["shareable"] is True
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.url.host, req.url.path, req.content))
        return httpx.Response(200, json={"status": 1, "status_verbose": "fields saved"})

    with SessionLocal() as db:
        out = contrib.contribute(db, db.get(Product, p["id"]), client=httpx.Client(transport=httpx.MockTransport(handler)))
        assert out["site"] == "openfoodfacts" and out["photo"] is True
        assert db.get(BarcodeCache, "041224705272").found is True
    (host1, path1, body1), (host2, path2, body2) = calls
    assert host1 == "world.openfoodfacts.org" and path1 == "/cgi/product_jqm2.pl"
    assert b"product_name=Roland+rice+vinegar+500+ml" in body1 and b"user_id=jazz" in body1
    assert path2 == "/cgi/product_image_upload.pl" and b'name="imgupload_front_en"' in body2
    # now known: nothing left to give, and the button goes away
    assert client.get(f"{base}/products/{p['id']}", headers=h).json()["shareable"] is False
    assert client.post(f"{base}/products/{p['id']}/contribute", headers=h).status_code == 409


def test_contribute_routing_and_setup():
    assert contrib.site_for("Personal care") == "openbeautyfacts"
    assert contrib.site_for("Household & cleaning") == "openproductsfacts"
    assert contrib.site_for("Pet") == "openpetfoodfacts"
    assert contrib.site_for("Drinks") == "openfoodfacts" and contrib.site_for(None) == "openfoodfacts"


def test_contribute_needs_an_account(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(settings, "off_user_id", "")
    p = client.post(f"/api/households/{hid}/products", json={"name": "X", "barcodes": ["041224705272"]},
                    headers=h).json()
    r = client.post(f"/api/households/{hid}/products/{p['id']}/contribute", headers=h)
    assert r.status_code == 409 and "set up" in r.json()["detail"]
