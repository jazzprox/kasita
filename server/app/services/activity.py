"""Who did what in the household: the activity feed."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Product, Receipt, ShoppingItem, StockEvent, Store, User

VERB = {"purchase": "bought", "consume": "used", "spoil": "threw away", "open": "opened"}


def feed(db: Session, household_id: str, limit: int = 60) -> list[dict]:
    names = {u.id: u.name for u in db.scalars(select(User))}
    out = []
    for ev, product, store in db.execute(
        select(StockEvent, Product.name, Store.name)
        .join(Product, Product.id == StockEvent.product_id)
        .outerjoin(Store, Store.id == StockEvent.store_id)
        .where(StockEvent.household_id == household_id)
        .order_by(StockEvent.at.desc()).limit(limit)
    ).all():
        qty = "" if ev.kind == "open" or ev.quantity == 1 else f"{ev.quantity.normalize():f}× "
        text = f"{VERB.get(ev.kind, ev.kind)} {qty}{product}" + (f" at {store}" if ev.kind == "purchase" and store else "")
        out.append({"at": ev.at, "who": names.get(ev.user_id), "kind": ev.kind, "text": text})
    for it in db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == household_id, ShoppingItem.auto.is_(False))
                         .order_by(ShoppingItem.created_at.desc()).limit(limit)):
        out.append({"at": it.created_at, "who": names.get(it.added_by), "kind": "list",
                    "text": f"put {it.name} on the shopping list"})
    for r, store in db.execute(select(Receipt, Store.name).outerjoin(Store, Store.id == Receipt.store_id)
                               .where(Receipt.household_id == household_id)
                               .order_by(Receipt.created_at.desc()).limit(limit)).all():
        out.append({"at": r.created_at, "who": names.get(r.uploaded_by), "kind": "receipt",
                    "text": f"scanned a {store or r.store_name or ''} receipt".replace("a  receipt", "a receipt")})
    out.sort(key=lambda x: x["at"].isoformat() if x["at"].tzinfo else x["at"].isoformat() + "+00:00", reverse=True)
    return out[:limit]
