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
