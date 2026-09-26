from datetime import date, timedelta

from .conftest import login, make_user


def test_login_rejects_wrong_password(client):
    make_user()
    r = client.post("/api/auth/login", json={"email": "jazz@example.com", "password": "nope"})
    assert r.status_code == 401


def test_new_household_has_default_locations(client, jazz):
    h, hid = jazz
    names = [loc["name"] for loc in client.get(f"/api/households/{hid}/locations", headers=h).json()]
    assert sorted(names) == ["Freezer", "Fridge", "Pantry"]


def test_other_users_cannot_see_household(client, jazz):
    _, hid = jazz
    other = login(client, *make_user("other@example.com"))
    assert client.get(f"/api/households/{hid}/products", headers=other).status_code == 404
    assert client.get(f"/api/households/{hid}/products").status_code == 401


def test_barcode_lookup_uses_public_db_then_cache(client, jazz, fresh_db):
    h, hid = jazz
    r = client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h).json()
    assert r["found"] and r["name"] == "Coca-Cola" and r["product"] is None
    client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h)
    assert fresh_db == ["5449000000996"]  # second scan served from cache


def test_unknown_barcode_becomes_household_product(client, jazz):
    h, hid = jazz
    code = "893958000310"
    assert client.get(f"/api/households/{hid}/barcodes/{code}", headers=h).json()["found"] is False
    p = client.post(f"/api/households/{hid}/products", headers=h,
                    json={"name": "Goisco toilet paper 12 rolls", "barcodes": [code]}).json()
    r = client.get(f"/api/households/{hid}/barcodes/{code}", headers=h).json()
    assert r["source"] == "household" and r["product"]["id"] == p["id"]


def test_barcode_cannot_belong_to_two_products(client, jazz):
    h, hid = jazz
    client.post(f"/api/households/{hid}/products", headers=h, json={"name": "A", "barcodes": ["12345678"]})
    r = client.post(f"/api/households/{hid}/products", headers=h, json={"name": "B", "barcodes": ["12345678"]})
    assert r.status_code == 409


def test_consume_takes_soonest_expiring_first_and_refills_list(client, jazz):
    h, hid = jazz
    p = client.post(f"/api/households/{hid}/products", headers=h, json={"name": "Milk", "min_stock": 1}).json()
    later, sooner = date.today() + timedelta(days=9), date.today() + timedelta(days=2)
    client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                json={"product_id": p["id"], "quantity": 1, "best_before": later.isoformat()})
    client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                json={"product_id": p["id"], "quantity": 1, "best_before": sooner.isoformat()})
    r = client.post(f"/api/households/{hid}/stock/consume", headers=h, json={"product_id": p["id"], "quantity": 1}).json()
    assert float(r["remaining"]) == 1
    stock = client.get(f"/api/households/{hid}/stock", headers=h).json()
    assert stock[0]["entries"][0]["best_before"] == later.isoformat()  # the sooner batch was used
    assert client.get(f"/api/households/{hid}/shopping", headers=h).json() == []
    client.post(f"/api/households/{hid}/stock/consume", headers=h, json={"product_id": p["id"], "quantity": 1})
    items = client.get(f"/api/households/{hid}/shopping", headers=h).json()
    assert len(items) == 1 and items[0]["auto"] and items[0]["product_id"] == p["id"]
    # buying it ticks the automatic item off
    client.post(f"/api/households/{hid}/stock/purchase", headers=h, json={"product_id": p["id"], "quantity": 2})
    assert client.get(f"/api/households/{hid}/shopping", headers=h).json() == []


def test_consume_more_than_available_reports_shortfall(client, jazz):
    h, hid = jazz
    p = client.post(f"/api/households/{hid}/products", headers=h, json={"name": "Eggs"}).json()
    client.post(f"/api/households/{hid}/stock/purchase", headers=h, json={"product_id": p["id"], "quantity": 2})
    r = client.post(f"/api/households/{hid}/stock/consume", headers=h, json={"product_id": p["id"], "quantity": 5}).json()
    assert float(r["consumed"]) == 2 and float(r["short_by"]) == 3


def test_price_history_per_store(client, jazz):
    h, hid = jazz
    store = client.post(f"/api/households/{hid}/stores", headers=h, json={"name": "Mangusa"}).json()
    p = client.post(f"/api/households/{hid}/products", headers=h, json={"name": "Rice"}).json()
    client.post(f"/api/households/{hid}/stock/purchase", headers=h,
                json={"product_id": p["id"], "unit_price": "4.50", "store_id": store["id"]})
    prices = client.get(f"/api/households/{hid}/products/{p['id']}/prices", headers=h).json()
    assert prices[0]["store_name"] == "Mangusa" and float(prices[0]["unit_price"]) == 4.5


def test_invite_flow_and_member_scope(client, jazz):
    h, hid = jazz
    inv = client.post(f"/api/households/{hid}/invites", headers=h).json()
    r = client.post("/api/auth/accept-invite", json={"token": inv["token"], "email": "mom@example.com",
                                                     "name": "Mom", "password": "a-long-password"})
    assert r.status_code == 200
    mom = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"/api/households/{hid}/products", headers=mom).status_code == 200
    # an invite works once
    again = client.post("/api/auth/accept-invite", json={"token": inv["token"], "email": "x@example.com",
                                                         "name": "X", "password": "a-long-password"})
    assert again.status_code == 400
    # members can't create invites or API keys
    assert client.post(f"/api/households/{hid}/invites", headers=mom).status_code == 403
    assert client.post(f"/api/households/{hid}/api-keys", headers=mom, json={"name": "k"}).status_code == 403


def test_api_key_is_bound_to_its_household(client, jazz):
    h, hid = jazz
    other_hid = client.post("/api/households", json={"name": "Second"}, headers=h).json()["id"]
    key = client.post(f"/api/households/{hid}/api-keys", headers=h, json={"name": "n8n"}).json()["key"]
    k = {"X-Api-Key": key}
    assert client.get(f"/api/households/{hid}/products", headers=k).status_code == 200
    assert client.get(f"/api/households/{other_hid}/products", headers=k).status_code == 403


def test_refresh_token_rotates(client):
    make_user()
    t = client.post("/api/auth/login", json={"email": "jazz@example.com", "password": "correct-horse-battery"}).json()
    r1 = client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]})
    assert r1.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401
