"""Store profiles from receipts: address, phone and CRIB; CRIB matching; user edits kept."""
import io

import pytest
from PIL import Image

from app.services import receipts as receipts_svc


def photo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 1000), "white").save(buf, "JPEG")
    return buf.getvalue()


def parsed(store="GUONSHENG MINIMARKET", address="CAS CORAWEG 78", phone="Tel: 7374534", crib="102768456"):
    return {"store": store, "store_address": address, "store_phone": phone, "store_tax_id": crib,
            "date": "2026-09-20", "currency": "XCG", "total": 5.0,
            "lines": [{"text": "BREAD", "name": "Bread", "quantity": 1, "unit_price": 5.0, "line_total": 5.0,
                       "kind": "item"}]}


@pytest.fixture
def ai(monkeypatch):
    answer = {"next": parsed()}
    monkeypatch.setattr(receipts_svc, "read_with_chatgpt", lambda db, hid, jpeg: answer["next"])
    return answer


def book(client, h, hid):
    r = client.post(f"/api/households/{hid}/receipts", headers=h, files={"file": ("r.jpg", photo(), "image/jpeg")})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    c = client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={})
    assert c.status_code == 200, c.text
    return client.get(f"/api/households/{hid}/receipts/{rid}", headers=h).json()


def test_profile_filled_from_first_receipt_only(client, jazz, ai):
    h, hid = jazz
    r = book(client, h, hid)
    st = client.get(f"/api/households/{hid}/stores/{r['store_id']}", headers=h).json()
    assert st["name"] == "Guonsheng Minimarket"
    assert (st["address"], st["phone"], st["crib"]) == ("CAS CORAWEG 78", "7374534", "102768456")
    # a later receipt with another reading does not change what is there
    ai["next"] = parsed(address="CAS CORAWEG 87", phone="7374999")
    r2 = book(client, h, hid)
    assert r2["store_id"] == r["store_id"]
    st = client.get(f"/api/households/{hid}/stores/{r['store_id']}", headers=h).json()
    assert (st["address"], st["phone"]) == ("CAS CORAWEG 78", "7374534")


def test_crib_beats_a_misread_name(client, jazz, ai):
    h, hid = jazz
    first = book(client, h, hid)
    ai["next"] = parsed(store="GUANSHENG MINI MRKT", crib="CRIB NUMBER: 102-768-456")
    again = book(client, h, hid)
    assert again["store_id"] == first["store_id"]
    assert len(client.get(f"/api/households/{hid}/stores", headers=h).json()) == 1


def test_missing_fields_filled_later_and_user_edits_kept(client, jazz, ai):
    h, hid = jazz
    ai["next"] = parsed(address=None, phone=None)
    sid = book(client, h, hid)["store_id"]
    r = client.patch(f"/api/households/{hid}/stores/{sid}", headers=h,
                     json={"phone": "+599 9 737 4534", "name": "Guonsheng (Coraweg)"})
    assert r.status_code == 200, r.text
    ai["next"] = parsed()
    assert book(client, h, hid)["store_id"] == sid  # CRIB, though the name was changed
    st = client.get(f"/api/households/{hid}/stores/{sid}", headers=h).json()
    assert st["name"] == "Guonsheng (Coraweg)" and st["phone"] == "+599 9 737 4534"  # kept
    assert st["address"] == "CAS CORAWEG 78"  # was empty: filled


def test_another_branch_of_a_chain(client, jazz, ai):
    h, hid = jazz
    ai["next"] = parsed(store="CENTRUM", address="Piscaderaweg 1", crib="100200300")
    a = book(client, h, hid)["store_id"]
    ai["next"] = parsed(store="CENTRUM", address="Mahaaiweg 5", crib="100200300")
    b = book(client, h, hid)["store_id"]
    assert a != b
    ai["next"] = parsed(store="CENTRUM", address="MAHAAIWEG 5", crib="100200300")
    assert book(client, h, hid)["store_id"] == b
    names = sorted(s["name"] for s in client.get(f"/api/households/{hid}/stores", headers=h).json())
    assert names == ["Centrum", "Centrum (2)"]


def test_manual_pin_and_validation(client, jazz, ai):
    h, hid = jazz
    sid = book(client, h, hid)["store_id"]
    url = f"/api/households/{hid}/stores/{sid}"
    assert client.patch(url, headers=h, json={"lat": 12.1}).status_code == 422
    st = client.patch(url, headers=h, json={"lat": 12.12, "lon": -68.93}).json()
    assert st["location_source"] == "manual"
    st = client.patch(url, headers=h, json={"lat": None, "lon": None}).json()
    assert st["lat"] is None and st["location_source"] is None
    other = client.post(f"/api/households/{hid}/stores", headers=h, json={"name": "Mangusa"}).json()
    assert client.patch(f"/api/households/{hid}/stores/{other['id']}", headers=h,
                        json={"name": "Guonsheng Minimarket"}).status_code == 409


def test_profile_cleaning():
    p = receipts_svc.store_profile({"store_address": "  CAS   CORAWEG 78 ", "store_phone": "Tel: 737",
                                    "store_tax_id": "n/a"})
    assert p == {"address": "CAS CORAWEG 78"}


@pytest.mark.parametrize("text,street,number", [
    ("Cas Coraweg 78", "Cas Coraweg", "78"),
    ("Schottegatweg Oost 191", "Schottegatweg Oost", "191"),
    ("Kaya Flamboyan 12A", "Kaya Flamboyan", "12A"),
    ("Caracasbaaiweg 12-14", "Caracasbaaiweg", "12-14"),
    ("CAS CORAWEG, 78", "CAS CORAWEG", "78"),
    ("Kaya Kaya z/n", "Kaya Kaya z/n", None),
    ("Piscadera", "Piscadera", None),
    ("", "", None),
])
def test_split_address(text, street, number):
    assert receipts_svc.split_address(text) == (street, number)
