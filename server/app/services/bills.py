"""Household bills (water, electricity, garbage, internet...) → the payment in Securo.

1. A photo (or the pages of one bill) is kept like a receipt and read by the
   household's ChatGPT: biller, what each service costs, amount due, dates.
2. The person picks the bills they paid together; `candidates` finds the Securo
   payment of that summed amount (bills are often paid days or weeks later).
3. `link` attaches every bill photo to that payment, puts it in Utilities and
   adds a breakdown note. `record` creates the payment first when Securo has
   none (cash at the counter, or an online payment that never showed up).
"""
import base64
import logging
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import settings
from ..db import SessionLocal
from ..models import Bill
from . import chatgpt, codex, securo
from .receipts import _date, _household_currency, _num, extract_json, sections

log = logging.getLogger(__name__)

CATEGORY = "Utilities"

INSTRUCTIONS = """You read photos of household utility bills (mostly Curaçao: Aqualectra water and electricity, Selikor garbage collection, Flow / UTS / Digicel internet, TV and phone) and reply with ONLY a JSON object, no prose, no code fences:
{"biller": "Aqualectra", "account": "customer or account number or null", "period": "September 2026 or null",
 "bill_date": "YYYY-MM-DD or null", "due_date": "YYYY-MM-DD or null", "currency": "XCG",
 "lines": [{"service": "water", "amount": 50.98}, {"service": "electricity", "amount": 250.00}],
 "total": 300.98, "card_total": null}
Rules:
- "total" is the amount due / te betalen / total a pagar on this bill, including any previous balance.
- "lines" split that total by service, in plain lowercase English words (water, electricity, garbage, internet, tv, phone, previous balance, late fee). One bill that combines water and electricity MUST be split into both. Taxes and fixed charges belong to the service they are printed under; if they cannot be placed, give them their own line. The lines must add up to the total.
- Amounts are plain numbers with a dot for decimals. Guilder (NAf, ANG, Cg, XCG) is "XCG"; US dollars is "USD".
- Dates on Curaçao bills are day-month-year.
- The photos may be payment receipts instead of bills, e.g. Pagafasil / Western Union / kiosk slips that say "Transakshon eksitoso", and several of them can come in one upload. Then each receipt is one paid bill: add one line per receipt, the service taken from who was paid (Selikor = garbage, Flow / UTS / Digicel = internet or phone, Aqualectra = water unless it says electricity, Pagatinu / a prepaid token / kWh = electricity), "total" is the sum of those lines, and "biller" names who was paid, joined with ", " when there are several (e.g. "Selikor, Flow, Aqualectra").
- A card terminal slip (bank logo, "Purchase" / "Sale", masked card number, Auth code, AID, "Cardholder copy") is how the bills were paid, NOT a bill: never make it a line and never add it to the total. Put its amount in "card_total" instead (null when there is none).
- If something is not printed, use null. Never guess numbers.
- Before replying, check your work: add up the lines and compare with the total.
"""


def bills_dir(household_id: str) -> Path:
    d = Path(settings.upload_dir) / "bills" / household_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_with_chatgpt(db: Session, household_id: str, jpeg: bytes) -> dict:
    """Ask the household's ChatGPT to read the bill. Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    parts = sections(jpeg)
    intro = f"Read this bill. If no currency is printed, assume {_household_currency(db, household_id)}."
    if len(parts) > 1:
        intro += f" It comes as {len(parts)} overlapping sections (or pages), top to bottom; count nothing twice."
    content = [{"type": "input_text", "text": intro}] + [
        {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(p).decode(),
         "detail": "high"} for p in parts]
    return extract_json(codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS, content))


def _text(v, limit: int) -> str | None:
    v = str(v or "").strip()
    return v[:limit] if v and v.lower() != "null" else None


def apply_parsed(bill: Bill, parsed: dict) -> None:
    lines = []
    for ln in parsed.get("lines") or []:
        amount = _num(ln.get("amount")) if isinstance(ln, dict) else None
        service = str(ln.get("service") or "").strip().lower()[:40] if isinstance(ln, dict) else ""
        if service and amount is not None:
            lines.append({"service": service, "amount": f"{amount:.2f}"})
    total = _num(parsed.get("total"))
    if total is None and lines:
        total = sum(Decimal(ln["amount"]) for ln in lines)
    bill.biller = _text(parsed.get("biller"), 120)
    bill.account_ref = _text(parsed.get("account"), 60)
    bill.period = _text(parsed.get("period"), 60)
    bill.bill_date = _date(parsed.get("bill_date"))
    bill.due_date = _date(parsed.get("due_date"))
    bill.currency = (str(parsed.get("currency") or "").upper()[:3] or None) or bill.currency
    bill.lines = lines
    bill.total = total.quantize(Decimal("0.01")) if total is not None else None
    bill.raw = parsed
    bill.status, bill.error = "read", None


def parse(bill_id: str) -> None:
    """Background job: read the photo with the AI. Uses its own session."""
    with SessionLocal() as db:
        bill = db.get(Bill, bill_id)
        if not bill or bill.status == "linked":
            return
        try:
            parsed = read_with_chatgpt(db, bill.household_id, Path(bill.image_path).read_bytes())
            apply_parsed(bill, parsed)
        except Exception as e:  # noqa: BLE001  (shown to the user on the bill)
            db.rollback()
            bill = db.get(Bill, bill_id)
            bill.status = "failed"
            bill.error = str(e)[:500] if isinstance(e, (ValueError, codex.CodexError)) else "Reading the bill failed"
            log.warning("bill %s failed: %r", bill_id, e)
        db.commit()


def total_of(bills: list[Bill]) -> tuple[Decimal, str | None]:
    """Sum of the bills in the first bill's currency (the guilder/dollar peg covers mixed bills)."""
    currency = next((b.currency for b in bills if b.currency), None)
    total = Decimal(0)
    for b in bills:
        if b.total is None:
            raise ValueError(f"{b.biller or 'A bill'} has no amount yet")
        amount = securo._in_currency(b.total, b.currency, currency)
        if amount is None:
            raise ValueError("These bills are in currencies Kasita cannot add up")
        total += amount
    return total.quantize(Decimal("0.01")), currency


def search_window(bills: list[Bill]) -> tuple[date, date]:
    # a bill is paid after it arrives, sometimes weeks later (or early, the day it is photographed)
    start = min((b.bill_date or b.created_at.date()) for b in bills) - timedelta(days=5)
    return start, min(start + timedelta(days=120), date.today() + timedelta(days=1))


def candidates(bills: list[Bill], txns: list[dict]) -> list[dict]:
    """Payments of exactly the summed amount first (biller name adds confidence); when none, the
    recent payments that look like bills, so a payment with a fee or rounding can still be picked."""
    total, currency = total_of(bills)
    biller_words = securo._words(" ".join(b.biller or "" for b in bills))
    exact, near = [], []
    for t in txns:
        try:
            amount = Decimal(str(t["amount"]))
        except (KeyError, ArithmeticError, ValueError):
            continue
        text = " ".join(filter(None, [t.get("description"), t.get("payee_name"), t.get("payee_raw")]))
        named = bool(biller_words & securo._words(text))
        utility = (t.get("category") or {}).get("name") == CATEGORY if isinstance(t.get("category"), dict) else False
        row = {"id": t["id"], "date": t.get("date"), "description": t.get("description"), "amount": str(amount),
               "currency": t.get("currency"), "notes": t.get("notes"),
               "attachment_count": t.get("attachment_count") or 0}
        converted = securo._in_currency(amount, t.get("currency"), currency)
        if converted is not None and abs(converted - total) <= Decimal("0.02"):
            same = (t.get("currency") or "").upper() == (currency or "").upper()
            exact.append({**row, "score": (4 if same else 2) + (2 if named else 0) + (1 if utility else 0)})
        elif named or utility:
            near.append({**row, "score": 0})
    exact.sort(key=lambda c: (-c["score"], c["date"] or ""))
    near.sort(key=lambda c: c["date"] or "", reverse=True)
    return exact[:5] if exact else near[:8]


def note(bills: list[Bill]) -> str:
    """"Bills: water 50.98 · electricity 250.00 · Selikor 35.00 · Flow 119.00 = 454.98" """
    parts = []
    for b in bills:
        lines = b.lines or []
        split = len(lines) > 1 and b.total is not None and \
            sum(Decimal(ln["amount"]) for ln in lines) == b.total
        if split:
            parts += [f"{ln['service']} {Decimal(ln['amount']):.2f}" for ln in lines]
        else:
            label = b.biller or (lines[0]["service"] if lines else "bill")
            parts.append(f"{label} {b.total:.2f}")
        if b.period:
            parts[-1] += f" ({b.period})"
    total, currency = total_of(bills)
    return f"Bills: {' · '.join(parts)} = {total:.2f}" + (f" {currency}" if currency else "")


def photo_name(bill: Bill) -> str:
    biller = "".join(c if c.isalnum() else "-" for c in (bill.biller or "bill").lower()).strip("-") or "bill"
    day = (bill.bill_date or bill.created_at.date()).isoformat()
    return f"bill-{biller}-{day}.jpg"


def link(conn: securo.Conn, bills: list[Bill], transaction_id: str, *, attach_photos: bool = True,
         set_category: bool = True, add_note: bool = True) -> list[str]:
    """Book the bills on that payment. Returns what could not be done (shown to the person)."""
    t = securo.transaction(conn, transaction_id)
    skipped = []
    if attach_photos:
        for b in bills:
            if b.image_path and Path(b.image_path).is_file():
                securo.link(conn, transaction_id, photo=Path(b.image_path).read_bytes(), photo_name=photo_name(b),
                            note=None, existing_notes=None)
    if set_category:
        cat = securo.category_id(conn, CATEGORY)
        if cat:
            securo.set_category(conn, transaction_id, cat)
        else:
            skipped.append(f"Securo has no {CATEGORY} category")
    if add_note:
        securo.link(conn, transaction_id, photo=None, photo_name="", note=note(bills), existing_notes=t.get("notes"))
    return skipped


def record(conn: securo.Conn, bills: list[Bill], account_id: str, day: date, description: str | None) -> str:
    """Create the payment in Securo (amount in the account's currency) and return its id."""
    account = next((a for a in securo.accounts(conn) if a["id"] == account_id), None)
    if account is None:
        raise ValueError("That Securo account was not found")
    total, currency = total_of(bills)
    amount = securo._in_currency(total, currency, account.get("currency"))
    if amount is None:
        raise ValueError(f"Kasita cannot convert {currency} to {account.get('currency')}")
    names = list(dict.fromkeys(b.biller for b in bills if b.biller))
    payload = {"description": (description or ", ".join(names) or "Bills")[:200],
               "amount": str(amount.quantize(Decimal("0.01"))), "date": day.isoformat(), "type": "debit",
               "account_id": account_id}
    cat = securo.category_id(conn, CATEGORY)
    if cat:
        payload["category_id"] = cat
    return securo.create_transaction(conn, payload)["id"]
