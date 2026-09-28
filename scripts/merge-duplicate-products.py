"""Merge products that a receipt split in two.

Until the guard in `services/receipts.confirm` existed, two lines of the same
item on one receipt made two products with the same name — a shop rings two
pineapples up as two lines of quantity 1, not one line of quantity 2. The fix
stops it happening again; this repairs what already happened.

The OLDEST row of each same-name group wins, because its id is the one the
receipt's first line already points at. Everything attached to the others is
moved onto it and the empty rows are deleted.

Dry by default:
    docker exec kasita python /srv/scripts/merge-duplicate-products.py
    docker exec kasita python /srv/scripts/merge-duplicate-products.py --write
"""
import sys
from collections import defaultdict

sys.path.insert(0, "/srv")

from sqlalchemy import select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Product, ProductBarcode, ReceiptLine, ShoppingItem, StockEntry,
)

WRITE = "--write" in sys.argv

# Every table that points at a product. Missing one would orphan rows on a
# deleted id, so this list is the whole contract of the script.
MOVE = [(StockEntry, "product_id"), (ProductBarcode, "product_id"),
        (ShoppingItem, "product_id"), (ReceiptLine, "product_id")]

db = SessionLocal()
groups: dict[tuple[str, str], list[Product]] = defaultdict(list)
for p in db.scalars(select(Product).order_by(Product.created_at)):
    groups[(p.household_id, " ".join(p.name.split()).lower())].append(p)

dupes = {k: v for k, v in groups.items() if len(v) > 1}
if not dupes:
    print("No duplicate product names.")
    raise SystemExit(0)

moved_total = 0
for (_, name), rows in dupes.items():
    keep, *rest = rows
    print(f"\n{rows[0].name}  —  keeping {keep.id[:8]} (oldest), merging {len(rest)}")
    for old in rest:
        for model, col in MOVE:
            hits = db.scalars(select(model).where(getattr(model, col) == old.id)).all()
            for row in hits:
                setattr(row, col, keep.id)
            if hits:
                moved_total += len(hits)
                print(f"    {old.id[:8]} → {len(hits):>3} {model.__tablename__}")
        # A field the kept row lacks and the duplicate has is worth keeping.
        for field in ("brand", "category", "image_url", "notes", "shelf_life_days"):
            if not getattr(keep, field, None) and getattr(old, field, None):
                setattr(keep, field, getattr(old, field))
                print(f"    {old.id[:8]} → {field}")
        if WRITE:
            db.delete(old)

print(f"\n{len(dupes)} name(s) duplicated, {moved_total} row(s) to move")
if WRITE:
    db.commit()
    print("✓ merged")
else:
    print("(dry run — pass --write)")
