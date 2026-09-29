"""Link receipts to card payments in Securo (the household's finance app).

Securo has no API keys, so the household owner signs in once and Kasita keeps
the (long-lived) access token, sealed like the ChatGPT tokens. Kasita only
READS transactions to suggest the payment a receipt belongs to; it writes to
Securo only when a person links a receipt (attach the photo, add a note).
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..crypto import seal, unseal
from ..models import Integration, Product, Receipt, Store

KIND = "securo"
# Caribbean guilder (XCG, formerly ANG) is pegged to the US dollar
PEG = {("USD", "XCG"): Decimal("1.79"), ("USD", "ANG"): Decimal("1.79")}


class SecuroError(Exception):
    pass


@dataclass
class Conn:
    url: str
    token: str


def get(db: Session, household_id: str) -> Integration | None:
    return db.scalar(select(Integration).where(Integration.household_id == household_id, Integration.kind == KIND))


def status(db: Session, household_id: str) -> dict:
    row = get(db, household_id)
    d = row.data if row else {}
    return {"connected": bool(d.get("token")), "url": d.get("url"), "email": d.get("email")}


def _request(conn: Conn, method: str, path: str, **kw) -> httpx.Response:
    try:
        r = httpx.request(method, conn.url.rstrip("/") + path, headers={"Authorization": f"Bearer {conn.token}"},
                          timeout=30, **kw)
    except httpx.HTTPError as e:
        raise SecuroError(f"Securo is not reachable: {e.__class__.__name__}") from e
    if r.status_code == 401:
        raise SecuroError("Securo sign-in expired; connect Securo again in Settings")
    if r.status_code >= 400:
        raise SecuroError(f"Securo answered {r.status_code}: {r.text[:200]}")
    return r


def connect(db: Session, household_id: str, url: str, email: str, password: str) -> dict:
    url = url.rstrip("/")
    try:
        r = httpx.post(f"{url}/api/auth/login", data={"username": email, "password": password}, timeout=30)
    except httpx.HTTPError as e:
        raise SecuroError(f"Securo is not reachable at {url}") from e
    if r.status_code != 200 or "access_token" not in r.text:
        raise SecuroError("Securo did not accept that email and password")
    token = r.json()["access_token"]
    _request(Conn(url, token), "GET", "/api/accounts")  # prove the token works
    row = get(db, household_id)
    if row is None:
        row = Integration(household_id=household_id, kind=KIND, data={})
        db.add(row)
    row.data = {"url": url, "email": email, "token": seal({"token": token})}
    db.commit()
    return status(db, household_id)


def disconnect(db: Session, household_id: str) -> None:
    row = get(db, household_id)
    if row:
        db.delete(row)
        db.commit()


def conn_for(db: Session, household_id: str) -> Conn:
    row = get(db, household_id)
    if not row or not row.data.get("token"):
        raise SecuroError("Securo is not connected. Connect it under More → Securo.")
    return Conn(row.data["url"], unseal(row.data["token"])["token"])


def transactions(conn: Conn, start: date, end: date) -> list[dict]:
    r = _request(conn, "GET", "/api/transactions", params={
        "from": start.isoformat(), "to": end.isoformat(), "type": "debit", "limit": 200, "exclude_transfers": "true"})
    return r.json().get("items", [])


def _in_currency(amount: Decimal, frm: str | None, to: str | None) -> Decimal | None:
    frm, to = (frm or "").upper(), (to or "").upper()
    if not frm or not to or frm == to:
        return amount
    if (frm, to) in PEG:
        return amount * PEG[(frm, to)]
    if (to, frm) in PEG:
        return amount / PEG[(to, frm)]
    return None


def _words(text: str) -> set[str]:
    return {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(w) >= 3}


def candidates(db: Session, receipt: Receipt, txns: list[dict]) -> list[dict]:
    """Rank card payments that could be this receipt. Amount must agree; date and store add confidence."""
    if receipt.total is None:
        return []
    store = db.get(Store, receipt.store_id) if receipt.store_id else None
    store_words = _words(" ".join(filter(None, [store.name if store else None, store.payee_match if store else None,
                                                receipt.store_name])))
    out = []
    for t in txns:
        try:
            amount = Decimal(str(t["amount"]))
        except (KeyError, ArithmeticError, ValueError):
            continue
        converted = _in_currency(amount, t.get("currency"), receipt.currency)
        if converted is None:
            continue
        diff = abs(converted - receipt.total)
        exact_currency = (t.get("currency") or "").upper() == (receipt.currency or "").upper()
        if diff > (Decimal("0.02") if exact_currency else max(Decimal("0.02"), receipt.total * Decimal("0.02"))):
            continue
        score = 4 if exact_currency else 2  # an exact same-currency amount is the strongest evidence
        if receipt.purchased_on and t.get("date"):
            days = abs((date.fromisoformat(t["date"][:10]) - receipt.purchased_on).days)
            score += 2 if days == 0 else (1 if days <= 2 else 0)
        text = " ".join(filter(None, [t.get("description"), t.get("payee_name"), t.get("payee_raw")]))
        if store_words and store_words & _words(text):
            score += 2
        out.append({"id": t["id"], "date": t.get("date"), "description": t.get("description"),
                    "amount": str(amount), "currency": t.get("currency"), "notes": t.get("notes"),
                    "attachment_count": t.get("attachment_count") or 0, "score": score, "_diff": diff})
    out.sort(key=lambda c: (-c["score"], c["_diff"]))
    for c in out:
        del c["_diff"]
    return out[:5]


def search_window(receipt: Receipt) -> tuple[date, date]:
    day = receipt.purchased_on or receipt.created_at.date()
    # card notifications can land a day or two after the purchase
    return day - timedelta(days=2), day + timedelta(days=4)


def summary_note(db: Session, receipt: Receipt) -> str:
    """"Kasita receipt: Groceries 45.10, Household 12.95 (9 items)" in the receipt's currency."""
    totals: dict[str, Decimal] = {}
    items = 0
    for line in receipt.lines:
        if line.skip or line.line_total is None:
            continue
        product = db.get(Product, line.product_id) if line.product_id else None
        cat = (product.category if product and product.category else "Other").split(",")[0].strip()[:30]
        totals[cat] = totals.get(cat, Decimal(0)) + line.line_total
        items += 1
    parts = ", ".join(f"{k} {v:.2f}" for k, v in sorted(totals.items(), key=lambda kv: -kv[1]))
    return f"Kasita receipt: {parts} ({items} items)" if parts else "Kasita receipt attached"


def link(conn: Conn, transaction_id: str, *, photo: bytes | None, photo_name: str, note: str | None,
         existing_notes: str | None) -> None:
    if photo is not None:
        _request(conn, "POST", f"/api/transactions/{transaction_id}/attachments",
                 files={"file": (photo_name, photo, "image/jpeg")})
    if note:
        notes = f"{existing_notes} • {note}" if existing_notes else note
        _request(conn, "PATCH", f"/api/transactions/{transaction_id}", json={"notes": notes[:1000]})


def transaction(conn: Conn, transaction_id: str) -> dict:
    return _request(conn, "GET", f"/api/transactions/{transaction_id}").json()


def accounts(conn: Conn) -> list[dict]:
    r = _request(conn, "GET", "/api/accounts").json()
    rows = r.get("items", []) if isinstance(r, dict) else r
    return [a for a in rows if not a.get("is_closed")]


def category_id(conn: Conn, name: str) -> str | None:
    r = _request(conn, "GET", "/api/categories").json()
    rows = r.get("items", []) if isinstance(r, dict) else r
    return next((c["id"] for c in rows if (c.get("name") or "").strip().lower() == name.lower()), None)


def set_category(conn: Conn, transaction_id: str, category: str) -> None:
    _request(conn, "PATCH", f"/api/transactions/{transaction_id}", json={"category_id": category})


def create_transaction(conn: Conn, payload: dict) -> dict:
    return _request(conn, "POST", "/api/transactions", json=payload).json()
