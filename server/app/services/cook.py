"""'What can I cook?': meal ideas from what is in the pantry, via the household's ChatGPT."""
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Product, StockEntry
from . import chatgpt, codex
from .receipts import extract_json

INSTRUCTIONS = """You suggest home-cooked meals from what a household has at home (Curaçao; they cook Caribbean,
Dutch, Latin and everyday international food). Reply with ONLY a JSON object:
{"ideas": [{"title": string, "minutes": number, "uses": [string], "missing": [string], "steps": [string], "why": string}]}

- Write titles, steps and "why" in English, even when pantry names are Spanish, Dutch or Papiamentu.
- 4 ideas. Build them mostly from the pantry list; "uses" names pantry items exactly as listed.
- Prefer items that expire soon (marked "expires in N days"); say so in "why" when an idea uses them.
- "missing": at most 3 cheap, common extras worth buying; basics like salt, pepper, oil, water are assumed.
- "steps": 3 to 6 short steps. Skip non-food items (soap, detergent, toilet paper...)."""


def pantry(db: Session, household_id: str) -> list[str]:
    today = date.today()
    rows = db.execute(
        select(Product.name, Product.unit, func.sum(StockEntry.quantity), func.min(StockEntry.best_before))
        .join(StockEntry, StockEntry.product_id == Product.id)
        .where(Product.household_id == household_id, StockEntry.quantity > 0)
        .group_by(Product.id, Product.name, Product.unit)
    ).all()
    out = []
    for name, unit, qty, bb in rows:
        line = f"{name} ({qty.normalize():f} {unit})"
        if bb is not None and (bb - today).days <= 5:
            line += f", expires in {max((bb - today).days, 0)} days"
        out.append(line)
    return out


def ask_chatgpt(db: Session, household_id: str, prompt: str) -> dict:
    """Tests replace this function."""
    secret = chatgpt.fresh_secret(db, household_id)
    text = codex.respond(secret, chatgpt.model_for(db, household_id), INSTRUCTIONS,
                         [{"type": "input_text", "text": prompt}], timeout=120)
    return extract_json(text)


def suggest(db: Session, household_id: str, note: str | None = None) -> dict:
    items = pantry(db, household_id)
    if not items:
        return {"ideas": [], "pantry": 0}
    prompt = "At home:\n" + "\n".join(f"- {i}" for i in items)
    if note:
        prompt += f"\n\nWishes: {note.strip()[:200]}"
    got = ask_chatgpt(db, household_id, prompt)
    ideas = []
    for i in (got.get("ideas") or [])[:6]:
        if not isinstance(i, dict) or not i.get("title"):
            continue
        ideas.append({"title": str(i["title"])[:120], "minutes": int(i.get("minutes") or 0),
                      "uses": [str(x)[:80] for x in (i.get("uses") or [])][:12],
                      "missing": [str(x)[:80] for x in (i.get("missing") or [])][:5],
                      "steps": [str(x)[:300] for x in (i.get("steps") or [])][:8],
                      "why": str(i.get("why") or "")[:200]})
    return {"ideas": ideas, "pantry": len(items)}
