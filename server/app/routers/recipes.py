"""Saved recipes, 'Cooked it', and the week's meal plan."""
import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import MealPlan, Product, Recipe, RecipeIngredient, ShoppingItem
from ..services import stock as svc

router = APIRouter(prefix="/api/households/{household_id}", tags=["recipes"])


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    minutes: int | None = None
    steps: list[str] = []
    uses: list[str] = []      # pantry product names (as 'What can I cook?' lists them)
    missing: list[str] = []   # things to buy


class CookedItem(BaseModel):
    product_id: str
    quantity: Decimal = Field(gt=0)


class CookedIn(BaseModel):
    items: list[CookedItem]


class PlanIn(BaseModel):
    recipe_id: str | None = None
    note: str | None = Field(default=None, max_length=160)


def _recipe(db: Session, hid: str, rid: str) -> Recipe:
    r = db.get(Recipe, rid)
    if not r or r.household_id != hid:
        raise HTTPException(404, "Recipe not found")
    return r


def _out(db: Session, r: Recipe) -> dict:
    ings = []
    for i in r.ingredients:
        have = svc.in_stock(db, i.product_id) if i.product_id else Decimal(0)
        ings.append({"id": i.id, "name": i.name, "product_id": i.product_id, "quantity": i.quantity,
                     "amount": i.amount, "in_stock": have, "have": bool(i.product_id) and have >= i.quantity})
    return {"id": r.id, "title": r.title, "minutes": r.minutes, "steps": r.steps or [], "ingredients": ings,
            "ready": all(x["have"] for x in ings), "source_url": r.source_url, "servings": r.servings}


def _match(products: list[Product], name: str) -> Product | None:
    """'Chicken wings 6 ct' as the AI wrote it -> the household's product (exact, then contained,
    then on whole words: "all-purpose flour" finds "Flour", not "Flour tortillas" over "Flour")."""
    low = name.strip().lower()
    if not low:
        return None
    for p in products:
        if p.name.lower() == low:
            return p
    for p in sorted(products, key=lambda p: -len(p.name)):
        pn = p.name.lower()
        if re.search(rf"\b{re.escape(pn)}\b", low) or re.search(rf"\b{re.escape(low)}\b", pn):
            return p  # whole words: "salted butter" is not "Salt"
    return None


@router.get("/recipes")
def list_recipes(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    rows = db.scalars(select(Recipe).where(Recipe.household_id == a.household.id).order_by(Recipe.title)).all()
    return [_out(db, r) for r in rows]


@router.post("/recipes", status_code=201)
def save_recipe(body: RecipeIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    products = db.scalars(select(Product).where(Product.household_id == a.household.id,
                                                Product.archived.is_(False))).all()
    r = Recipe(household_id=a.household.id, title=body.title.strip(), minutes=body.minutes,
               steps=[s.strip() for s in body.steps if s.strip()][:20])
    for n, name in enumerate(body.uses + body.missing):
        p = _match(products, name) if n < len(body.uses) else None
        r.ingredients.append(RecipeIngredient(position=n, name=(p.name if p else name.strip())[:160],
                                              product_id=p.id if p else None, quantity=Decimal(1)))
    db.add(r)
    db.commit()
    return _out(db, r)


class ImportIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post("/recipes/import", status_code=201)
def import_recipe(body: ImportIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """A recipe from a web page: its schema.org data, else ChatGPT reads the page. Ingredients are
    matched to the pantry; what isn't there can go on the list with 'Plan' / 'Missing to list'."""
    from ..services import recipe_import as ri
    try:
        got = ri.read(db, a.household.id, body.url)
    except ri.ImportError_ as e:
        raise HTTPException(422, str(e)) from e
    products = db.scalars(select(Product).where(Product.household_id == a.household.id,
                                                Product.archived.is_(False))).all()
    r = Recipe(household_id=a.household.id, title=got["title"], minutes=got.get("minutes"),
               steps=got.get("steps") or [], source_url=body.url.strip()[:2000],
               servings=(str(got["servings"])[:40] if got.get("servings") else None))
    for n, (amount, item) in enumerate(got["ingredients"]):
        p = _match(products, item)
        r.ingredients.append(RecipeIngredient(position=n, name=item[:160], amount=(amount or None),
                                              product_id=p.id if p else None, quantity=Decimal(1)))
    db.add(r)
    db.commit()
    return {**_out(db, r), "via": got["via"]}


@router.post("/recipes/{recipe_id}/missing-to-list")
def missing_to_list(recipe_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Everything this recipe needs that the pantry lacks, onto the shopping list (no duplicates)."""
    r = _recipe(db, a.household.id, recipe_id)
    open_items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == a.household.id,
                                                       ShoppingItem.done.is_(False))).all()
    on_list = {x.product_id for x in open_items if x.product_id} | {x.name.lower() for x in open_items}
    added = []
    for i in r.ingredients:
        have = svc.in_stock(db, i.product_id) if i.product_id else Decimal(0)
        if have >= i.quantity or i.product_id in on_list or i.name.lower() in on_list:
            continue
        db.add(ShoppingItem(household_id=a.household.id, product_id=i.product_id, name=i.name,
                            note=f"for {r.title}"[:255], added_by=a.user.id))
        added.append(i.name)
    db.commit()
    return {"added": added}


@router.get("/recipes/{recipe_id}")
def get_recipe(recipe_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return _out(db, _recipe(db, a.household.id, recipe_id))


@router.delete("/recipes/{recipe_id}", status_code=204)
def delete_recipe(recipe_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    db.delete(_recipe(db, a.household.id, recipe_id))
    db.commit()


@router.post("/recipes/{recipe_id}/cooked")
def cooked(recipe_id: str, body: CookedIn, a: HouseholdAccess = Depends(household_access),
           db: Session = Depends(get_db)):
    """Take what the meal used out of the pantry (amounts confirmed in the app). Returns event ids for Undo."""
    _recipe(db, a.household.id, recipe_id)
    events: list = []
    short = []
    for item in body.items:
        p = svc.get_product(db, a.household.id, item.product_id)
        taken = svc.consume(db, a.household.id, a.user.id, p, item.quantity, events=events)
        if taken < item.quantity:
            short.append(p.name)
    db.commit()
    return {"event_ids": [e.id for e in events], "short": short}


@router.get("/plan")
def get_plan(start: date | None = None, days: int = 7, a: HouseholdAccess = Depends(household_access),
             db: Session = Depends(get_db)):
    start = start or date.today()
    days = max(1, min(days, 31))
    rows = {m.day: m for m in db.scalars(select(MealPlan).where(
        MealPlan.household_id == a.household.id, MealPlan.day >= start, MealPlan.day < start + timedelta(days=days)))}
    out = []
    for n in range(days):
        d = start + timedelta(days=n)
        m = rows.get(d)
        r = db.get(Recipe, m.recipe_id) if m and m.recipe_id else None
        out.append({"day": d, "note": m.note if m else None, "recipe": _out(db, r) if r else None})
    return out


@router.put("/plan/{day}")
def set_plan(day: date, body: PlanIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    if body.recipe_id:
        _recipe(db, a.household.id, body.recipe_id)
    m = db.scalar(select(MealPlan).where(MealPlan.household_id == a.household.id, MealPlan.day == day))
    if not body.recipe_id and not body.note:
        if m:
            db.delete(m)
        db.commit()
        return {"day": day, "recipe": None, "note": None}
    if m is None:
        m = MealPlan(household_id=a.household.id, day=day)
        db.add(m)
    m.recipe_id, m.note = body.recipe_id, (body.note or None)
    db.commit()
    return {"day": day, "recipe_id": m.recipe_id, "note": m.note}


class AutoPlanIn(BaseModel):
    start: date | None = None
    days: int = Field(default=7, ge=1, le=10)
    note: str | None = Field(default=None, max_length=200)
    budget: Decimal | None = Field(default=None, gt=0)


@router.post("/plan/suggest")
def plan_suggest(body: AutoPlanIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """A proposed week of dinners from the pantry and the cheapest known prices. Saves nothing: apply it with POST /plan/apply."""
    from ..services import codex, mealplan
    try:
        return mealplan.propose(db, a.household.id, body.start, body.days, body.note, body.budget, match=_match)
    except codex.CodexError as e:
        raise HTTPException(502, str(e)) from e
    except (ValueError, KeyError) as e:
        raise HTTPException(422, f"Could not plan: {e}") from e


class ApplyDay(BaseModel):
    day: date
    title: str = Field(min_length=1, max_length=120)
    minutes: int = 0
    uses: list[dict] = []   # [{"name", "product_id"}]
    buy: list[dict] = []    # [{"name", "product_id", "repeat"}]
    steps: list[str] = []


class ApplyPlanIn(BaseModel):
    days: list[ApplyDay] = Field(min_length=1, max_length=10)


@router.post("/plan/apply")
def plan_apply(body: ApplyPlanIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Accept a proposal: one recipe per dinner, the week plan filled in, and what is missing put on the shopping list."""
    products = {p.id: p for p in db.scalars(select(Product).where(Product.household_id == a.household.id))}
    open_items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == a.household.id,
                                                       ShoppingItem.done.is_(False))).all()
    on_list = {x.product_id for x in open_items if x.product_id} | {x.name.lower() for x in open_items}
    added, made = [], 0
    for d in body.days:
        r = Recipe(household_id=a.household.id, title=d.title.strip(), minutes=d.minutes or None,
                   steps=[x.strip() for x in d.steps if x.strip()][:20])
        n = 0
        for u in d.uses:
            pid = u.get("product_id") if u.get("product_id") in products else None
            r.ingredients.append(RecipeIngredient(position=n, name=str(u.get("name", ""))[:160], product_id=pid, quantity=Decimal(1)))
            n += 1
        for b in d.buy:
            pid = b.get("product_id") if b.get("product_id") in products else None
            name = str(b.get("name", "")).strip()[:160]
            if not name:
                continue
            r.ingredients.append(RecipeIngredient(position=n, name=name, product_id=pid, quantity=Decimal(1)))
            n += 1
            key = pid or name.lower()
            if key in on_list or name.lower() in on_list:
                continue
            db.add(ShoppingItem(household_id=a.household.id, product_id=pid, name=products[pid].name if pid else name,
                                note=f"for {d.day:%a}: {d.title}"[:255], added_by=a.user.id))
            on_list.add(key)
            added.append(name)
        db.add(r)
        db.flush()
        m = db.scalar(select(MealPlan).where(MealPlan.household_id == a.household.id, MealPlan.day == d.day))
        if m is None:
            m = MealPlan(household_id=a.household.id, day=d.day)
            db.add(m)
        m.recipe_id, m.note = r.id, None
        made += 1
    db.commit()
    return {"recipes": made, "added_to_list": added}


@router.post("/plan/shopping")
def plan_to_shopping(start: date | None = None, days: int = 7, a: HouseholdAccess = Depends(household_access),
                     db: Session = Depends(get_db)):
    """Put everything the planned meals need but the pantry lacks on the shopping list (no duplicates)."""
    start = start or date.today()
    plan = db.scalars(select(MealPlan).where(MealPlan.household_id == a.household.id, MealPlan.day >= start,
                                             MealPlan.day < start + timedelta(days=max(1, min(days, 31))),
                                             MealPlan.recipe_id.is_not(None))).all()
    need: dict[str, tuple[str | None, str, Decimal]] = {}  # key -> (product_id, name, quantity)
    for m in plan:
        for i in db.get(Recipe, m.recipe_id).ingredients:
            key = i.product_id or i.name.lower()
            pid, name, q = need.get(key, (i.product_id, i.name, Decimal(0)))
            need[key] = (pid, name, q + i.quantity)
    open_items = db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == a.household.id,
                                                       ShoppingItem.done.is_(False))).all()
    on_list = {x.product_id for x in open_items if x.product_id} | {x.name.lower() for x in open_items}
    added = []
    for key, (pid, name, q) in need.items():
        have = svc.in_stock(db, pid) if pid else Decimal(0)
        if have >= q or key in on_list or name.lower() in on_list:
            continue
        db.add(ShoppingItem(household_id=a.household.id, product_id=pid, name=name, quantity=max(q - have, Decimal(1)),
                            note="for the week's meals", added_by=a.user.id))
        added.append(name)
    db.commit()
    return {"added": added}
