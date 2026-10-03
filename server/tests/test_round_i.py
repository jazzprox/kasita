"""Round I: walking order per store, the widget's tick, Securo month of groceries."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.db import SessionLocal
from app.models import Receipt, ShoppingTick
from app.services import securo, securo_month
from tests.test_receipts import ai, upload  # noqa: F401  (fixture + helper)
from tests.test_securo import connected  # noqa: F401  (fixture)


def _store(client, h, hid, name):
    r = client.post(f"/api/households/{hid}/stores", headers=h, json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add(client, h, hid, name, product_id=None):
    body = {"name": name} if product_id is None else {"product_id": product_id}
    return client.post(f"/api/households/{hid}/shopping", headers=h, json=body).json()["id"]


def test_store_walk_is_learned_from_tick_order(client, jazz):
    h, hid = jazz
    store = _store(client, h, hid, "Goisco")
    milk = client.post(f"/api/households/{hid}/products", headers=h, json={"name": "Milk"}).json()["id"]
    today = date.today()
    # two trips: soap first, then milk, then bread
    for back in (2, 1):
        ids = [_add(client, h, hid, "Dish soap"), _add(client, h, hid, None, milk), _add(client, h, hid, "Bread")]
        for n, iid in enumerate(ids):
            at = datetime.now(timezone.utc) - timedelta(days=back) + timedelta(minutes=n)
            r = client.patch(f"/api/households/{hid}/shopping/{iid}", headers=h,
                             json={"done": True, "ticked_at": at.isoformat(),
                                   "local_day": (today - timedelta(days=back)).isoformat(), "store_id": store})
            assert r.status_code == 200, r.text
        client.post(f"/api/households/{hid}/shopping/clear-done", headers=h)
    bread, soap, m = _add(client, h, hid, "bread"), _add(client, h, hid, "Dish Soap"), _add(client, h, hid, None, milk)
    other = _add(client, h, hid, "Mystery thing")
    r = client.get(f"/api/households/{hid}/shopping/route", headers=h).json()
    assert r["store"] == "Goisco" and r["trips"] == 2  # the most recently walked store by default
    rank = r["rank"]
    assert rank[soap] < rank[m] < rank[bread]  # names match case-insensitively
    assert rank[other] is None  # never ticked there: the app puts it last
    assert r["stores"][0]["trips"] == 2


def test_untick_forgets_and_bad_store_is_refused(client, jazz):
    h, hid = jazz
    iid = _add(client, h, hid, "Eggs")
    assert client.patch(f"/api/households/{hid}/shopping/{iid}", headers=h,
                        json={"done": True, "store_id": "nope"}).status_code == 404
    client.patch(f"/api/households/{hid}/shopping/{iid}", headers=h, json={"done": True})
    client.patch(f"/api/households/{hid}/shopping/{iid}", headers=h, json={"done": False})
    with SessionLocal() as db:
        assert db.query(ShoppingTick).count() == 0


def test_offline_tick_keeps_its_time_but_not_a_wild_one(client, jazz):
    h, hid = jazz
    a, b = _add(client, h, hid, "A"), _add(client, h, hid, "B")
    earlier = datetime.now(timezone.utc) - timedelta(hours=5)
    client.patch(f"/api/households/{hid}/shopping/{a}", headers=h, json={"done": True, "ticked_at": earlier.isoformat()})
    client.patch(f"/api/households/{hid}/shopping/{b}", headers=h,
                 json={"done": True, "ticked_at": "2020-01-01T00:00:00Z"})
    with SessionLocal() as db:
        ta = db.query(ShoppingTick).filter_by(item_id=a).one()
        tb = db.query(ShoppingTick).filter_by(item_id=b).one()
        assert abs((ta.ticked_at.replace(tzinfo=timezone.utc) - earlier).total_seconds()) < 1
        assert tb.ticked_at.replace(tzinfo=timezone.utc) > earlier  # too old: replaced by "now"


def test_receipt_tells_where_the_ticks_happened(client, jazz, ai):  # noqa: F811
    h, hid = jazz
    a, b = _add(client, h, hid, "Toilet paper"), _add(client, h, hid, "Milk")
    for iid in (a, b):
        client.patch(f"/api/households/{hid}/shopping/{iid}", headers=h, json={"done": True})
    with SessionLocal() as db:  # pretend the shopping happened on the receipt's day
        for t in db.query(ShoppingTick):
            t.local_day = date(2026, 9, 20)
        db.commit()
    rid = upload(client, h, hid)
    assert client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={}).status_code == 200
    with SessionLocal() as db:
        store_id = db.get(Receipt, rid).store_id
        ticks = db.query(ShoppingTick).all()
        assert store_id and all(t.store_id == store_id and t.store_source == "receipt" for t in ticks)


def test_widget_key_may_tick_and_nothing_else(client, jazz):
    h, hid = jazz
    iid = _add(client, h, hid, "Rice")
    key = client.post(f"/api/households/{hid}/api-keys", headers=h,
                      json={"name": "Home-screen widget", "read_only": True}).json()["key"]
    k = {"X-Api-Key": key}
    w = client.get(f"/api/households/{hid}/widget", headers=k).json()
    assert w["items"] == [{"id": iid, "name": "Rice", "quantity": 1.0}]
    assert client.post(f"/api/households/{hid}/widget/tick/{iid}", headers=k).status_code == 200
    assert client.post(f"/api/households/{hid}/widget/tick/{iid}", headers=k).status_code == 200  # a retry is fine
    assert client.get(f"/api/households/{hid}/widget", headers=k).json()["items"] == []
    assert client.patch(f"/api/households/{hid}/shopping/{iid}", headers=k, json={"done": False}).status_code == 403
    assert client.post(f"/api/households/{hid}/shopping", headers=k, json={"name": "x"}).status_code == 403
    assert client.post(f"/api/households/{hid}/widget/tick/nope", headers=k).status_code == 404


def _fake_securo(monkeypatch, payments, extra=None):
    class R:
        def __init__(self, data):
            self.data, self.status_code, self.text = data, 200, ""

        def json(self):
            return self.data

    def fake(conn, method, path, **kw):
        if path == "/api/categories":
            return R([{"id": "cat-g", "name": "Groceries"}, {"id": "cat-u", "name": "Utilities"}])
        if path == "/api/transactions":
            assert kw["params"]["category_id"] == "cat-g"
            return R({"items": payments})
        if path == "/api/budgets":
            return R([{"category_id": "cat-g", "amount": "200.00", "currency": "USD"}])
        if path.startswith("/api/transactions/"):
            return R((extra or {})[path.rsplit("/", 1)[1]])
        raise AssertionError(path)

    monkeypatch.setattr(securo, "_request", fake)


PAYMENTS = [
    {"id": "t1", "date": "2026-09-20", "description": "Centrum Piscadera", "amount": "23.45", "currency": "XCG",
     "category_id": "cat-g", "category": {"name": "Groceries"}},
    {"id": "t2", "date": "2026-09-26", "description": "Goisco", "amount": "50.00", "currency": "XCG",
     "category_id": "cat-g", "category": {"name": "Groceries"}},
]


def test_securo_month_report(client, connected, ai, monkeypatch):  # noqa: F811
    h, hid = connected
    rid = upload(client, h, hid)
    client.post(f"/api/households/{hid}/receipts/{rid}/confirm", headers=h, json={})
    _fake_securo(monkeypatch, PAYMENTS)
    r = client.get(f"/api/households/{hid}/integrations/securo/groceries?month=2026-09", headers=h)
    assert r.status_code == 200, r.text
    rep = r.json()
    assert Decimal(str(rep["securo_total"])) == Decimal("73.45") and rep["coverage_pct"] == 0
    t1 = next(p for p in rep["payments"] if p["id"] == "t1")
    assert t1["suggested_receipt_id"] == rid and t1["receipt_id"] is None  # same amount, same day, same store
    assert [u["id"] for u in rep["unlinked_receipts"]] == [rid]
    assert Decimal(str(rep["securo_budget"]["amount"])) == Decimal("358.00")  # 200 USD at the peg
    assert rep["by_category"] and rep["receipts"] == 1
    assert client.get(f"/api/households/{hid}/integrations/securo/groceries?month=sept",
                      headers=h).status_code == 422

    # linked (to a payment Securo files elsewhere): it counts, and covers its share
    with SessionLocal() as db:
        db.get(Receipt, rid).securo_transaction_id = "t9"
        db.commit()
    t9 = {"id": "t9", "date": "2026-09-20", "description": "CENTRUM", "amount": "13.10", "currency": "USD",
          "category_id": "cat-s", "category": {"name": "Shopping"}}
    _fake_securo(monkeypatch, PAYMENTS, {"t9": t9})
    rep = securo_month.report(SessionLocal(), hid, "2026-09")
    assert rep["securo_total"] == Decimal("96.90") and rep["with_receipt"] == Decimal("23.45")
    assert rep["coverage_pct"] == 24
    msg = securo_month.monthly_message(rep)
    assert msg.startswith("Groceries in September: XCG 96.90 in Securo") and "2 payments without a receipt" in msg


def test_month_bounds():
    assert securo_month.month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))
    assert securo_month.month_bounds(None, date(2026, 2, 14)) == (date(2026, 2, 1), date(2026, 3, 1))
