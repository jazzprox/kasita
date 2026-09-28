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


def test_change_password_signs_out_other_devices(client):
    email, pw = make_user(email="pw@example.com")
    phone = client.post("/api/auth/login", json={"email": email, "password": pw}).json()
    laptop = client.post("/api/auth/login", json={"email": email, "password": pw}).json()
    h = {"Authorization": f"Bearer {laptop['access_token']}"}
    url = "/api/auth/change-password"
    assert client.post(url, headers=h, json={"current_password": "nope", "new_password": "a-new-long-password"}).status_code == 400
    assert client.post(url, headers=h, json={"current_password": pw, "new_password": "short"}).status_code == 422
    r = client.post(url, headers=h, json={"current_password": pw, "new_password": "a-new-long-password"})
    assert r.status_code == 200 and r.json()["refresh_token"]
    # every old session is gone, the new one works, and only the new password logs in
    assert client.post("/api/auth/refresh", json={"refresh_token": phone["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": laptop["refresh_token"]}).status_code == 401
    assert client.post("/api/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 200
    assert client.post("/api/auth/login", json={"email": email, "password": pw}).status_code == 401
    assert client.post("/api/auth/login", json={"email": email, "password": "a-new-long-password"}).status_code == 200


def test_attach_barcode_to_receipt_product_fills_gaps(client, jazz):
    h, hid = jazz
    p = client.post(f"/api/households/{hid}/products", json={"name": "Cola from receipt"}, headers=h).json()
    r = client.post(f"/api/households/{hid}/products/{p['id']}/barcodes", params={"barcode": "5449000000996"}, headers=h)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["barcodes"] == ["5449000000996"] and out["brand"] == "Coca-Cola" and out["category"] == "Drinks"
    assert out["name"] == "Cola from receipt"  # the household's own name is kept
    # scanning it now finds the household product
    assert client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h).json()["product"]["id"] == p["id"]


def test_pantry_pass_undo(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    p = client.post(f"{base}/products", json={"name": "Rice"}, headers=h).json()
    stock = lambda: float(client.get(f"{base}/products/{p['id']}", headers=h).json()["in_stock"])  # noqa: E731
    a1 = client.post(f"{base}/stock/purchase", json={"product_id": p["id"]}, headers=h).json()
    a2 = client.post(f"{base}/stock/purchase", json={"product_id": p["id"]}, headers=h).json()
    assert a1["event_id"] and stock() == 2
    # minus: undo the last add exactly
    assert client.post(f"{base}/stock/undo", json={"event_ids": [a2["event_id"]]}, headers=h).status_code == 200
    assert stock() == 1
    # use one, then undo the use: back to 1
    used = client.post(f"{base}/stock/consume", json={"product_id": p["id"]}, headers=h).json()
    assert stock() == 0 and len(used["event_ids"]) == 1
    assert client.post(f"{base}/stock/undo", json={"event_ids": used["event_ids"]}, headers=h).status_code == 200
    assert stock() == 1
    # an add that has since been partly used can't be silently erased
    client.post(f"{base}/stock/consume", json={"product_id": p["id"], "quantity": 0.5}, headers=h)
    assert client.post(f"{base}/stock/undo", json={"event_ids": [a1["event_id"]]}, headers=h).status_code == 409
    # another household's events are invisible
    other = login(client, *make_user(email="undo-other@example.com"))
    assert client.post(f"{base}/stock/undo", json={"event_ids": [a1["event_id"]]}, headers=other).status_code == 404


def test_failed_lookup_is_not_remembered_for_a_month(client, jazz, monkeypatch):
    from datetime import datetime, timedelta, timezone

    from app.db import SessionLocal
    from app.models import BarcodeCache
    from app.services import barcodes as bcs
    h, hid = jazz
    calls = []

    def down(code):
        calls.append(code)
        raise bcs.Incomplete

    monkeypatch.setattr(bcs, "fetch_remote", down)
    assert client.get(f"/api/households/{hid}/barcodes/4006381333931", headers=h).json()["found"] is False
    with SessionLocal() as db:
        row = db.get(BarcodeCache, "4006381333931")
        age = datetime.now(timezone.utc) - row.fetched_at.replace(tzinfo=timezone.utc)
        # dated so that it expires after ~6 hours instead of 30 days
        assert timedelta(days=29) < age < timedelta(days=30)
        row.fetched_at = datetime.now(timezone.utc) - timedelta(days=31)  # simulate the 6 hours passing
        db.commit()
    monkeypatch.setattr(bcs, "fetch_remote", lambda code: {"source": "openfoodfacts", "name": "Stabilo"})
    assert client.get(f"/api/households/{hid}/barcodes/4006381333931", headers=h).json()["name"] == "Stabilo"


def test_brand_hint_from_company_prefix(client, jazz, monkeypatch):
    from app.services import barcodes as bcs
    h, hid = jazz
    base = f"/api/households/{hid}"
    monkeypatch.setattr(bcs, "fetch_remote", lambda code: None)  # nothing in any database
    # one Roland product the household already has
    client.post(f"{base}/products", json={"name": "Rice vinegar", "brand": "Roland",
                                          "barcodes": ["041224705272"]}, headers=h)
    r = client.get(f"{base}/barcodes/041224860506", headers=h).json()   # another Roland item
    assert r["found"] is False and r["brand_hint"] == "Roland"
    assert client.get(f"{base}/barcodes/5449000000996", headers=h).json()["brand_hint"] is None  # other maker
    # two brands under one prefix: no guess rather than a wrong one
    client.post(f"{base}/products", json={"name": "X", "brand": "Other brand", "barcodes": ["041224700017"]},
                headers=h)
    assert client.get(f"{base}/barcodes/041224860506", headers=h).json()["brand_hint"] is None


def test_shopping_items_carry_a_category(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    p = client.post(f"{base}/products", json={"name": "Head & Shoulders", "category": "Personal care"}, headers=h).json()
    client.post(f"{base}/shopping", json={"product_id": p["id"]}, headers=h)
    client.post(f"{base}/shopping", json={"name": "bananas"}, headers=h)
    client.post(f"{base}/shopping", json={"name": "thing"}, headers=h)
    cats = {i["name"]: i["category"] for i in client.get(f"{base}/shopping", headers=h).json()}
    assert cats == {"Head & Shoulders": "Personal care", "bananas": "Produce", "thing": None}


def test_invite_to_their_own_household(client, jazz):
    h, hid = jazz
    inv = client.post(f"/api/households/{hid}/invites", json={"own_household": True}, headers=h).json()
    assert inv["own_household"] is True
    r = client.post("/api/auth/accept-invite", json={"token": inv["url"].rsplit("/", 1)[1], "email": "friend@example.com",
                                                      "name": "Ana", "password": "a-long-password"})
    assert r.status_code == 200, r.text
    friend = {"Authorization": f"Bearer {r.json()['access_token']}"}
    theirs = client.get("/api/households", headers=friend).json()
    assert [x["name"] for x in theirs] == ["Ana's household"] and theirs[0]["role"] == "owner"
    assert len(client.get(f"/api/households/{theirs[0]['id']}/locations", headers=friend).json()) == 3
    # no access to the inviter's household, and the inviter's members are unchanged
    assert client.get(f"/api/households/{hid}/stock", headers=friend).status_code == 404
    assert [m["email"] for m in client.get(f"/api/households/{hid}/members", headers=h).json()] == ["jazz@example.com"]


def test_default_invite_still_joins(client, jazz):
    h, hid = jazz
    inv = client.post(f"/api/households/{hid}/invites", headers=h).json()
    assert inv["own_household"] is False
    r = client.post("/api/auth/accept-invite", json={"token": inv["url"].rsplit("/", 1)[1], "email": "fam@example.com",
                                                      "name": "Fam", "password": "a-long-password"})
    fam = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert [x["id"] for x in client.get("/api/households", headers=fam).json()] == [hid]
