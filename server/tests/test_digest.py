from datetime import date, timedelta
from decimal import Decimal

from app.db import SessionLocal
from app.services import digest as dg


def test_expiry_and_spending(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    today = date.today()

    def product(name, category=None):
        return client.post(f"{base}/products", json={"name": name, "category": category}, headers=h).json()["id"]

    def buy(pid, bb=None, price=None, qty=1, store=None):
        body = {"product_id": pid, "quantity": qty, "best_before": bb.isoformat() if bb else None,
                "unit_price": price, "store_id": store}
        assert client.post(f"{base}/stock/purchase", json=body, headers=h).status_code == 201

    store = client.post(f"{base}/stores", json={"name": "Goisco"}, headers=h).json()["id"]
    milk, yog, rice, old = product("Milk", "Dairy & eggs"), product("Yogurt", "Dairy & eggs"), product("Rice", "Pantry"), product("Old jam")
    buy(milk, today, price=4.75, qty=2, store=store)
    buy(yog, today + timedelta(days=1), price=2.50, store=store)
    buy(rice, today + timedelta(days=200), price=10)
    buy(old, today - timedelta(days=40))            # forgotten stock: not news every morning
    with SessionLocal() as db:
        groups = dg.expiring(db, hid)
        assert groups == {"today": ["Milk"], "tomorrow": ["Yogurt"]}
        msg = dg.expiry_message(groups)
        assert msg == "Today: Milk\nTomorrow: Yogurt"
        s = dg.spending(db, hid, days=7)
    assert s["total"] == Decimal("22.00") and s["purchases"] == 3
    assert s["by_category"][0] == {"name": "Dairy & eggs", "amount": Decimal("12.00")}
    assert {x["name"]: x["amount"] for x in s["by_store"]} == {"Goisco": Decimal("12.00"),
                                                               "Unknown store": Decimal("10.00")}
    assert "Groceries this week: XCG 22.00 (3 items)" in dg.weekly_message(s)
    # the same numbers over the API
    api = client.get(f"{base}/stock/spending?days=30", headers=h).json()
    assert float(api["total"]) == 22.0


def test_nothing_to_say_sends_nothing(client, jazz):
    _, hid = jazz
    with SessionLocal() as db:
        assert dg.expiry_message(dg.expiring(db, hid)) is None
        assert dg.weekly_message(dg.spending(db, hid)) is None


def test_digests_only_go_to_each_households_own_topic(client, jazz, monkeypatch):
    from app import cli
    from app.models import Household
    from app.services import digest
    h, hid = jazz
    other = client.post("/api/households", json={"name": "Mom"}, headers=h).json()["id"]
    today = date.today().isoformat()
    for house in (hid, other):
        pid = client.post(f"/api/households/{house}/products", json={"name": "Milk"}, headers=h).json()["id"]
        client.post(f"/api/households/{house}/stock/purchase", json={"product_id": pid, "best_before": today}, headers=h)
    with SessionLocal() as db:
        db.get(Household, hid).ntfy_topic = "kasita"
        db.commit()
    sent = []
    monkeypatch.setattr(digest, "send", lambda title, msg, tags, topic=None: sent.append((topic, title)))
    cli.digest("expiry", dry_run=False)
    assert sent == [("kasita", "Jazz: use these soon")]   # Mom's household has no topic: nothing sent anywhere
