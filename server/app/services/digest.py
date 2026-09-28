"""Push digests to the household's phone through ntfy.

- expiry: every morning, only when something expires today/tomorrow (or already did).
- weekly: Sunday evening, what the week's groceries cost, per category and store.
Run from a host timer: `docker exec kasita python -m app.cli digest expiry|weekly`.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Household, Product, StockEntry, StockEvent, Store


def expiring(db: Session, household_id: str, today: date | None = None) -> dict[str, list[str]]:
    """Names grouped as expired / today / tomorrow (only products still in stock)."""
    today = today or date.today()
    rows = db.execute(
        select(Product.name, func.min(StockEntry.best_before))
        .join(StockEntry, StockEntry.product_id == Product.id)
        .where(Product.household_id == household_id, StockEntry.quantity > 0, StockEntry.best_before.is_not(None))
        .group_by(Product.id, Product.name)
    ).all()
    out: dict[str, list[str]] = {"expired": [], "today": [], "tomorrow": []}
    for name, bb in rows:
        days = (bb - today).days
        if days < 0 and days >= -7:  # a week back at most: older is forgotten stock, not news
            out["expired"].append(name)
        elif days == 0:
            out["today"].append(name)
        elif days == 1:
            out["tomorrow"].append(name)
    return {k: sorted(v) for k, v in out.items() if v}


def expiry_message(groups: dict[str, list[str]]) -> str | None:
    if not groups:
        return None
    parts = []
    if "today" in groups:
        parts.append("Today: " + ", ".join(groups["today"]))
    if "tomorrow" in groups:
        parts.append("Tomorrow: " + ", ".join(groups["tomorrow"]))
    if "expired" in groups:
        parts.append("Already past: " + ", ".join(groups["expired"]))
    return "\n".join(parts)


def spending(db: Session, household_id: str, days: int = 7, until: datetime | None = None) -> dict:
    """What purchases with a price cost in the last `days` days, per category and per store."""
    until = until or datetime.now(timezone.utc)
    since = until - timedelta(days=days)
    rows = db.execute(
        select(StockEvent.quantity, StockEvent.unit_price, Product.category, Store.name)
        .join(Product, Product.id == StockEvent.product_id)
        .outerjoin(Store, Store.id == StockEvent.store_id)
        .where(StockEvent.household_id == household_id, StockEvent.kind == "purchase",
               StockEvent.unit_price.is_not(None), StockEvent.at >= since, StockEvent.at < until)
    ).all()
    by_cat: dict[str, Decimal] = {}
    by_store: dict[str, Decimal] = {}
    total = Decimal(0)
    for qty, price, cat, store in rows:
        amount = (qty * price).quantize(Decimal("0.01"))
        total += amount
        by_cat[cat or "Other"] = by_cat.get(cat or "Other", Decimal(0)) + amount
        by_store[store or "Unknown store"] = by_store.get(store or "Unknown store", Decimal(0)) + amount
    order = lambda d: [{"name": k, "amount": v} for k, v in sorted(d.items(), key=lambda kv: -kv[1])]  # noqa: E731
    h = db.get(Household, household_id)
    return {"days": days, "currency": h.currency if h else "XCG", "total": total,
            "by_category": order(by_cat), "by_store": order(by_store), "purchases": len(rows)}


def weekly_message(s: dict) -> str | None:
    if not s["purchases"]:
        return None
    cur = s["currency"]
    lines = [f"Groceries this week: {cur} {s['total']:.2f} ({s['purchases']} items)"]
    lines += [f"• {c['name']}: {c['amount']:.2f}" for c in s["by_category"][:6]]
    if len(s["by_store"]) > 1:
        lines.append("Stores: " + ", ".join(f"{x['name']} {x['amount']:.2f}" for x in s["by_store"][:4]))
    return "\n".join(lines)


def send(title: str, message: str, tags: str = "shopping_cart", priority: str = "default") -> None:
    if not (settings.ntfy_url and settings.ntfy_topic):
        raise RuntimeError("ntfy is not configured (KASITA_NTFY_URL / KASITA_NTFY_TOPIC)")
    headers = {"Title": title if title.isascii() else "Kasita",  # HTTP headers are latin-1 only
               "Tags": tags, "Priority": priority, "Click": settings.public_url}
    if settings.ntfy_token:
        headers["Authorization"] = f"Bearer {settings.ntfy_token}"
    r = httpx.post(f"{settings.ntfy_url.rstrip('/')}/{settings.ntfy_topic}", content=message.encode("utf-8"),
                   headers=headers, timeout=20)
    r.raise_for_status()
