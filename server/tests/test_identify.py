import io

from PIL import Image

from app.services import identify as ident


def photo():
    buf = io.BytesIO()
    Image.new("RGB", (1600, 2000), "orange").save(buf, "JPEG")
    return buf.getvalue()


def test_photo_is_identified_and_kept_as_picture(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(ident, "ask_chatgpt", lambda db, hh, jpeg: {
        "name": "Roland unseasoned rice vinegar 500 ml", "brand": "Roland", "size": "500 ml",
        "category": "Pantry", "readable": True})
    r = client.post(f"/api/households/{hid}/products/identify", headers=h,
                    files={"file": ("p.jpg", photo(), "image/jpeg")})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["found"] and out["name"].startswith("Roland") and out["category"] == "Pantry"
    assert out["quantity_text"] == "500 ml"
    # the picture is served without a login (random name), shrunk to 1000 px
    path = out["image_url"].split("kasita.jazzproxy.com", 1)[-1] if "jazzproxy" in out["image_url"] \
        else "/" + out["image_url"].split("/", 3)[3]
    img = client.get(path)
    assert img.status_code == 200 and max(Image.open(io.BytesIO(img.content)).size) == 1000
    assert client.get(path.replace(path[-10:-4], "000000")).status_code == 404
    assert client.get(f"/api/product-images/{hid}/../../etc/passwd").status_code == 404


def test_unknown_category_is_guessed_and_unreadable_photo_says_so(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(ident, "ask_chatgpt", lambda db, hh, jpeg: {"name": "Goisco toilet paper 12 rolls",
                                                                    "category": "Paper goods"})
    out = client.post(f"/api/households/{hid}/products/identify", headers=h,
                      files={"file": ("p.jpg", photo(), "image/jpeg")}).json()
    assert out["category"] == "Household & cleaning"
    monkeypatch.setattr(ident, "ask_chatgpt", lambda db, hh, jpeg: {"readable": False})
    out = client.post(f"/api/households/{hid}/products/identify", headers=h,
                      files={"file": ("p.jpg", photo(), "image/jpeg")}).json()
    assert out["found"] is False and out["image_url"]


def test_identify_needs_login(client, jazz):
    _, hid = jazz
    assert client.post(f"/api/households/{hid}/products/identify",
                       files={"file": ("p.jpg", photo(), "image/jpeg")}).status_code == 401


def test_retake_and_remove_product_photo(client, jazz, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    h, hid = jazz
    base = f"/api/households/{hid}"
    pid = client.post(f"{base}/products", json={"name": "Dove"}, headers=h).json()["id"]
    first = client.post(f"{base}/products/{pid}/photo", headers=h, files={"file": ("a.jpg", photo(), "image/jpeg")}).json()
    first_path = "/" + first["image_url"].split("/", 3)[3]
    assert client.get(first_path).status_code == 200
    second = client.post(f"{base}/products/{pid}/photo", headers=h, files={"file": ("b.jpg", photo(), "image/jpeg")}).json()
    assert second["image_url"] != first["image_url"]
    assert client.get(first_path).status_code == 404            # the old picture is gone from disk
    gone = client.delete(f"{base}/products/{pid}/photo", headers=h).json()
    assert gone["image_url"] is None
    # an Open Food Facts picture is only a link: removing it deletes nothing
    client.patch(f"{base}/products/{pid}", json={"image_url": "https://images.openfoodfacts.org/x.jpg"}, headers=h)
    assert client.delete(f"{base}/products/{pid}/photo", headers=h).json()["image_url"] is None


def test_photo_source_and_restoring_the_database_photo(client, jazz, tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    h, hid = jazz
    base = f"/api/households/{hid}"
    db_pic = "https://images.openfoodfacts.org/images/products/544/900/000/0996/front_en.jpg"
    p = client.post(f"{base}/products", json={"name": "Coca-Cola", "image_url": db_pic}, headers=h).json()
    assert p["photo_source"] == "database" and p["can_restore_photo"] is False
    mine = client.post(f"{base}/products/{p['id']}/photo", headers=h, files={"file": ("a.jpg", photo(), "image/jpeg")}).json()
    assert mine["photo_source"] == "yours" and mine["can_restore_photo"] is True
    back = client.post(f"{base}/products/{p['id']}/photo/restore", headers=h).json()
    assert back["image_url"] == db_pic and back["photo_source"] == "database" and back["can_restore_photo"] is False
    assert client.get("/" + mine["image_url"].split("/", 3)[3]).status_code == 404   # my photo cleaned up
    gone = client.delete(f"{base}/products/{p['id']}/photo", headers=h).json()
    assert gone["photo_source"] is None and gone["can_restore_photo"] is True       # removed, still restorable
    plain = client.post(f"{base}/products", json={"name": "Garlic"}, headers=h).json()
    assert client.post(f"{base}/products/{plain['id']}/photo/restore", headers=h).status_code == 409
