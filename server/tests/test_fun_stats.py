"""Fun stats: home turf, trips, days and times, travel, minimarkets vs supermarkets."""
import io
from datetime import date, timedelta

import pytest
from PIL import Image

from app.services import receipts as receipts_svc
from app.services.store_stats import guess_kind, km_between


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 1000), "white").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def book(client, jazz, monkeypatch):
    h, hid = jazz
    answer = {}
    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", lambda db, hid_, jpeg: answer["next"])

    def go(store, total, days_ago, time=None):
        answer["next"] = {"store": store, "date": (date.today() - timedelta(days=days_ago)).isoformat(),
                          "time": time, "currency": "XCG", "total": total,
                          "lines": [{"text": "STUFF", "name": "Stuff", "quantity": 1, "line_total": total,
                                     "kind": "item"}]}
        rid = client.post(f"/api/households/{hid}/receipts", headers=h,
                          files={"file": ("r.jpg", photo(), "image/jpeg")}).json()["id"]
        r = client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()
        assert client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).status_code == 200
        return r
    return go


def test_guess_kind():
    assert guess_kind("GUONSHENG MINIMARKET") == "minimarket"
    assert guess_kind("Lucky Mini Market") == "minimarket"
    assert guess_kind("Mangusa Hypermarket") == "supermarket"
    assert guess_kind("Centrum Piscadera") == "supermarket"
    assert guess_kind("Snack Kaya") == "other"


def test_receipt_time_is_read(book):
    r = book("CENTRUM", 10, 1, time="6:42 PM")  # the AI is told 24h; a sloppy answer is still read
    assert r["purchased_time"] == "18:42:00"
    assert book("CENTRUM", 10, 1, time="12:05 a.m.")["purchased_time"] == "00:05:00"
    assert book("CENTRUM", 10, 1, time="18:42")["purchased_time"] == "18:42:00"
    assert book("CENTRUM", 10, 1, time="later")["purchased_time"] is None


def test_no_receipts(client, jazz):
    h, hid = jazz
    s = client.get(f"/api/households/{hid}/stats", headers=h).json()
    assert s["trips"] == 0 and s["headlines"]


def test_fun_stats(client, jazz, book):
    h, hid = jazz
    for d in (1, 8, 15):
        book("MANGUSA HYPERMARKET", 100, d, time="10:15")
    book("GUONSHENG MINIMARKET", 50, 2, time="19:30")
    s = client.get(f"/api/households/{hid}/stats", headers=h).json()
    assert s["trips"] == 4 and s["home_turf"]["name"] == "Mangusa Hypermarket" and s["home_turf"]["visits"] == 3
    assert s["favourite_time"] == "morning" and s["favourite_hour"] == 10
    assert sum(d["trips"] for d in s["weekdays"]) == 4
    assert s["per_week"] == round(4 / (16 / 7), 1)
    kinds = {k["kind"]: (float(k["total"]), k["share"]) for k in s["by_kind"]}
    assert kinds["minimarket"] == (50, 0.143) and kinds["supermarket"] == (300, 0.857)
    assert s["travel"] is None
    assert any("14% of your XCG 350.00 went to minimarkets" in x for x in s["headlines"])

    # the user says the hypermarket is "other"; set home and pin the stores: travel appears
    stores = {x["name"]: x["id"] for x in client.get(f"/api/households/{hid}/stores", headers=h).json()}
    st = client.patch(f"/api/households/{hid}/stores/{stores['Mangusa Hypermarket']}", headers=h,
                      json={"kind": "other", "lat": 12.12, "lon": -68.90}).json()
    assert st["kind"] == "other" and st["kind_guess"] == "other"
    assert client.put(f"/api/households/{hid}/home", headers=h, json={"lat": 12.12, "lon": -68.92}).status_code == 200
    s = client.get(f"/api/households/{hid}/stats", headers=h).json()
    assert {k["kind"]: k["share"] for k in s["by_kind"]}["other"] == 0.857
    assert s["travel"]["trips_counted"] == 3 and s["travel"]["farthest"]["name"] == "Mangusa Hypermarket"
    assert s["travel"]["round_trip_km"] == pytest.approx(6 * km_between(12.12, -68.92, 12.12, -68.90), abs=0.1)
    assert client.get(f"/api/households/{hid}/home", headers=h).json() == {"lat": 12.12, "lon": -68.92}
    assert client.put(f"/api/households/{hid}/home", headers=h, json={"lat": 1}).status_code == 422


def test_km_between():
    assert km_between(12.1, -68.9, 12.1, -68.9) == 0
    assert 10.5 < km_between(12.0, -68.9, 12.1, -68.9) < 11.6
