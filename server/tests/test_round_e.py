from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db import SessionLocal
from app.models import Product, StockEvent
from app.services import digest as dg
from app.services import identify
from app.services import stock as svc


def _setup(client, jazz, **product):
    h, hid = jazz
    base = f"/api/households/{hid}"
    pid = client.post(f"{base}/products", json={"name": "Rice", **product}, headers=h).json()["id"]
    return h, hid, base, pid


def test_forecast_needs_history_then_puts_it_on_the_list(client, jazz):
    h, hid, base, pid = _setup(client, jazz)
    client.post(f"{base}/stock/purchase", json={"product_id": pid, "quantity": 10}, headers=h)
    with SessionLocal() as db:
        p = db.get(Product, pid)
        assert svc.forecast(db, p) is None                      # no history yet
        now = datetime.now(timezone.utc)
        # 8 used over the last 20 days: 0.4 a day
        for days_ago in (20, 10):
            db.add(StockEvent(household_id=hid, product_id=pid, kind="consume", quantity=Decimal(4),
                              at=now - timedelta(days=days_ago)))
        db.commit()
        rate, days_left = svc.forecast(db, p)
        assert round(rate, 2) == 0.4 and round(days_left) == 25  # 10 in stock / 0.4
    # use 9 of the 10: 1 left = 2.5 days -> onto the list, marked 'running out soon'
    client.post(f"{base}/stock/consume", json={"product_id": pid, "quantity": 9}, headers=h)
    items = client.get(f"{base}/shopping", headers=h).json()
    assert [(i["name"], i["note"]) for i in items] == [("Rice", "running out soon")]
    assert client.get(f"{base}/products/{pid}", headers=h).json()["runs_out_in_days"] is not None


def test_opened_countdown_only_shortens(client, jazz):
    h, hid, base, pid = _setup(client, jazz, name="Milk", open_days=5)
    far = (date.today() + timedelta(days=30)).isoformat()
    client.post(f"{base}/stock/purchase", json={"product_id": pid, "best_before": far}, headers=h)
    e = client.post(f"{base}/stock/open", json={"product_id": pid}, headers=h).json()
    assert e["best_before"] == (date.today() + timedelta(days=5)).isoformat()


def test_freezer_tracking_and_digests(client, jazz):
    h, hid, base, pid = _setup(client, jazz, name="Chicken")
    locs = {l["name"]: l["id"] for l in client.get(f"{base}/locations", headers=h).json()}
    soon = date.today().isoformat()
    e = client.post(f"{base}/stock/purchase", json={"product_id": pid, "best_before": soon}, headers=h).json()
    with SessionLocal() as db:
        assert dg.expiring(db, hid) == {"today": ["Chicken"]}
    moved = client.patch(f"{base}/stock/entries/{e['id']}", json={"location_id": locs["Freezer"]}, headers=h).json()
    assert moved["frozen_at"] == date.today().isoformat()
    with SessionLocal() as db:
        assert dg.expiring(db, hid) == {}                        # frozen: no expiry alarm
        assert dg.forgotten_in_freezer(db, hid) == []            # not forgotten yet
        later = date.today() + timedelta(days=70)
        assert dg.forgotten_in_freezer(db, hid, today=later) == ["Chicken (frozen 10 weeks ago)"]
    back = client.patch(f"{base}/stock/entries/{e['id']}", json={"location_id": locs["Fridge"]}, headers=h).json()
    assert back["frozen_at"] is None
    # setting a date on an existing batch
    d = (date.today() + timedelta(days=3)).isoformat()
    assert client.patch(f"{base}/stock/entries/{e['id']}", json={"best_before": d}, headers=h).json()["best_before"] == d


def test_read_date_from_photo(client, jazz, monkeypatch):
    import io

    from PIL import Image
    h, hid = jazz
    buf = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(buf, "JPEG")
    monkeypatch.setattr(identify, "ask_date", lambda db, hh, jpeg: {"date": "2026-10-31", "printed": "BB 10/2026"})
    r = client.post(f"/api/households/{hid}/stock/read-date", headers=h, files={"file": ("d.jpg", buf.getvalue(), "image/jpeg")})
    assert r.json() == {"date": "2026-10-31", "printed": "BB 10/2026"}
    monkeypatch.setattr(identify, "ask_date", lambda db, hh, jpeg: {"date": "not a date"})
    r = client.post(f"/api/households/{hid}/stock/read-date", headers=h, files={"file": ("d.jpg", buf.getvalue(), "image/jpeg")})
    assert r.json()["date"] is None
