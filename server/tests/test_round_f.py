from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.db import SessionLocal
from app.models import StockEvent
from app.services import digest as dg
from app.services import prices


def _world(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    goisco = client.post(f"{base}/stores", json={"name": "Goisco"}, headers=h).json()["id"]
    centrum = client.post(f"{base}/stores", json={"name": "Centrum"}, headers=h).json()["id"]
    milk = client.post(f"{base}/products", json={"name": "Milk"}, headers=h).json()["id"]
    rice = client.post(f"{base}/products", json={"name": "Rice"}, headers=h).json()["id"]
    return h, hid, base, goisco, centrum, milk, rice


def buy(client, h, base, pid, store, price):
    client.post(f"{base}/stock/purchase", json={"product_id": pid, "store_id": store, "unit_price": price}, headers=h)


def test_cheapest_store_split(client, jazz):
    h, hid, base, goisco, centrum, milk, rice = _world(client, jazz)
    buy(client, h, base, milk, goisco, 4.75)
    buy(client, h, base, milk, centrum, 5.20)
    buy(client, h, base, rice, centrum, 9.00)
    buy(client, h, base, rice, goisco, 9.50)
    for pid in (milk, rice):
        client.post(f"{base}/shopping", json={"product_id": pid}, headers=h)
    client.post(f"{base}/shopping", json={"name": "birthday candles"}, headers=h)
    split = client.get(f"{base}/shopping/by-store", headers=h).json()
    got = {g["store"]: [(i["name"], i["price"] and float(i["price"])) for i in g["items"]] for g in split}
    assert got == {"Goisco": [("Milk", 4.75)], "Centrum": [("Rice", 9.0)],
                   "Anywhere (no prices yet)": [("birthday candles", None)]}
    assert split[-1]["store"].startswith("Anywhere")


def test_price_rises_only_when_noticeable(client, jazz):
    h, hid, base, goisco, centrum, milk, rice = _world(client, jazz)
    with SessionLocal() as db:  # earlier prices, a month ago
        old = datetime.now(timezone.utc) - timedelta(days=30)
        for pid, price in ((milk, "4.75"), (rice, "9.00")):
            db.add(StockEvent(household_id=hid, product_id=pid, kind="purchase", quantity=Decimal(1),
                              unit_price=Decimal(price), store_id=goisco, at=old))
        db.commit()
    buy(client, h, base, milk, goisco, 5.35)   # +12.6%, +0.60: news
    buy(client, h, base, rice, goisco, 9.20)   # +2%: not news
    with SessionLocal() as db:
        rises = prices.price_changes(db, hid, days=7)
    assert [(r["product"], r["pct"]) for r in rises] == [("Milk", 13)]
    assert "Milk 4.75→5.35 at Goisco (+13%)" in dg.weekly_message(dg.spending(db, hid, days=7), rises)


def test_budget_alerts_once_per_threshold(client, jazz):
    h, hid, base, goisco, centrum, milk, rice = _world(client, jazz)
    assert float(client.patch(f"/api/households/{hid}", json={"grocery_budget": 100}, headers=h).json()["grocery_budget"]) == 100
    buy(client, h, base, rice, goisco, 50)
    with SessionLocal() as db:
        assert dg.budget_alert(db, hid) is None                        # 50%
    buy(client, h, base, rice, goisco, 35)
    with SessionLocal() as db:
        assert dg.budget_alert(db, hid).startswith("80% of the grocery budget")
        assert dg.budget_alert(db, hid) is None                        # not twice
    buy(client, h, base, rice, goisco, 20)
    with SessionLocal() as db:
        assert dg.budget_alert(db, hid).startswith("Grocery budget used up")
        assert dg.budget_alert(db, hid) is None
        next_month = datetime.now(timezone.utc).replace(day=28) + timedelta(days=10)
        assert dg.month_to_date(db, hid, now=next_month)["spent"] == 0  # a new month starts from zero
    assert client.get(f"{base}/stock/month", headers=h).json()["pct"] == 105


def test_activity_feed_names_who(client, jazz):
    h, hid, base, goisco, centrum, milk, rice = _world(client, jazz)
    buy(client, h, base, milk, goisco, 4.75)
    client.post(f"{base}/stock/consume", json={"product_id": milk}, headers=h)
    client.post(f"{base}/shopping", json={"name": "bread"}, headers=h)
    feed = client.get(f"{base}/stock/activity", headers=h).json()
    texts = [(f["who"], f["text"]) for f in feed]
    assert ("Jazz", "used Milk") in texts and ("Jazz", "bought Milk at Goisco") in texts
    assert ("Jazz", "put bread on the shopping list") in texts
