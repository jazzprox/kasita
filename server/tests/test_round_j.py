"""Round J: pack sizes + per kg, deli barcodes and labels, nutrition, recipe import, MCP."""
from decimal import Decimal

import pytest

from app.services import barcodes, identify, recipe_import, sizes
from tests.conftest import FAKE_DB


def test_parse_size():
    assert sizes.parse_size("1.5 l") == (Decimal("1500.000"), "ml")
    assert sizes.parse_size("6 x 330 ml") == (Decimal("1980.000"), "ml")
    assert sizes.parse_size("GSC TOILET PPR 12R") == (Decimal("12.000"), "pcs")
    assert sizes.parse_size("Rice 2 lb")[1] == "g"
    assert sizes.parse_size("16.9 FL OZ")[1] == "ml"
    assert sizes.parse_size("Coca-Cola") is None


def test_variable_barcodes():
    assert sizes.variable("2123456012996") == {"key": "W2123456", "value": Decimal("12.99")}
    assert sizes.variable("201234502999") == {"key": "W201234", "value": Decimal("2.99")}
    assert sizes.variable("5449000000996") is None  # a normal product
    assert sizes.variable("2123456012995") is None  # bad check digit


def _p(client, h, hid, **body):
    r = client.post(f"/api/households/{hid}/products", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_size_from_database_and_price_per_litre(client, jazz):
    h, hid = jazz
    FAKE_DB["5449000000996"]["quantity_text"] = "1.5 l"
    try:
        lk = client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h).json()
        cola = _p(client, h, hid, name=lk["name"], barcodes=["5449000000996"], category="Drinks")
    finally:
        FAKE_DB["5449000000996"]["quantity_text"] = "330 ml"
    assert Decimal(cola["size_amount"]) == 1500 and cola["size_unit"] == "ml"
    small = _p(client, h, hid, name="Coca-Cola can", category="Drinks", size_amount=330, size_unit="ml")
    store = client.post(f"/api/households/{hid}/stores", headers=h, json={"name": "Goisco"}).json()["id"]
    for pid, price in ((cola["id"], "3.00"), (small["id"], "1.20")):
        client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                    json={"product_id": pid, "quantity": 1, "unit_price": price, "store_id": store})
    pts = client.get(f"/api/households/{hid}/products/{cola['id']}/prices", headers=h).json()
    assert pts[0]["per"] == "l" and Decimal(str(pts[0]["per_base"])) == Decimal("2.00")
    cmp = client.get(f"/api/households/{hid}/products/{small['id']}/compare", headers=h).json()
    assert [x["name"] for x in cmp] == ["Coca-Cola", "Coca-Cola can"]  # 2.00/l beats 3.64/l
    assert cmp[1]["this"] and float(cmp[1]["per_base"]) == pytest.approx(3.64)


def test_size_from_receipt_name(client, jazz):
    from tests.test_receipts import ai, upload  # noqa: F401
    h, hid = jazz
    p = _p(client, h, hid, name="Whole milk 1 L")
    assert Decimal(p["size_amount"]) == 1000 and p["size_unit"] == "ml"


def test_deli_barcode_links_by_item_and_skips_databases(client, jazz, fresh_db):
    h, hid = jazz
    r = client.get(f"/api/households/{hid}/barcodes/2123456012996", headers=h).json()
    assert r["variable"] and r["product"] is None and Decimal(str(r["embedded_price"])) == Decimal("12.99")
    assert fresh_db == []  # never asked Open Food Facts
    gouda = _p(client, h, hid, name="Gouda young", barcodes=["2123456012996"])
    assert gouda["unit"] == "kg" and gouda["weighed"] and gouda["barcodes"] == ["W2123456"]
    # the next label for the same cheese: other weight, other price, same item part
    r2 = client.get(f"/api/households/{hid}/barcodes/2123456007008", headers=h).json()
    assert r2["product"]["id"] == gouda["id"] and Decimal(str(r2["embedded_price"])) == Decimal("7.00")


def test_read_label(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(identify, "ask_label", lambda db, hid_, jpeg: {
        "name": "Gouda jong", "weight": 345, "weight_unit": "g", "price_per": "2,49", "price_per_unit": "100g",
        "total": None, "best_before": "2026-10-20"})
    from tests.test_receipts import photo
    r = client.post(f"/api/households/{hid}/stock/read-label", headers=h,
                    files={"file": ("l.jpg", photo(), "image/jpeg")}).json()
    assert r == {"name": "Gouda jong", "weight_kg": 0.345, "price_per_kg": 24.9, "total": 8.59,
                 "best_before": "2026-10-20", "packed_on": None}


def test_nutrition_from_open_food_facts(client, jazz):
    h, hid = jazz
    hit = barcodes._parse("openfoodfacts", {"status": 1, "product": {
        "product_name": "Cola", "nutriscore_grade": "e", "nova_group": "4",
        "nutriments": {"sugars_100g": 10.6, "energy-kcal_100g": "42"}}})
    assert hit["nutriscore"] == "e" and hit["nova"] == 4 and hit["nutrients"] == {"sugars": 10.6, "kcal": 42.0}
    FAKE_DB["5449000000996"].update(nutriscore="e", nova=4, nutrients={"sugars": 10.6})
    try:
        client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h)
        cola = _p(client, h, hid, name="Coca-Cola", barcodes=["5449000000996"])
    finally:
        for k in ("nutriscore", "nova", "nutrients"):
            FAKE_DB["5449000000996"].pop(k)
    assert cola["nutriscore"] == "e" and cola["nova"] == 4
    apples = _p(client, h, hid, name="Apples")
    for pid, price in ((cola["id"], "3"), (apples["id"], "1")):
        client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                    json={"product_id": pid, "quantity": 1, "unit_price": price})
    rep = client.get(f"/api/households/{hid}/stock/nutrition", headers=h).json()
    grades = {g["grade"]: g for g in rep["by_grade"]}
    assert rep["rated_pct"] == 75 and grades["e"]["pct"] == 100 and grades["unrated"]["pct"] == 25
    assert rep["ultra_processed_pct"] == 100 and rep["top_d_e"][0]["name"] == "Coca-Cola"


PAGE = """<html><head><script type="application/ld+json">
{"@context":"https://schema.org","@graph":[{"@type":"WebPage"},{"@type":["Recipe"],"name":"Pancakes",
 "totalTime":"PT25M","recipeYield":["4 servings"],
 "recipeIngredient":["2 cups all-purpose flour, sifted","1 cup milk","2 eggs","Salt to taste","1 tbsp salted butter"],
 "recipeInstructions":[{"@type":"HowToStep","text":"Mix.&nbsp;"},{"@type":"HowToSection","itemListElement":[
   {"@type":"HowToStep","text":"Fry in a pan."}]}]}]}
</script></head><body>...</body></html>"""


def test_recipe_import_from_schema_org(client, jazz, monkeypatch):
    h, hid = jazz
    monkeypatch.setattr(recipe_import, "fetch", lambda url: PAGE)
    for name in ("Flour", "Milk", "Salt"):
        _p(client, h, hid, name=name)
    r = client.post(f"/api/households/{hid}/recipes/import", headers=h, json={"url": "https://example.com/pancakes"})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["title"] == "Pancakes" and rec["minutes"] == 25 and rec["servings"] == "4 servings"
    assert rec["steps"] == ["Mix.", "Fry in a pan."] and rec["via"] == "page"
    ings = {i["name"]: i for i in rec["ingredients"]}
    assert ings["all-purpose flour"]["amount"] == "2 cups" and ings["all-purpose flour"]["product_id"]
    assert ings["milk"]["product_id"] and ings["eggs"]["product_id"] is None
    assert ings["Salt"]["amount"] is None and ings["Salt"]["product_id"]
    assert ings["salted butter"]["product_id"] is None  # "Salt" is not "salted butter"
    added = client.post(f"/api/households/{hid}/recipes/{rec['id']}/missing-to-list", headers=h).json()["added"]
    assert set(added) == {"all-purpose flour", "milk", "eggs", "Salt", "salted butter"}  # nothing in stock yet
    again = client.post(f"/api/households/{hid}/recipes/{rec['id']}/missing-to-list", headers=h).json()["added"]
    assert again == []  # already on the list


def test_recipe_import_refuses_private_addresses(client, jazz):
    h, hid = jazz
    for url in ("http://127.0.0.1:3008/api/health", "http://localhost/x", "file:///etc/passwd"):
        r = client.post(f"/api/households/{hid}/recipes/import", headers=h, json={"url": url + "#padding"})
        assert r.status_code == 422, url


def _rpc(client, key, method, params=None, mid=1):
    r = client.post("/mcp", headers={"Authorization": f"Bearer {key}"},
                    json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()


def test_mcp_server(client, jazz):
    h, hid = jazz
    full = client.post(f"/api/households/{hid}/api-keys", headers=h, json={"name": "agent"}).json()["key"]
    ro = client.post(f"/api/households/{hid}/api-keys", headers=h,
                     json={"name": "reader", "read_only": True}).json()["key"]
    assert client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401
    init = _rpc(client, full, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "t", "version": "1"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and init["result"]["serverInfo"]["name"] == "kasita"
    assert client.post("/mcp", headers={"Authorization": f"Bearer {full}"},
                       json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    names = {t["name"] for t in _rpc(client, full, "tools/list")["result"]["tools"]}
    assert {"pantry", "shopping_list", "add_to_shopping_list", "tick_off", "used"} <= names
    ro_names = {t["name"] for t in _rpc(client, ro, "tools/list")["result"]["tools"]}
    assert "add_to_shopping_list" not in ro_names and "pantry" in ro_names
    call = _rpc(client, full, "tools/call", {"name": "add_to_shopping_list",
                                             "arguments": {"items": [{"name": "Milk", "quantity": 2}, "Bread"]}})
    assert call["result"]["structuredContent"]["added"] == ["Milk", "Bread"]
    lst = _rpc(client, full, "tools/call", {"name": "shopping_list"})["result"]["structuredContent"]["items"]
    assert [(i["name"], i["quantity"]) for i in lst] == [("Milk", 2.0), ("Bread", 1.0)]
    tick = _rpc(client, full, "tools/call", {"name": "tick_off", "arguments": {"name": "bread"}})
    assert tick["result"]["structuredContent"] == {"ticked": "Bread"}
    miss = _rpc(client, full, "tools/call", {"name": "tick_off", "arguments": {"name": "caviar"}})
    assert miss["result"]["isError"] is True
    denied = _rpc(client, ro, "tools/call", {"name": "add_to_shopping_list", "arguments": {"items": ["x"]}})
    assert denied["error"]["code"] == -32602
    pantry = _rpc(client, ro, "tools/call", {"name": "pantry"})["result"]
    assert pantry["isError"] is False and pantry["structuredContent"]["items"] == []
    assert _rpc(client, full, "nope")["error"]["code"] == -32601
