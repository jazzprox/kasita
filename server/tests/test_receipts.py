import io
from decimal import Decimal

import pytest
from PIL import Image

from app.services import chatgpt, codex
from app.services import receipts as receipts_svc

PARSED = {
    "store": "Centrum Piscadera", "date": "2026-09-20", "currency": "XCG", "total": 23.45,
    "lines": [
        {"text": "GSC TOILET PPR 12R", "name": "Goisco toilet paper 12 rolls", "quantity": 1, "unit_price": 12.95,
         "line_total": 12.95, "kind": "item"},
        {"text": "MILK WHL 1L", "name": "Whole milk 1 L", "quantity": 2, "unit_price": None, "line_total": 9.50,
         "kind": "item"},
        {"text": "BAG FEE", "name": "Bag", "quantity": 1, "unit_price": 1.00, "line_total": 1.00, "kind": "fee"},
    ],
}


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 3000), "white").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def ai(monkeypatch):
    calls = []

    def fake(db, household_id, jpeg):
        calls.append(len(jpeg))
        return PARSED

    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", fake)
    return calls


def upload(client, h, hid):
    r = client.post(f"/api/households/{hid}/receipts", headers=h,
                    files={"file": ("r.jpg", photo(), "image/jpeg")})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_receipt_read_review_confirm_and_learn(client, jazz, ai):
    h, hid = jazz
    milk = client.post(f"/api/households/{hid}/products", json={"name": "Whole milk", "unit": "pcs"}, headers=h).json()
    rid = upload(client, h, hid)
    r = client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()
    assert r["status"] == "parsed" and r["store_name"] == "Centrum Piscadera"
    assert r["purchased_on"] == "2026-09-20" and Decimal(r["total"]) == Decimal("23.45")
    paper, milk_line, bag = r["lines"]
    assert paper["product_id"] is None
    assert milk_line["product_id"] == milk["id"] and milk_line["matched_by"] == "guess"
    assert Decimal(milk_line["unit_price"]) == Decimal("4.75")
    assert bag["skip"] is True

    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={})
    assert c.status_code == 200, c.text
    assert c.json() == {"added": 2, "created_products": 1, "skipped": 1}
    # store created from the receipt, milk stock and price history recorded
    stores = client.get(f"/api/households/{hid}/stores", headers=h).json()
    assert [s["name"] for s in stores] == ["Centrum Piscadera"]
    stock = {s["product"]["name"]: Decimal(s["total"]) for s in client.get(f"/api/households/{hid}/stock", headers=h).json()}
    assert stock == {"Whole milk": 2, "Goisco toilet paper 12 rolls": 1}
    prices = client.get(f"/api/households/{hid}/products/{milk['id']}/prices", headers=h).json()
    assert Decimal(prices[0]["unit_price"]) == Decimal("4.75") and prices[0]["store_name"] == "Centrum Piscadera"
    # booked receipts are frozen
    assert client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).status_code == 409

    # the next receipt from this store matches both lines by what was learned
    rid2 = upload(client, h, hid)
    lines = client.get(f"/api/households/{hid}/receipts/{rid2}", headers=h).json()["lines"]
    assert [ln["matched_by"] for ln in lines[:2]] == ["alias", "alias"]
    assert lines[1]["product_id"] == milk["id"]


def test_review_edits(client, jazz, ai):
    h, hid = jazz
    rid = upload(client, h, hid)
    lines = client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()["lines"]
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    assert client.patch(f"{base}/{lines[0]['id']}", headers=h, json={"skip": True}).json()["skip"] is True
    assert client.delete(f"{base}/{lines[2]['id']}", headers=h).status_code == 204
    r = client.post(base, headers=h, json={"raw_text": "BANANA", "quantity": 1.25, "line_total": 3.10}).json()
    assert r["line_count"] == 3
    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).json()
    assert c == {"added": 2, "created_products": 2, "skipped": 1}
    banana = [p for p in client.get(f"/api/households/{hid}/products", headers=h).json() if p["name"] == "Banana"][0]
    assert banana["unit"] == "kg"


def test_failed_read_is_reported(client, jazz, monkeypatch):
    h, hid = jazz

    def broken(db, household_id, jpeg):
        raise codex.CodexError("ChatGPT is not connected. Connect it under More → ChatGPT.")

    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", broken)
    rid = upload(client, h, hid)
    r = client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()
    assert r["status"] == "failed" and "not connected" in r["error"]
    assert client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).status_code == 409
    assert client.get(f"/api/households/{hid}/receipts/{rid}/image", headers=h).status_code == 200


def test_not_an_image(client, jazz, ai):
    h, hid = jazz
    r = client.post(f"/api/households/{hid}/receipts", headers=h, files={"file": ("x.jpg", b"nope", "image/jpeg")})
    assert r.status_code == 422


def test_receipts_are_private_to_household(client, jazz, ai):
    from tests.conftest import login, make_user
    h, hid = jazz
    rid = upload(client, h, hid)
    other = login(client, *make_user(email="other@example.com"))
    assert client.get(f"/api/households/{hid}/receipts/{rid}", headers=other).status_code == 404


def test_extract_json_tolerates_fences():
    assert receipts_svc.extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_chatgpt_device_flow_stores_encrypted_tokens(client, jazz, monkeypatch):
    h, hid = jazz
    base = f"/api/households/{hid}/integrations/chatgpt"
    assert client.get(base, headers=h).json()["connected"] is False
    monkeypatch.setattr(codex, "request_device_code", lambda: {
        "device_auth_id": "dev-1", "user_code": "ABCD-EFGH", "interval": 5, "started_at": __import__("time").time()})
    approved = {"yes": False}
    monkeypatch.setattr(codex, "poll_device_code", lambda d, u: ("auth-code", "verifier") if approved["yes"] else None)
    monkeypatch.setattr(codex, "exchange_code", lambda c, v: codex.Secret(
        refresh_token="rt-secret", account_id="acc", access_token="at", expires_at=2**40, email="me@x.com", plan="plus"))
    monkeypatch.setattr(codex, "list_models", lambda s: ["gpt-5.4-mini", "gpt-5.6"])

    s = client.post(f"{base}/connect", headers=h).json()
    assert s["pending"]["user_code"] == "ABCD-EFGH" and s["connected"] is False
    assert client.post(f"{base}/poll", headers=h).json()["connected"] is False
    approved["yes"] = True
    s = client.post(f"{base}/poll", headers=h).json()
    assert s["connected"] and s["model"] == "gpt-5.6" and s["email"] == "me@x.com" and s["pending"] is None

    from app.db import SessionLocal
    with SessionLocal() as db:
        row = chatgpt.get(db, hid)
        assert "rt-secret" not in str(row.data)  # encrypted at rest
        assert chatgpt.fresh_secret(db, hid).refresh_token == "rt-secret"
    assert client.delete(base, headers=h).status_code == 204
    assert client.get(base, headers=h).json()["connected"] is False


def test_only_owner_connects_chatgpt(client, jazz):
    h, hid = jazz
    url = client.post(f"/api/households/{hid}/invites", headers=h).json()["url"]
    r = client.post("/api/auth/accept-invite", json={"token": url.rsplit("/", 1)[1], "email": "m@example.com",
                                                      "password": "another-long-password", "name": "M"})
    assert r.status_code == 200, r.text
    m = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.post(f"/api/households/{hid}/integrations/chatgpt/connect", headers=m).status_code == 403
    assert client.get(f"/api/households/{hid}/integrations/chatgpt", headers=m).status_code == 200


def test_migrations_match_models(tmp_path, monkeypatch):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from app import migrate
    from app.db import Base
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    monkeypatch.setattr(migrate, "engine", eng)
    migrate.migrate()
    with eng.connect() as conn:
        assert compare_metadata(MigrationContext.configure(conn), Base.metadata) == []


def jpeg(w, h, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def test_long_receipt_in_parts_becomes_one_strip(client, jazz, ai):
    h, hid = jazz
    files = [("file", ("top.jpg", jpeg(900, 1200), "image/jpeg")),
             ("file", ("bottom.jpg", jpeg(1000, 1300, "gray"), "image/jpeg"))]
    r = client.post(f"/api/households/{hid}/receipts", headers=h, files=files)
    assert r.status_code == 201, r.text
    img = Image.open(io.BytesIO(client.get(f"/api/households/{hid}/receipts/{r.json()['id']}/image", headers=h).content))
    # both parts at the narrower width, stacked with a 16 px bar between them
    assert img.width == 900 and img.height == 1200 + round(1300 * 900 / 1000) + 16
    assert client.get(f"/api/households/{hid}/receipts/{r.json()['id']}", headers=h).json()["status"] == "parsed"


def test_panorama_keeps_width_and_is_read_in_overlapping_sections():
    import app.services.receipts as svc
    import tempfile
    from app.config import settings
    settings.upload_dir = tempfile.mkdtemp()
    path = svc.store_image("hh", jpeg(1000, 6000))
    strip = open(path, "rb").read()
    assert Image.open(io.BytesIO(strip)).size == (1000, 6000)  # not shrunk to 400 x 2400
    parts = [Image.open(io.BytesIO(p)) for p in svc.sections(strip)]
    assert len(parts) == 6 and all(p.size == (1000, 1300) for p in parts)
    # a normal photo stays one image, and a very tall one still fits in 10 sections
    assert len(svc.sections(jpeg(1500, 2000))) == 1
    assert len(svc.sections(jpeg(500, 19000))) <= 10


def test_sections_are_explained_to_the_model(client, jazz, monkeypatch):
    import app.services.receipts as svc
    from app.services import chatgpt, codex
    seen = {}
    monkeypatch.setattr(chatgpt, "fresh_secret", lambda db, hid: object())
    monkeypatch.setattr(chatgpt, "model_for", lambda db, hid: "m")

    def fake_respond(secret, model, instructions, content, **kw):
        seen["content"] = content
        return '{"store": "X", "lines": []}'

    monkeypatch.setattr(codex, "respond", fake_respond)
    h, hid = jazz
    from app.db import SessionLocal
    with SessionLocal() as db:
        svc.read_with_chatgpt(db, hid, jpeg(1000, 6000))
    images = [c for c in seen["content"] if c["type"] == "input_image"]
    assert len(images) == 6 and "SAME line" in seen["content"][0]["text"]


def test_two_lines_of_the_same_thing_make_one_product(client, jazz, ai):
    """A shop rings two of the same item up as two lines, not one line of two.

    A real receipt printed PINEAPPLE CHUNKS twice (at different prices, 8.62
    and 7.89) and made two products with the same name. Aliases are matched
    when a receipt is PARSED and only written after it is confirmed, so the
    second line could never see what the first had just created. Everything
    downstream then treats the pair as different things: stock is split, the
    shopping list offers both, and a barcode — unique per household — can
    only be attached to one of them.
    """
    h, hid = jazz
    rid = upload(client, h, hid)
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    lines = client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()["lines"]
    for ln in lines:  # start from a clean receipt, then add the pair
        client.delete(f"{base}/{ln['id']}", headers=h)
    client.post(base, headers=h, json={"raw_text": "PINEAPPLE CHUNKS", "quantity": 1, "line_total": 8.62})
    client.post(base, headers=h, json={"raw_text": "PINEAPPLE CHUNKS", "quantity": 1, "line_total": 7.89})

    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).json()
    assert c["added"] == 2, "both lines are still booked"
    assert c["created_products"] == 1, "but they share ONE product"

    named = [p for p in client.get(f"/api/households/{hid}/products", headers=h).json()
             if p["name"].lower() == "pineapple chunks"]
    assert len(named) == 1

    # Both quantities land on it, and both prices are kept.
    stock = {s["product"]["name"]: Decimal(s["total"])
             for s in client.get(f"/api/households/{hid}/stock", headers=h).json()}
    assert stock["Pineapple Chunks"] == 2
    prices = client.get(f"/api/households/{hid}/products/{named[0]['id']}/prices", headers=h).json()
    assert sorted(Decimal(p["unit_price"]) for p in prices) == [Decimal("7.89"), Decimal("8.62")]


def test_different_names_still_make_different_products(client, jazz, ai):
    """The guard keys on the text, so it must not merge things that differ."""
    h, hid = jazz
    rid = upload(client, h, hid)
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    for ln in client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()["lines"]:
        client.delete(f"{base}/{ln['id']}", headers=h)
    client.post(base, headers=h, json={"raw_text": "PINEAPPLE CHUNKS", "quantity": 1, "line_total": 8.62})
    client.post(base, headers=h, json={"raw_text": "PINEAPPLE RINGS", "quantity": 1, "line_total": 7.89})
    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).json()
    assert c["created_products"] == 2
