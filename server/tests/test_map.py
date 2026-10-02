"""Store map: Nominatim geocoding (mocked), manual pins, spending per store."""
import io

import pytest
from PIL import Image

from app.db import SessionLocal
from app.models import Store
from app.services import geocode
from app.services import receipts as receipts_svc

HIT = [{"lat": "12.1180", "lon": "-68.9330", "display_name": "Cas Coraweg, Willemstad, Curaçao"}]


@pytest.fixture
def osm(monkeypatch):
    """Nominatim that knows exactly the searches in `known`."""
    calls, known = [], {}

    def search(params):
        calls.append(params)
        return known.get(tuple(sorted(params.items())), [])

    monkeypatch.setattr(geocode, "nominatim_search", search)
    return calls, known


def q(**params):
    return tuple(sorted(params.items()))


def make_store(**fields):
    with SessionLocal() as db:
        from app.models import Household
        hid = db.query(Household).first().id
        s = Store(household_id=hid, **fields)
        db.add(s)
        db.commit()
        return s.id


def load(sid):
    with SessionLocal() as db:
        return db.get(Store, sid)


def test_tries_address_then_structured_street_then_name(client, jazz, osm):
    calls, known = osm
    sid = make_store(name="Guonsheng Minimarket", address="Cas Coraweg 78")
    known[q(q="Guonsheng Minimarket, Curaçao")] = HIT
    with SessionLocal() as db:
        assert geocode.geocode_store(db, db.get(Store, sid)) is True
        db.commit()
    assert calls == [{"q": "Cas Coraweg 78, Curaçao"}, {"street": "78 Cas Coraweg", "country": "Curaçao"},
                     {"q": "Guonsheng Minimarket, Curaçao"}]
    s = load(sid)
    assert (s.lat, s.lon, s.location_source) == (12.118, -68.933, "geocoded")
    # cached: asking again costs no request
    with SessionLocal() as db:
        db.get(Store, sid).lat = None
        assert geocode.geocode_store(db, db.get(Store, sid)) is True
    assert len(calls) == 3


def test_nothing_found_stays_off_the_map_and_misses_are_cached(client, jazz, osm):
    calls, _ = osm
    sid = make_store(name="Toko Kaya", address="Kaya Flamboyan")
    with SessionLocal() as db:
        assert geocode.geocode_store(db, db.get(Store, sid)) is False
        db.commit()
        assert geocode.geocode_store(db, db.get(Store, sid)) is False
    assert len(calls) == 2  # address and name, once each (no house number: no structured search)
    assert load(sid).lat is None


def test_manual_pin_is_never_geocoded(client, jazz, osm):
    calls, known = osm
    h, hid = jazz
    known[q(q="Cas Coraweg 78, Curaçao")] = HIT
    sid = make_store(name="Guonsheng", address="Cas Coraweg 78")
    url = f"/api/households/{hid}/stores/{sid}"
    client.patch(url, headers=h, json={"lat": 12.2, "lon": -69.0})
    assert client.post(f"{url}/geocode", headers=h).json()["location_source"] == "manual"
    client.patch(url, headers=h, json={"address": "Cas Coraweg 80"})
    with SessionLocal() as db:
        geocode.geocode_all(db, redo=True)
    s = load(sid)
    assert (s.lat, s.lon, s.location_source) == (12.2, -69.0, "manual") and calls == []


def test_new_address_moves_a_looked_up_pin(client, jazz, osm):
    calls, known = osm
    h, hid = jazz
    known[q(q="Cas Coraweg 78, Curaçao")] = HIT
    known[q(q="Schottegatweg Oost 191, Curaçao")] = [{"lat": "12.13", "lon": "-68.90"}]
    sid = make_store(name="Mangusa")
    url = f"/api/households/{hid}/stores/{sid}"
    assert client.patch(url, headers=h, json={"address": "Cas Coraweg 78"}).status_code == 200
    assert load(sid).lat == 12.118  # geocoded in the background after the edit
    client.patch(url, headers=h, json={"address": "Schottegatweg Oost 191"})
    assert (load(sid).lat, load(sid).lon) == (12.13, -68.9)


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 1000), "white").save(buf, "JPEG")
    return buf.getvalue()


def book(client, h, hid, monkeypatch, parsed):
    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", lambda db, hid_, jpeg: parsed)
    rid = client.post(f"/api/households/{hid}/receipts", headers=h,
                      files={"file": ("r.jpg", photo(), "image/jpeg")}).json()["id"]
    assert client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).status_code == 200


def receipt(total, lines, date="2026-09-20"):
    return {"store": "GUONSHENG MINIMARKET", "store_address": "CAS CORAWEG 78", "store_tax_id": "102768456",
            "date": date, "currency": "XCG", "total": total,
            "lines": [{"text": t.upper(), "name": t, "quantity": 1, "line_total": p, "kind": "item"} for t, p in lines]}


def test_receipt_puts_store_on_map_and_map_shows_spending(client, jazz, osm, monkeypatch):
    calls, known = osm
    h, hid = jazz
    known[q(q="CAS CORAWEG 78, Curaçao")] = HIT
    book(client, h, hid, monkeypatch, receipt(10.0, [("Bread", 4.0), ("Milk", 6.0)]))
    book(client, h, hid, monkeypatch, receipt(20.0, [("Bread", 4.0), ("Rice", 16.0)], date="2026-09-27"))
    client.post(f"/api/households/{hid}/stores", headers=h, json={"name": "Nowhere"})
    pins = {p["name"]: p for p in client.get(f"/api/households/{hid}/stores/map", headers=h).json()}
    g = pins["Guonsheng Minimarket"]
    assert (g["lat"], g["lon"], g["visits"], float(g["total"]), float(g["average"])) == (12.118, -68.933, 2, 30, 15)
    assert g["last_visit"] == "2026-09-27"
    assert pins["Nowhere"]["lat"] is None and pins["Nowhere"]["visits"] == 0
    assert len(calls) == 1  # the second receipt found the store already on the map
    s = client.get(f"/api/households/{hid}/stores/{g['id']}/summary", headers=h).json()
    assert s["visits"] == 2 and s["top_items"][0]["name"] == "Bread" and s["top_items"][0]["times"] == 2
