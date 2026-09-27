from decimal import Decimal

import httpx
import pytest

from app.services import securo
from tests.test_receipts import ai, upload  # noqa: F401  (fixture + helper)

TXNS = [
    {"id": "t-visa", "date": "2026-09-20", "description": "CENTRUM PISCADERA", "amount": "13.10", "currency": "USD",
     "notes": "MCB Visa ****2834", "attachment_count": 0},
    {"id": "t-debit", "date": "2026-09-21", "description": "Centrum Piscadera", "amount": "23.45", "currency": "XCG",
     "notes": "MCB Bankomatiko+", "attachment_count": 0},
    {"id": "t-other", "date": "2026-09-20", "description": "Mahaai", "amount": "17.50", "currency": "XCG"},
]


@pytest.fixture
def connected(client, jazz, monkeypatch):
    h, hid = jazz

    class Resp:
        status_code = 200
        text = '{"access_token": "sec-token"}'

        def json(self):
            return {"access_token": "sec-token"}

    monkeypatch.setattr(httpx, "post", lambda *a, **k: Resp())
    monkeypatch.setattr(securo, "_request", lambda conn, m, p, **k: Resp())
    r = client.post(f"/api/households/{hid}/integrations/securo", headers=h,
                    json={"email": "me@x.com", "password": "pw"})
    assert r.status_code == 200 and r.json()["connected"], r.text
    return h, hid


def test_candidates_rank_same_currency_and_store_first(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    monkeypatch.setattr(securo, "transactions", lambda conn, start, end: TXNS)
    rid = upload(client, h, hid)
    c = client.get(f"/api/households/{hid}/receipts/{rid}/securo-candidates", headers=h).json()
    assert [x["id"] for x in c] == ["t-debit", "t-visa"]  # 13.10 USD * 1.79 = 23.45 XCG also fits
    assert c[0]["score"] > c[1]["score"]


def test_link_attaches_photo_and_appends_note(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    monkeypatch.setattr(securo, "transactions", lambda conn, start, end: TXNS)
    calls = []
    monkeypatch.setattr(securo, "link", lambda conn, tid, **kw: calls.append((conn.token, tid, kw)))
    rid = upload(client, h, hid)
    r = client.post(f"/api/households/{hid}/receipts/{rid}/securo-link", headers=h,
                    json={"transaction_id": "t-debit"})
    assert r.status_code == 200, r.text
    assert r.json()["securo_transaction_id"] == "t-debit"
    token, tid, kw = calls[0]
    assert token == "sec-token" and tid == "t-debit"  # the decrypted token is used
    assert kw["photo"][:2] == b"\xff\xd8" and kw["existing_notes"] == "MCB Bankomatiko+"
    assert kw["note"].startswith("Kasita receipt: Other 22.45 (2 items)")
    assert client.post(f"/api/households/{hid}/receipts/{rid}/securo-link", headers=h,
                       json={"transaction_id": "nope"}).status_code == 404
    assert client.delete(f"/api/households/{hid}/receipts/{rid}/securo-link", headers=h).json()[
        "securo_transaction_id"] is None


def test_not_connected_is_a_clear_error(client, jazz, ai):  # noqa: F811
    h, hid = jazz
    rid = upload(client, h, hid)
    r = client.get(f"/api/households/{hid}/receipts/{rid}/securo-candidates", headers=h)
    assert r.status_code == 502 and "not connected" in r.json()["detail"]


def test_currency_peg():
    assert securo._in_currency(Decimal("10"), "USD", "XCG") == Decimal("17.90")
    assert securo._in_currency(Decimal("17.90"), "XCG", "USD") == Decimal("10")
    assert securo._in_currency(Decimal("5"), "EUR", "XCG") is None
