"""'Plan my week': dinners for the coming days that use what's at home first and cost the least.

The household's ChatGPT is given the pantry (expiring things marked), the prices it knows (what you paid, and what
Mangusa's web shop charges, including what is on sale) and a weekly budget, and proposes one dinner per day with
what to buy. Kasita prices every "buy" line itself from its own data (never from the AI), so the total is real:
  1. your cheapest recent price for that product (receipts / typed prices),
  2. else the online shop's price,
  3. else unknown (counted separately, not guessed).
Nothing is saved until the person accepts the plan (apply): then recipes, the week plan and the shopping list are made.
"""
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Household, Product
from . import chatgpt, codex, cook, market, prices
from .receipts import extract_json

INSTRUCTIONS = """You plan home-cooked dinners for a household in Curaçao (they cook Caribbean, Dutch, Latin and
everyday international food) to cost as little as possible. Reply with ONLY a JSON object:
{"days": [{"day": "YYYY-MM-DD", "title": string, "minutes": number, "uses": [string], "buy": [string],
           "steps": [string], "why": string}], "notes": string}

- One dinner for each requested day, in order, using exactly the dates given. English titles and steps.
- "uses": pantry items EXACTLY as listed. Use up items marked "expires in N days" first and say so in "why".
- "buy": what is missing, as short shopping-list names ("chicken thighs 1 kg"). At most 5 per dinner; reuse the same
  extras across several dinners (buy once, cook several times) so nothing is wasted. Salt, pepper, oil, water are free.
- Prefer ingredients from the known price list, especially anything marked "on sale"; avoid expensive extras.
- Respect the weekly budget when one is given. Vary the meals; no more than 2 dinners from the same protein.
- 3 to 6 short steps each. If the pantry already covers a dinner completely, "buy" is empty."""


def known_prices(db: Session, household_id: str) -> list[str]:
    """'Chicken thighs: 9.50 at Goisco' lines for products with a price, plus online sales."""
    prods = list(db.scalars(select(Product).where(Product.household_id == household_id, Product.archived.is_(False))))
    info = prices.store_prices(db, household_id, [p.id for p in prods])
    lines = []
    for p in prods:
        c = prices.compare(info.get(p.id))
        if c["cheapest_price"] is not None:
            lines.append(f"{p.name}: {c['cheapest_price']} at {c['cheapest_store']}")
        for o in market.offers_for_product(db, p):
            if not o["stale"] and o["in_stock"]:
                lines.append(f"{p.name}: {o['price']} at {o['store']} online" + (" (ON SALE)" if o["on_sale"] else ""))
    return lines[:120]


def ask_chatgpt(db: Session, household_id: str, prompt: str) -> dict:
    """Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS,
                         [{"type": "input_text", "text": prompt}], timeout=180)
    return extract_json(text)


def price_line(db: Session, household_id: str, name: str, products: list[Product], match) -> dict:
    """{"name", "product_id", "price", "store", "source"} for one 'buy' line."""
    p = match(products, name)
    out = {"name": name, "product_id": p.id if p else None, "price": None, "store": None, "source": None}
    if not p:
        return out
    c = prices.compare(prices.store_prices(db, household_id, [p.id]).get(p.id))
    if c["cheapest_price"] is not None:
        out.update(price=c["cheapest_price"], store=c["cheapest_store"], source="your receipts")
        return out
    offers = [o for o in market.offers_for_product(db, p) if o["in_stock"] and not o["stale"]]
    if offers:
        o = min(offers, key=lambda x: x["price"])
        out.update(price=o["price"], store=f"{o['store']} online", source="online shop")
    return out


def propose(db: Session, household_id: str, start: date | None = None, days: int = 7, note: str | None = None,
            budget: Decimal | None = None, match=None) -> dict:
    start = start or date.today()
    days = max(1, min(days, 10))
    h = db.get(Household, household_id)
    if budget is None and h and h.grocery_budget:
        budget = (h.grocery_budget * 7 / 30).quantize(Decimal("1"))  # a week's share of the monthly budget
    wanted = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    pantry = cook.pantry(db, household_id)
    prompt = (f"Today is {date.today().isoformat()}. Plan dinners for these days: {', '.join(wanted)}.\n\n"
              "At home:\n" + ("\n".join(f"- {x}" for x in pantry) or "- (nothing)") +
              "\n\nKnown prices (" + (h.currency if h else "XCG") + "):\n" +
              ("\n".join(f"- {x}" for x in known_prices(db, household_id)) or "- (none yet)"))
    if budget:
        prompt += f"\n\nWeekly food budget: {h.currency} {budget}"
    if note:
        prompt += f"\n\nWishes: {note.strip()[:200]}"
    got = ask_chatgpt(db, household_id, prompt)
    products = list(db.scalars(select(Product).where(Product.household_id == household_id, Product.archived.is_(False))))
    out_days, total, unpriced, seen_buy = [], Decimal(0), 0, set()
    for i, d in enumerate((got.get("days") or [])[:days]):
        if not isinstance(d, dict) or not d.get("title"):
            continue
        buy = []
        for b in (d.get("buy") or [])[:6]:
            line = price_line(db, household_id, str(b)[:80], products, match)
            key = line["product_id"] or line["name"].lower()
            line["repeat"] = key in seen_buy  # bought once for an earlier dinner: not paid again
            seen_buy.add(key)
            if not line["repeat"]:
                if line["price"] is None:
                    unpriced += 1
                else:
                    total += line["price"]
            buy.append(line)
        pantry_names = {p.name.lower(): p for p in products}
        uses = [str(u)[:80] for u in (d.get("uses") or [])][:12]
        out_days.append({"day": wanted[i], "title": str(d["title"])[:120], "minutes": int(d.get("minutes") or 0),
                         "uses": [{"name": u, "product_id": pantry_names[u.lower()].id if u.lower() in pantry_names else None}
                                  for u in uses],
                         "buy": buy, "steps": [str(x)[:300] for x in (d.get("steps") or [])][:8],
                         "why": str(d.get("why") or "")[:200]})
    return {"days": out_days, "est_cost": total, "unpriced": unpriced, "budget": budget,
            "currency": h.currency if h else "XCG", "notes": str(got.get("notes") or "")[:300]}
