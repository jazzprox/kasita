"""Where you shop: visits and spending per store, and fun stats, from booked receipts."""
import math
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, Receipt, ReceiptLine, Store


def _receipt_total(r: Receipt) -> Decimal | None:
    if r.total is not None:
        return r.total
    totals = [ln.line_total for ln in r.lines if ln.line_total is not None and not ln.skip]
    return sum(totals) if totals else None


def _receipts(db: Session, household_id: str, days: int | None, store_id: str | None = None) -> list[Receipt]:
    stmt = select(Receipt).where(Receipt.household_id == household_id, Receipt.status == "confirmed",
                                 Receipt.store_id.is_not(None))
    if store_id:
        stmt = stmt.where(Receipt.store_id == store_id)
    if days:
        stmt = stmt.where(Receipt.purchased_on >= date.today() - timedelta(days=days))
    return list(db.scalars(stmt))


def _summary(receipts: list[Receipt]) -> dict:
    totals = [t for t in (_receipt_total(r) for r in receipts) if t is not None]
    spent = sum(totals, Decimal(0))
    days = [r.purchased_on or r.created_at.date() for r in receipts]
    return {"visits": len(receipts), "total": spent,
            "average": (spent / len(totals)).quantize(Decimal("0.01")) if totals else None,
            "first_visit": min(days) if days else None, "last_visit": max(days) if days else None}


def map_stores(db: Session, household_id: str, days: int | None = None) -> list[dict]:
    """Every store with its pin (if any) and how much was spent there: the map's pins."""
    by_store: dict[str, list[Receipt]] = defaultdict(list)
    for r in _receipts(db, household_id, days):
        by_store[r.store_id].append(r)
    out = []
    for s in db.scalars(select(Store).where(Store.household_id == household_id).order_by(Store.name)):
        out.append({"id": s.id, "name": s.name, "address": s.address, "lat": s.lat, "lon": s.lon,
                    "location_source": s.location_source, **_summary(by_store.get(s.id, []))})
    return out


def store_summary(db: Session, household_id: str, store: Store, days: int | None = None, top: int = 8) -> dict:
    """One store: visits, total spent, average basket and what you buy there most."""
    receipts = _receipts(db, household_id, days, store.id)
    lines = [ln for r in receipts for ln in r.lines if not ln.skip]
    names = {p.id: p.name for p in db.scalars(select(Product).where(
        Product.id.in_({ln.product_id for ln in lines if ln.product_id})))}
    count: Counter = Counter()
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for ln in lines:
        name = names.get(ln.product_id) or ln.name or ln.raw_text
        count[name] += 1
        if ln.line_total is not None:
            spent[name] += ln.line_total
    top_items = [{"name": n, "times": c, "spent": spent.get(n, Decimal(0))}
                 for n, c in sorted(count.items(), key=lambda kv: (-kv[1], -spent.get(kv[0], 0), kv[0]))[:top]]
    return {"id": store.id, "name": store.name, **_summary(receipts), "top_items": top_items}


# --- fun stats ---------------------------------------------------------------------
KIND_WORDS = [
    ("minimarket", re.compile(r"\bMINI[\s-]?(MARKET|MERCADO|MART|SUPER)\b|\bTOKO\b")),
    ("supermarket", re.compile(r"\b(SUPER|HYPER)[\s-]?(MARKET|MERCADO|MARCHE)\b|\bSUPERMERCADO\b")),
]
# Curaçao's big supermarkets, for names that don't say so
SUPERMARKETS = ("CENTRUM", "MANGUSA", "GOISCO", "VAN DEN TWEEL", "VREUGDENHIL", "CARREFOUR", "ESPERAMOS",
                "BUURTSUPER", "PRICESMART", "ALBERT HEIJN")


def guess_kind(name: str | None) -> str:
    """minimarket | supermarket | other, from the store's name."""
    n = (name or "").upper()
    for kind, rx in KIND_WORDS:
        if rx.search(n):
            return kind
    return "supermarket" if any(w in n for w in SUPERMARKETS) else "other"


def km_between(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance (haversine), in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _part_of_day(hour: int) -> str:
    return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening" if hour < 21 else "late night"


def fun_stats(db: Session, household, days: int = 365) -> dict:
    receipts = _receipts(db, household.id, days)
    stores = {s.id: s for s in db.scalars(select(Store).where(Store.household_id == household.id))}
    cur = household.currency
    out: dict = {"days": days, "trips": len(receipts), "headlines": []}
    if not receipts:
        out["headlines"].append("No booked receipts yet: scan a few and come back for your shopping stats.")
        return out
    when = [r.purchased_on or r.created_at.date() for r in receipts]
    lines = out["headlines"]

    # home turf
    visits = Counter(r.store_id for r in receipts)
    sid, n = max(visits.items(), key=lambda kv: (kv[1], stores[kv[0]].name))
    out["home_turf"] = {"store_id": sid, "name": stores[sid].name, "visits": n,
                        "share": round(n / len(receipts), 3)}
    lines.append(f"Home turf: {stores[sid].name}, {n} of your {len(receipts)} trips.")

    # trips per week / month, over the time you have been scanning receipts (at least a week)
    span = max(7, (date.today() - min(when)).days + 1)
    out["per_week"] = round(len(receipts) / (span / 7), 1)
    out["per_month"] = round(len(receipts) / (span / 30.44), 1)
    lines.append(f"About {out['per_week']:g} shopping trips a week ({out['per_month']:g} a month).")

    # favourite days and times
    by_day = Counter(d.weekday() for d in when)
    out["weekdays"] = [{"day": WEEKDAYS[i], "trips": by_day.get(i, 0)} for i in range(7)]
    fav = max(range(7), key=lambda i: (by_day.get(i, 0), -i))
    out["favourite_day"] = WEEKDAYS[fav]
    times = [r.purchased_time for r in receipts if r.purchased_time]
    if times:
        by_hour = Counter(t.hour for t in times)
        out["hours"] = [{"hour": h, "trips": by_hour.get(h, 0)} for h in range(24)]
        parts = Counter(_part_of_day(t.hour) for t in times)
        out["favourite_time"] = parts.most_common(1)[0][0]
        out["favourite_hour"] = max(by_hour.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        lines.append(f"Favourite moment: {WEEKDAYS[fav]} {out['favourite_time']}s.")
        early = min(times)
        if early.hour < 9:
            lines.append(f"Early bird: once you were shopping at {early.strftime('%H:%M')}.")
    else:
        lines.append(f"Favourite day: {WEEKDAYS[fav]}.")

    # how far you travel
    home = (household.home_lat, household.home_lon)
    if home[0] is not None and home[1] is not None:
        far = [(r, km_between(home[0], home[1], stores[r.store_id].lat, stores[r.store_id].lon))
               for r in receipts if stores[r.store_id].lat is not None and stores[r.store_id].lon is not None]
        if far:
            dist = [d for _, d in far]
            fr, fd = max(far, key=lambda x: x[1])
            out["travel"] = {"trips_counted": len(far), "average_km": round(sum(dist) / len(dist), 1),
                             "round_trip_km": round(2 * sum(dist), 1),
                             "farthest": {"name": stores[fr.store_id].name, "km": round(fd, 1)}}
            lines.append(f"You travelled about {out['travel']['round_trip_km']:g} km to shop "
                         f"(there and back, as the crow flies).")
            if fd >= 1:
                lines.append(f"Farthest: {stores[fr.store_id].name}, {fd:.1f} km from home.")
    else:
        out["travel"] = None

    # minimarkets vs supermarkets
    spent: dict[str, Decimal] = defaultdict(Decimal)
    for r in receipts:
        t = _receipt_total(r)
        if t is not None:
            spent[stores[r.store_id].kind_guess] += t
    total = sum(spent.values(), Decimal(0))
    out["by_kind"] = [{"kind": k, "total": spent.get(k, Decimal(0)),
                       "share": round(float(spent.get(k, 0) / total), 3) if total else 0.0}
                      for k in ("supermarket", "minimarket", "other")]
    if total:
        mini = spent.get("minimarket", Decimal(0)) / total
        lines.append(f"{round(float(mini) * 100)}% of your {cur} {total:.2f} went to minimarkets."
                     if mini else f"All your {cur} {total:.2f} went to the big stores: no minimarket receipts yet.")
    out["stores_visited"] = len(visits)
    if len(visits) >= 3:
        lines.append(f"Explorer: you shopped at {len(visits)} different stores.")
    return out
