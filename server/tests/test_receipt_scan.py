"""Department receipts (small shops print "COMESTIBELS 7.99", not products): scan a pack to say
what a line was, scan a whole bag at once, spending only, and never remembering a department."""
from decimal import Decimal

import pytest

from app.services import departments
from app.services import receipts as receipts_svc
from tests.conftest import FAKE_DB
from tests.test_receipts import upload

# the real receipt that started this (Guonsheng Minimarket); the AI flags some lines, the words catch the rest
GUONSHENG = {
    "store": "Guonsheng Minimarket", "date": "2026-09-30", "currency": "XCG", "total": 37.79,
    "lines": [
        {"text": "FRUTA / BERDURA", "name": "Fruit and vegetables", "quantity": 1, "line_total": 7.25,
         "kind": "department"},
        {"text": "AROS / BONCHI", "name": "Rice and beans", "quantity": 1, "line_total": 2.46, "kind": "department"},
        {"text": "COMESTIBELS", "name": "Groceries", "quantity": 1, "line_total": 5.35, "kind": "item"},
        {"text": "COMESTIBELS", "name": "Groceries", "quantity": 1, "line_total": 7.99, "kind": "item"},
        {"text": "COMESTIBELS", "name": "Groceries", "quantity": 1, "line_total": 7.99, "kind": "item"},
        {"text": "WEBU / ARINA", "name": "Eggs and flour", "quantity": 1, "line_total": 6.75, "kind": "item"},
    ],
}

EGGS, COOKIES, RICE, MYSTERY = "8712345678906", "7501234567893", "0123456789012", "99887766"


@pytest.fixture
def gs(monkeypatch):
    parsed = {"value": GUONSHENG}
    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", lambda db, hid, jpeg: parsed["value"])
    monkeypatch.setitem(FAKE_DB, EGGS, {"source": "openfoodfacts", "name": "Large eggs", "brand": "Farm",
                                        "quantity_text": "12", "image_url": "https://img/eggs.jpg",
                                        "categories": "Eggs"})
    monkeypatch.setitem(FAKE_DB, COOKIES, {"source": "openfoodfacts", "name": "Maria cookies", "brand": "Gamesa",
                                           "quantity_text": "170 g", "image_url": None, "categories": "Biscuits"})
    return parsed


def _r(client, h, hid, rid):
    return client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()


def test_department_words():
    for text in ("FRUTA / BERDURA", "AROS / BONCHI", "WEBU / ARINA", "COMESTIBELS", "FRUTAS Y VERDURAS",
                 "DEPT 03", "Groente & Fruit"):
        assert departments.is_department_text(text), text
    for text in ("LECHI KRIOYO 1L", "ARROZ BLANCO 5LB", "BANANA", "COCA COLA 330", "PAN DULCE", "12345"):
        assert not departments.is_department_text(text), text
    assert departments.default_category("FRUTA / BERDURA") == "Produce"
    assert departments.default_category("AROS / BONCHI") == "Pantry"
    assert departments.likely_categories("WEBU / ARINA")[:2] == ["Dairy & eggs", "Pantry"]
    assert departments.default_category("COMESTIBELS") == "Pantry"


def test_department_lines_are_flagged_and_not_linked(client, jazz, gs):
    h, hid = jazz
    # a product whose name a guess would happily match
    client.post(f"/api/households/{hid}/products", json={"name": "Comestibels"}, headers=h)
    lines = _r(client, h, hid, upload(client, h, hid))["lines"]
    assert all(ln["department"] for ln in lines)
    assert all(ln["product_id"] is None for ln in lines)
    assert [ln["suggested_category"] for ln in lines] == ["Produce", "Pantry", "Pantry", "Pantry", "Pantry",
                                                          "Dairy & eggs"]


def test_scan_a_line_known_database_and_unknown(client, jazz, gs):
    h, hid = jazz
    rid = upload(client, h, hid)
    lines = _r(client, h, hid, rid)["lines"]
    base = f"/api/households/{hid}/receipts/{rid}/lines"

    # known to the household: linked
    rice = client.post(f"/api/households/{hid}/products", json={"name": "Rice", "barcodes": [RICE]}, headers=h).json()
    out = client.post(f"{base}/{lines[1]['id']}/scan", headers=h, json={"barcode": RICE}).json()
    assert out["status"] == "known" and out["product"]["id"] == rice["id"] and out["line_id"] == lines[1]["id"]
    line = out["receipt"]["lines"][1]
    assert line["product_name"] == "Rice" and line["matched_by"] == "scan" and line["raw_text"] == "AROS / BONCHI"

    # in a product database: the product is made from it, no form
    out = client.post(f"{base}/{lines[5]['id']}/scan", headers=h, json={"barcode": EGGS}).json()
    assert out["status"] == "created"
    p = out["product"]
    assert p["name"] == "Large eggs 12" and p["brand"] == "Farm" and p["category"] == "Dairy & eggs"
    assert p["barcodes"] == [EGGS] and p["image_url"] == "https://img/eggs.jpg" and p["photo_source"] == "database"
    assert out["receipt"]["lines"][5]["product_id"] == p["id"]

    # nobody knows it: the app asks, then sends the product it chose or made
    out = client.post(f"{base}/{lines[0]['id']}/scan", headers=h, json={"barcode": MYSTERY}).json()
    assert out["status"] == "unknown" and out["lookup"]["found"] is False and out["lookup"]["barcode"] == MYSTERY
    assert out["receipt"]["lines"][0]["product_id"] is None
    mango = client.post(f"/api/households/{hid}/products", json={"name": "Mango", "barcodes": [MYSTERY]},
                        headers=h).json()
    out = client.post(f"{base}/{lines[0]['id']}/scan", headers=h, json={"product_id": mango["id"]}).json()
    assert out["status"] == "linked" and out["receipt"]["lines"][0]["product_name"] == "Mango"

    assert client.post(f"{base}/{lines[2]['id']}/scan", headers=h, json={"barcode": "x1"}).status_code == 422


def _price_history(client, h, hid, pid, price, store="Guonsheng Minimarket"):
    stores = {s["name"]: s["id"] for s in client.get(f"/api/households/{hid}/stores", headers=h).json()}
    sid = stores.get(store) or client.post(f"/api/households/{hid}/stores", json={"name": store}, headers=h).json()["id"]
    client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                json={"product_id": pid, "quantity": 1, "unit_price": price, "store_id": sid})


def test_scan_them_all_picks_by_price_then_twin(client, jazz, gs):
    h, hid = jazz
    oil = client.post(f"/api/households/{hid}/products", json={"name": "Cooking oil", "category": "Pantry",
                                                                "barcodes": ["4006381333931"]}, headers=h).json()
    _price_history(client, h, hid, oil["id"], 7.99)
    rid = upload(client, h, hid)
    url = f"/api/households/{hid}/receipts/{rid}/scan"
    first = client.post(url, headers=h, json={"barcode": "4006381333931"}).json()
    lines = first["receipt"]["lines"]
    assert first["status"] == "known" and first["reason"] == "same price as last time"
    assert first["line_id"] == lines[3]["id"]  # the first 7.99 COMESTIBELS, not the 5.35 one before it
    second = client.post(url, headers=h, json={"barcode": "4006381333931"}).json()
    assert second["line_id"] == lines[4]["id"]  # its twin


def test_scan_them_all_department_affinity(client, jazz, gs):
    h, hid = jazz
    rid = upload(client, h, hid)
    url = f"/api/households/{hid}/receipts/{rid}/scan"
    eggs = client.post(url, headers=h, json={"barcode": EGGS}).json()
    assert eggs["status"] == "created"
    assert eggs["line_id"] == eggs["receipt"]["lines"][5]["id"]  # WEBU / ARINA, the last line
    assert eggs["reason"] == "Dairy & eggs fits this department"
    banana = client.post(f"/api/households/{hid}/products", json={"name": "Bananas", "category": "Produce",
                                                                   "barcodes": ["20012345"]}, headers=h).json()
    out = client.post(url, headers=h, json={"barcode": "20012345"}).json()
    assert out["product"]["id"] == banana["id"] and out["line_id"] == out["receipt"]["lines"][0]["id"]


def test_move_undo_and_duplicates(client, jazz, gs):
    h, hid = jazz
    rid = upload(client, h, hid)
    url = f"/api/households/{hid}/receipts/{rid}"
    first = client.post(f"{url}/scan", headers=h, json={"barcode": COOKIES}).json()
    lines = first["receipt"]["lines"]
    assert first["line_id"] == lines[2]["id"]  # snacks fit COMESTIBELS; the first one is 5.35
    # wrong line: move it to the 7.99 one
    r = client.post(f"{url}/lines/{lines[2]['id']}/move", headers=h, json={"to_line_id": lines[3]["id"]}).json()
    assert r["lines"][2]["product_id"] is None and r["lines"][3]["product_id"] == first["product"]["id"]
    # the same pack again goes on the other 7.99 line
    second = client.post(f"{url}/scan", headers=h, json={"barcode": COOKIES}).json()
    assert second["line_id"] == lines[4]["id"]
    assert second["reason"] == "same text and price as the one you just scanned"
    # undo = unlink the line
    client.patch(f"{url}/lines/{lines[4]['id']}", headers=h, json={"clear_product": True})
    assert _r(client, h, hid, rid)["lines"][4]["product_id"] is None
    assert client.post(f"{url}/lines/{lines[4]['id']}/move", headers=h,
                       json={"to_line_id": lines[0]["id"]}).status_code == 409


def test_no_open_line_left(client, jazz, gs):
    h, hid = jazz
    rid = upload(client, h, hid)
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    for ln in _r(client, h, hid, rid)["lines"]:
        client.patch(f"{base}/{ln['id']}", headers=h, json={"spending_only": True})
    out = client.post(f"/api/households/{hid}/receipts/{rid}/scan", headers=h, json={"barcode": EGGS}).json()
    assert out["status"] == "no_line" and out["line_id"] is None and out["product"]["name"] == "Large eggs 12"


def test_spending_only_counts_but_makes_no_stock(client, jazz, gs):
    h, hid = jazz
    gs["value"] = {**GUONSHENG, "lines": GUONSHENG["lines"] + [
        {"text": "BAG", "name": "Bag", "quantity": 1, "line_total": 0.50, "kind": "fee"}]}
    rid = upload(client, h, hid)
    lines = _r(client, h, hid, rid)["lines"]
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    fruit = client.patch(f"{base}/{lines[0]['id']}", headers=h, json={"spending_only": True}).json()
    assert fruit["spending_only"] and fruit["spending_category"] == "Produce" and fruit["product_id"] is None
    client.patch(f"{base}/{lines[1]['id']}", headers=h, json={"spending_only": True, "spending_category": "Other"})
    client.post(f"/api/households/{hid}/receipts/{rid}/scan", headers=h, json={"barcode": EGGS})  # WEBU / ARINA

    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).json()
    # eggs to the pantry; fruit and rice by hand, the three unscanned COMESTIBELS as spending only; bag skipped
    assert c == {"added": 1, "created_products": 0, "skipped": 1, "spending_only": 5}
    stock = {s["product"]["name"] for s in client.get(f"/api/households/{hid}/stock", headers=h).json()}
    assert stock == {"Large eggs 12"}
    names = {p["name"] for p in client.get(f"/api/households/{hid}/products", headers=h).json()}
    assert names == {"Large eggs 12"}, "departments never become products"

    s = client.get(f"/api/households/{hid}/stock/spending?days=7", headers=h).json()
    cats = {c["name"]: Decimal(str(c["amount"])) for c in s["by_category"]}
    assert cats["Produce"] == Decimal("7.25") and cats["Other"] == Decimal("2.46")
    assert cats["Pantry"] == Decimal("21.33") and cats["Dairy & eggs"] == Decimal("6.75")
    assert Decimal(str(s["total"])) == Decimal("37.79"), "everything but the skipped bag"
    assert s["by_store"][0]["name"] == "Guonsheng Minimarket"
    assert Decimal(str(client.get(f"/api/households/{hid}/stock/month", headers=h).json()["spent"])) == Decimal("37.79")


def test_departments_are_never_remembered(client, jazz, gs):
    h, hid = jazz
    rid = upload(client, h, hid)
    url = f"/api/households/{hid}/receipts/{rid}"
    lines = _r(client, h, hid, rid)["lines"]
    client.post(f"{url}/lines/{lines[2]['id']}/scan", headers=h, json={"barcode": COOKIES})
    client.post(f"{url}/confirm", headers=h, json={})
    from app.db import SessionLocal
    from app.models import ReceiptAlias
    with SessionLocal() as db:
        assert db.query(ReceiptAlias).count() == 0
    again = _r(client, h, hid, upload(client, h, hid))["lines"]
    assert again[2]["department"] and again[2]["product_id"] is None


SHOP = {"store": "Toko Kim", "date": "2026-09-30", "currency": "XCG", "total": 10,
        "lines": [{"text": "TK SPECIAL", "name": "Special", "quantity": 1, "line_total": 3, "kind": "item"},
                  {"text": "TK SPECIAL", "name": "Special", "quantity": 1, "line_total": 4, "kind": "item"},
                  {"text": "COCA COLA 330", "name": "Coca-Cola 330 ml", "quantity": 1, "line_total": 3,
                   "kind": "item"}]}


def test_store_learns_a_department_from_different_products(client, jazz, gs):
    h, hid = jazz
    gs["value"] = SHOP
    rid = upload(client, h, hid)
    lines = _r(client, h, hid, rid)["lines"]
    assert not any(ln["department"] for ln in lines)
    base = f"/api/households/{hid}/receipts/{rid}/lines"
    a = client.post(f"/api/households/{hid}/products", json={"name": "Peanuts"}, headers=h).json()
    b = client.post(f"/api/households/{hid}/products", json={"name": "Chips"}, headers=h).json()
    client.patch(f"{base}/{lines[0]['id']}", headers=h, json={"product_id": a["id"]})
    client.patch(f"{base}/{lines[1]['id']}", headers=h, json={"product_id": b["id"]})
    client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={})

    again = _r(client, h, hid, upload(client, h, hid))["lines"]
    assert again[0]["department"] and again[0]["product_id"] is None
    assert again[1]["department"]
    # a real product name still links from memory
    assert not again[2]["department"] and again[2]["matched_by"] == "alias"

    # another store has not learned it
    gs["value"] = {**SHOP, "store": "Other shop"}
    other = _r(client, h, hid, upload(client, h, hid))["lines"]
    assert not other[0]["department"]


def test_not_a_department_is_remembered(client, jazz, gs):
    h, hid = jazz
    gs["value"] = {**SHOP, "lines": [{"text": "FRUTA", "name": "Fruit", "quantity": 1, "line_total": 3,
                                      "kind": "item"}]}
    rid = upload(client, h, hid)
    line = _r(client, h, hid, rid)["lines"][0]
    assert line["department"]
    apples = client.post(f"/api/households/{hid}/products", json={"name": "Apples"}, headers=h).json()
    client.patch(f"/api/households/{hid}/receipts/{rid}/lines/{line['id']}", headers=h,
                 json={"department": False, "product_id": apples["id"]})
    client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={})
    again = _r(client, h, hid, upload(client, h, hid))["lines"][0]
    assert not again["department"] and again["product_id"] == apples["id"] and again["matched_by"] == "alias"
