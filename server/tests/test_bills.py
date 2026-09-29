from decimal import Decimal

import pytest

from app.services import bills as bills_svc
from app.services import securo
from tests.test_receipts import photo
from tests.test_securo import connected  # noqa: F401  (fixture)

READS = {
    "aqua": {"biller": "Aqualectra", "account": "12345", "period": "August 2026", "bill_date": "2026-09-02",
             "due_date": "2026-09-20", "currency": "XCG",
             "lines": [{"service": "Water", "amount": 50.98}, {"service": "electricity", "amount": "250.00"}],
             "total": 300.98},
    "selikor": {"biller": "Selikor", "bill_date": "2026-09-01", "currency": "XCG",
                "lines": [{"service": "garbage", "amount": 35}], "total": 35},
    "flow": {"biller": "Flow", "bill_date": "2026-09-05", "currency": "XCG", "lines": [], "total": 119},
}

TXNS = [
    {"id": "t-salinja", "date": "2026-09-28", "description": "SALINJA BILL PAYMENT", "amount": "454.98",
     "currency": "XCG", "notes": "MCB debit", "attachment_count": 0},
    {"id": "t-flow", "date": "2026-09-10", "description": "Flow Curacao", "amount": "120.50", "currency": "XCG"},
    {"id": "t-shop", "date": "2026-09-12", "description": "Mangusa", "amount": "80.00", "currency": "XCG"},
]


@pytest.fixture
def ai(monkeypatch):
    queue = []

    def fake(db, household_id, jpeg):
        return READS[queue.pop(0)]

    monkeypatch.setattr(bills_svc, "read_with_chatgpt", fake)
    return queue


def upload(client, h, hid, ai, which, pages=1):
    ai.append(which)
    r = client.post(f"/api/households/{hid}/bills", headers=h,
                    files=[("file", (f"p{i}.jpg", photo(), "image/jpeg")) for i in range(pages)])
    assert r.status_code == 201, r.text
    return client.get(f"/api/households/{hid}/bills/{r.json()['id']}", headers=h).json()


def test_bill_is_read_and_can_be_corrected(client, jazz, ai):
    h, hid = jazz
    b = upload(client, h, hid, ai, "aqua", pages=2)
    assert b["status"] == "read" and b["biller"] == "Aqualectra" and b["due_date"] == "2026-09-20"
    assert b["lines"] == [{"service": "water", "amount": "50.98"}, {"service": "electricity", "amount": "250.00"}]
    assert Decimal(b["total"]) == Decimal("300.98")
    r = client.patch(f"/api/households/{hid}/bills/{b['id']}", headers=h,
                     json={"total": "301.00", "lines": [{"service": " Water ", "amount": 51}]}).json()
    assert Decimal(r["total"]) == Decimal("301.00") and r["lines"] == [{"service": "water", "amount": "51.00"}]
    assert client.get(f"/api/households/{hid}/bills/{b['id']}/image", headers=h).content[:2] == b"\xff\xd8"
    assert len(client.get(f"/api/households/{hid}/bills", headers=h).json()) == 1


def test_failed_read_is_shown(client, jazz, monkeypatch):
    h, hid = jazz

    def boom(db, household_id, jpeg):
        raise ValueError("ChatGPT is not connected")

    monkeypatch.setattr(bills_svc, "read_with_chatgpt", boom)
    r = client.post(f"/api/households/{hid}/bills", headers=h, files={"file": ("b.jpg", photo(), "image/jpeg")})
    b = client.get(f"/api/households/{hid}/bills/{r.json()['id']}", headers=h).json()
    assert b["status"] == "failed" and "not connected" in b["error"]
    # typing the amount in by hand makes it usable anyway
    b = client.patch(f"/api/households/{hid}/bills/{b['id']}", headers=h, json={"biller": "Flow", "total": 119}).json()
    assert b["status"] == "read"


def test_three_bills_paid_together_find_and_book_the_payment(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    ids = [upload(client, h, hid, ai, w)["id"] for w in ("aqua", "selikor", "flow")]
    monkeypatch.setattr(securo, "transactions", lambda conn, start, end: TXNS)
    c = client.post(f"/api/households/{hid}/bills/payment-candidates", headers=h, json={"bill_ids": ids}).json()
    assert [x["id"] for x in c] == ["t-salinja"]

    calls = []
    monkeypatch.setattr(securo, "transaction", lambda conn, tid: {"id": tid, "notes": "MCB debit"})
    monkeypatch.setattr(securo, "link", lambda conn, tid, **kw: calls.append(("link", tid, kw)))
    monkeypatch.setattr(securo, "category_id", lambda conn, name: "cat-util")
    monkeypatch.setattr(securo, "set_category", lambda conn, tid, cat: calls.append(("cat", tid, cat)))
    r = client.post(f"/api/households/{hid}/bills/link", headers=h,
                    json={"bill_ids": ids, "transaction_id": "t-salinja"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["note"] == ("Bills: water 50.98 · electricity 250.00 (August 2026) · Selikor 35.00 · Flow 119.00"
                           " = 454.98 XCG")
    photos = [kw["photo_name"] for kind, _, kw in calls if kind == "link" and kw["photo"]]
    assert photos == ["bill-aqualectra-2026-09-02.jpg", "bill-selikor-2026-09-01.jpg", "bill-flow-2026-09-05.jpg"]
    assert ("cat", "t-salinja", "cat-util") in calls
    notes = [kw for kind, _, kw in calls if kind == "link" and kw["note"]]
    assert notes[0]["existing_notes"] == "MCB debit" and notes[0]["note"] == out["note"]
    assert all(b["status"] == "linked" for b in out["bills"])
    # booked once only
    assert client.post(f"/api/households/{hid}/bills/link", headers=h,
                       json={"bill_ids": ids[:1], "transaction_id": "t-x"}).status_code == 409
    assert client.delete(f"/api/households/{hid}/bills/{ids[0]}/securo-link", headers=h).json()["status"] == "read"


def test_no_exact_payment_offers_lookalikes(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    bid = upload(client, h, hid, ai, "flow")["id"]
    monkeypatch.setattr(securo, "transactions", lambda conn, start, end: TXNS)
    c = client.post(f"/api/households/{hid}/bills/payment-candidates", headers=h, json={"bill_ids": [bid]}).json()
    assert [x["id"] for x in c] == ["t-flow"] and c[0]["score"] == 0  # 120.50 with a fee: named, not exact


def test_record_cash_payment(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    ids = [upload(client, h, hid, ai, w)["id"] for w in ("selikor", "flow")]
    made = []
    monkeypatch.setattr(securo, "accounts", lambda conn: [{"id": "acc-usd", "name": "Wallet", "currency": "USD"}])
    monkeypatch.setattr(securo, "category_id", lambda conn, name: "cat-util")
    monkeypatch.setattr(securo, "create_transaction", lambda conn, p: made.append(p) or {"id": "t-new"})
    monkeypatch.setattr(securo, "transaction", lambda conn, tid: {"id": tid, "notes": None})
    monkeypatch.setattr(securo, "link", lambda conn, tid, **kw: None)
    r = client.post(f"/api/households/{hid}/bills/record", headers=h,
                    json={"bill_ids": ids, "account_id": "acc-usd", "date": "2026-09-28"})
    assert r.status_code == 201, r.text
    assert made == [{"description": "Selikor, Flow", "amount": "86.03", "date": "2026-09-28", "type": "debit",
                     "account_id": "acc-usd", "category_id": "cat-util"}]  # 154 XCG / 1.79
    assert r.json()["transaction_id"] == "t-new"
    assert client.post(f"/api/households/{hid}/bills/record", headers=h,
                       json={"bill_ids": ids, "account_id": "nope", "date": "2026-09-28"}).status_code == 409


def test_accounts_need_securo(client, jazz):
    h, hid = jazz
    r = client.get(f"/api/households/{hid}/bills/securo-accounts", headers=h)
    assert r.status_code == 502 and "not connected" in r.json()["detail"]


def test_other_households_bills_are_hidden(client, jazz, ai):
    from tests.conftest import login, make_user
    h, hid = jazz
    bid = upload(client, h, hid, ai, "flow")["id"]
    make_user("other@example.com", "another-long-password", "Other")
    h2 = login(client, "other@example.com", "another-long-password")
    assert client.get(f"/api/households/{hid}/bills/{bid}", headers=h2).status_code in (403, 404)


def test_retake_photos_starts_over_and_delete(client, jazz, ai):
    h, hid = jazz
    b = upload(client, h, hid, ai, "aqua")
    ai.append("flow")
    r = client.put(f"/api/households/{hid}/bills/{b['id']}/photos", headers=h,
                   files=[("file", ("a.jpg", photo(), "image/jpeg")), ("file", ("b.jpg", photo(), "image/jpeg"))])
    assert r.status_code == 200 and r.json()["status"] == "reading"
    again = client.get(f"/api/households/{hid}/bills/{b['id']}", headers=h).json()
    assert again["biller"] == "Flow" and Decimal(again["total"]) == 119
    assert client.delete(f"/api/households/{hid}/bills/{b['id']}", headers=h).status_code == 204
    assert client.get(f"/api/households/{hid}/bills", headers=h).json() == []


def test_bill_typed_in_by_hand(client, jazz):
    h, hid = jazz
    assert client.post(f"/api/households/{hid}/bills/manual", headers=h, json={"biller": "Flow"}).status_code == 422
    b = client.post(f"/api/households/{hid}/bills/manual", headers=h,
                    json={"biller": "Flow", "total": 119, "lines": [{"service": "Internet", "amount": 119}]}).json()
    assert b["status"] == "read" and not b["has_photo"] and b["lines"] == [{"service": "internet", "amount": "119.00"}]
    assert client.post(f"/api/households/{hid}/bills/{b['id']}/parse", headers=h).status_code == 409
