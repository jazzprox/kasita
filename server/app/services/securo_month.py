"""A month of groceries, seen from both sides: what Securo says you paid (its Groceries
category, plus any payment a Kasita receipt is linked to) and what Kasita knows was in the bag.

Securo has the true total (every card payment); Kasita knows what was in it, but only for
the receipts that were scanned. The report shows both, how much of the money has a receipt
behind it, which payments have none, and Kasita receipts that look like an unlinked payment.
Read-only: linking stays a tap in the app (POST /receipts/{id}/securo-link).
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Household, Product, Receipt
from . import securo

CATEGORY = "Groceries"
SUGGEST_SCORE = 6  # an exact amount within two days, or the same day at a converted amount + store name


def month_bounds(month: str | None, today: date | None = None) -> tuple[date, date]:
    """"2026-09" -> (2026-09-01, 2026-10-01); None = this month."""
    today = today or date.today()
    first = date.fromisoformat(f"{month}-01") if month else today.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def receipt_breakdown(db: Session, receipts: list[Receipt]) -> list[dict]:
    """What the receipts' lines were, per category (same grouping as the note Kasita writes in Securo)."""
    by: dict[str, Decimal] = {}
    for r in receipts:
        for line in r.lines:
            if line.skip or line.line_total is None:
                continue
            product = db.get(Product, line.product_id) if line.product_id else None
            cat = (product.category if product and product.category
                   else line.spending_category or "Other").split(",")[0].strip()
            by[cat] = by.get(cat, Decimal(0)) + line.line_total
    return [{"name": k, "amount": v} for k, v in sorted(by.items(), key=lambda kv: -kv[1])]


def report(db: Session, household_id: str, month: str | None = None) -> dict:
    first, nxt = month_bounds(month)
    h = db.get(Household, household_id)
    cur = h.currency if h else "XCG"
    conn = securo.conn_for(db, household_id)
    cid = securo.category_id(conn, CATEGORY)

    payments: dict[str, dict] = {}
    if cid:
        r = securo._request(conn, "GET", "/api/transactions", params={
            "from": first.isoformat(), "to": (nxt - timedelta(days=1)).isoformat(), "type": "debit",
            "category_id": cid, "limit": 500, "exclude_transfers": "true"}).json()
        for t in r.get("items", []):
            payments[t["id"]] = t

    receipts = list(db.scalars(select(Receipt).where(
        Receipt.household_id == household_id, Receipt.status == "confirmed",
        Receipt.purchased_on >= first, Receipt.purchased_on < nxt)))
    linked = {r.securo_transaction_id: r for r in receipts if r.securo_transaction_id}
    # a receipt can be linked to a payment Securo files under another category (Shopping, Food & Dining...)
    for tid in linked:
        if tid not in payments:
            try:
                payments[tid] = securo.transaction(conn, tid)
            except securo.SecuroError:
                pass  # deleted in Securo since

    rows, total, covered = [], Decimal(0), Decimal(0)
    unlinked_receipts = [r for r in receipts if not r.securo_transaction_id]
    for t in sorted(payments.values(), key=lambda t: t.get("date") or ""):
        amount = securo._in_currency(_money(t["amount"]), t.get("currency"), cur)
        if amount is None:
            continue
        amount = amount.quantize(Decimal("0.01"))
        total += amount
        r = linked.get(t["id"])
        row = {"id": t["id"], "date": t.get("date"), "description": t.get("description"),
               "amount": _money(t["amount"]), "currency": t.get("currency"), "in_currency": amount,
               "category": (t.get("category") or {}).get("name"),
               "receipt_id": r.id if r else None, "suggested_receipt_id": None}
        if r:
            covered += amount
        else:
            # a scanned receipt that fits this payment but was never linked
            best = None
            for rec in unlinked_receipts:
                c = securo.candidates(db, rec, [t])
                if c and c[0]["score"] >= SUGGEST_SCORE and (best is None or c[0]["score"] > best[0]):
                    best = (c[0]["score"], rec)
            if best:
                row["suggested_receipt_id"] = best[1].id
        rows.append(row)

    budget = None
    if cid:
        try:
            for b in securo._request(conn, "GET", "/api/budgets", params={"month": first.isoformat()}).json():
                if str(b.get("category_id")) == cid:
                    amount = securo._in_currency(_money(b["amount"]), b.get("currency") or cur, cur)
                    if amount is not None:
                        budget = {"amount": amount.quantize(Decimal("0.01")), "currency": cur}
        except securo.SecuroError:
            pass

    return {
        "month": first.strftime("%Y-%m"), "currency": cur, "category_found": cid is not None,
        "securo_total": total, "with_receipt": covered, "without_receipt": total - covered,
        "coverage_pct": round(float(covered / total) * 100) if total else None,
        "payments": rows,
        "receipts_total": sum((r.total or Decimal(0) for r in receipts), Decimal(0)),
        "receipts": len(receipts),
        "unlinked_receipts": [{"id": r.id, "date": r.purchased_on.isoformat() if r.purchased_on else None,
                               "store": r.store_name, "total": r.total} for r in unlinked_receipts],
        "by_category": receipt_breakdown(db, receipts),
        "kasita_budget": h.grocery_budget if h else None,
        "securo_budget": budget,
    }


def monthly_message(rep: dict) -> str | None:
    """The 1st-of-the-month summary of the month before."""
    if not rep["payments"] and not rep["receipts"]:
        return None
    cur = rep["currency"]
    lines = [f"Groceries in {date.fromisoformat(rep['month'] + '-01'):%B}: {cur} {rep['securo_total']:.2f} in Securo"]
    if rep["coverage_pct"] is not None:
        lines.append(f"Receipts cover {rep['coverage_pct']}% ({cur} {rep['with_receipt']:.2f})")
    missing = [p for p in rep["payments"] if not p["receipt_id"]]
    if missing:
        lines.append(f"{len(missing)} payment{'s' if len(missing) != 1 else ''} without a receipt: "
                     + ", ".join(f"{p['description']} {p['in_currency']:.2f}" for p in missing[:4])
                     + (" …" if len(missing) > 4 else ""))
    if rep["by_category"]:
        lines.append("In the bags: " + ", ".join(f"{c['name']} {c['amount']:.2f}" for c in rep["by_category"][:5]))
    budget = rep["securo_budget"]["amount"] if rep["securo_budget"] else rep["kasita_budget"]
    if budget:
        lines.append(f"Budget {cur} {budget:.2f}: {round(float(rep['securo_total'] / budget) * 100)}% used")
    return "\n".join(lines)
