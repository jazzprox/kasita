"""Kasita as an MCP server, for AI agents (OpenClaw, Hermes, Claude...).

MCP's Streamable HTTP transport, the small stateless part of it: the agent POSTs
JSON-RPC 2.0 to /mcp and gets JSON back (no server-sent events, no sessions).
Authentication is a Kasita API key (More → Settings → API keys), sent as
`Authorization: Bearer ksk_...` or `X-Api-Key: ksk_...`; the key decides the
household. A read-only key gets the read tools only.

Connect, e.g. Claude Code:
  claude mcp add --transport http kasita https://kasita.jazzproxy.com/mcp \
      --header "Authorization: Bearer ksk_..."
"""
import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ApiKey, Household, Membership, Product, ShoppingItem, StockEntry
from ..security import token_hash

log = logging.getLogger("kasita.mcp")
router = APIRouter(tags=["mcp"])

PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]  # newest first
SERVER = {"name": "kasita", "title": "Kasita pantry", "version": "1.0.0"}
INSTRUCTIONS = ("Kasita is a household's pantry, shopping list and grocery spending (currency in each answer). "
                "Product and item names are matched loosely, so plain names work ('milk', 'rice').")


# --- the tools ----------------------------------------------------------------------
class Ctx:
    def __init__(self, db: Session, key: ApiKey):
        self.db, self.key = db, key
        self.hid, self.user_id = key.household_id, key.user_id
        self.household = db.get(Household, key.household_id)


def _num(x) -> float | None:
    return None if x is None else float(x)


def _find_product(c: Ctx, name: str) -> Product | None:
    low = name.strip().lower()
    rows = list(c.db.scalars(select(Product).where(Product.household_id == c.hid, Product.archived.is_(False),
                                                   or_(Product.name.ilike(f"%{low}%"), Product.brand.ilike(f"%{low}%")))))
    exact = [p for p in rows if p.name.lower() == low]
    return (exact or sorted(rows, key=lambda p: len(p.name)) or [None])[0]


def t_pantry(c: Ctx, args: dict) -> dict:
    from .stock import overview
    from ..deps import HouseholdAccess
    stock = overview(HouseholdAccess(household=c.household, user=None, role="member"), c.db)
    q = (args.get("search") or "").lower()
    items = [{"name": s.product.name, "quantity": _num(s.total), "unit": s.product.unit,
              "category": s.product.category,
              "next_best_before": s.product.next_best_before.isoformat() if s.product.next_best_before else None}
             for s in stock if not q or q in s.product.name.lower()]
    return {"items": items, "count": len(items)}


def t_expiring(c: Ctx, args: dict) -> dict:
    days = int(args.get("days") or 5)
    out = t_pantry(c, {})["items"]
    limit = date.today().toordinal() + days
    soon = [i for i in out if i["next_best_before"] and date.fromisoformat(i["next_best_before"]).toordinal() <= limit]
    return {"days": days, "items": sorted(soon, key=lambda i: i["next_best_before"])}


def t_shopping_list(c: Ctx, args: dict) -> dict:
    rows = c.db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == c.hid, ShoppingItem.done.is_(False))
                        .order_by(ShoppingItem.created_at))
    return {"items": [{"id": i.id, "name": i.name, "quantity": _num(i.quantity), "note": i.note,
                       "category": i.category, "running_low": i.auto} for i in rows]}


def t_add_to_list(c: Ctx, args: dict) -> dict:
    added = []
    for it in args.get("items") or []:
        name = (it.get("name") if isinstance(it, dict) else str(it)).strip()
        if not name:
            continue
        qty = Decimal(str(it.get("quantity") or 1)) if isinstance(it, dict) else Decimal(1)
        p = _find_product(c, name)
        c.db.add(ShoppingItem(household_id=c.hid, product_id=p.id if p and p.name.lower() == name.lower() else None,
                              name=name[:255], quantity=qty, note=(it.get("note") if isinstance(it, dict) else None),
                              added_by=c.user_id))
        added.append(name)
    c.db.commit()
    return {"added": added}


def t_tick(c: Ctx, args: dict) -> dict:
    from ..services import route
    name = (args.get("name") or "").strip().lower()
    rows = list(c.db.scalars(select(ShoppingItem).where(ShoppingItem.household_id == c.hid,
                                                        ShoppingItem.done.is_(False))))
    hit = next((i for i in rows if i.id == args.get("id")), None) or \
        next((i for i in rows if i.name.lower() == name), None) or \
        next((i for i in rows if name and name in i.name.lower()), None)
    if not hit:
        return {"error": f"Nothing like {args.get('name') or args.get('id')!r} is on the list"}
    tick = route.record(c.db, hit)
    hit.done, hit.done_at = True, tick.ticked_at
    c.db.commit()
    return {"ticked": hit.name}


def t_used(c: Ctx, args: dict) -> dict:
    from ..services import stock as svc
    p = _find_product(c, args.get("product") or "")
    if not p:
        return {"error": f"No product like {args.get('product')!r}"}
    taken = svc.consume(c.db, c.hid, c.user_id, p, Decimal(str(args.get("quantity") or 1)),
                        spoiled=bool(args.get("thrown_away")))
    c.db.commit()
    return {"product": p.name, "used": _num(taken), "left": _num(svc.in_stock(c.db, p.id))}


def t_product(c: Ctx, args: dict) -> dict:
    from .products import nutrition
    from ..services import prices, sizes
    p = _find_product(c, args.get("name") or "")
    if not p:
        return {"error": f"No product like {args.get('name')!r}"}
    from ..services.stock import in_stock
    info = prices.compare(prices.store_prices(c.db, c.hid, [p.id]).get(p.id))
    per = []
    for x in info["prices"]:
        b = sizes.per_base(x["price"], p)
        per.append({"store": x["store"], "price": _num(x["price"]), "on": x["on"].isoformat(),
                    "per_base": _num(b[0].quantize(Decimal("0.01"))) if b else None, "per": b[1] if b else None})
    return {"name": p.name, "brand": p.brand, "category": p.category, "unit": p.unit,
            "in_stock": _num(in_stock(c.db, p.id)), "latest_prices": per, "cheapest_store": info["cheapest_store"],
            "usual_store": info["usual_store"], **nutrition(c.db, p)}


def t_spending(c: Ctx, args: dict) -> dict:
    from ..services.digest import month_to_date, spending
    s = spending(c.db, c.hid, days=int(args.get("days") or 30))
    return {**json.loads(json.dumps(s, default=str)), "this_month": json.loads(json.dumps(month_to_date(c.db, c.hid),
                                                                                          default=str))}


def t_nutrition(c: Ctx, args: dict) -> dict:
    from ..services.nutrition import report
    return json.loads(json.dumps(report(c.db, c.hid, days=int(args.get("days") or 30)), default=str))


def t_recipes(c: Ctx, args: dict) -> dict:
    from .recipes import _out
    from ..models import Recipe
    rows = c.db.scalars(select(Recipe).where(Recipe.household_id == c.hid).order_by(Recipe.title))
    return {"recipes": [{k: v for k, v in json.loads(json.dumps(_out(c.db, r), default=str)).items()
                         if k in ("title", "minutes", "ready", "ingredients", "source_url")} for r in rows]}


def _schema(props: dict | None = None, required: list | None = None) -> dict:
    return {"type": "object", "properties": props or {}, **({"required": required} if required else {})}


TOOLS = [
    ("pantry", "What is at home: every product in stock with quantity and the soonest best-before date.",
     _schema({"search": {"type": "string", "description": "only products whose name contains this"}}), t_pantry, False),
    ("expiring", "Products at home that expire within N days (default 5), soonest first.",
     _schema({"days": {"type": "integer"}}), t_expiring, False),
    ("shopping_list", "The open shopping list.", _schema(), t_shopping_list, False),
    ("product", "One product: stock, latest price per store (also per kg / l), cheapest and usual store, "
                "Nutri-Score and nutrients.", _schema({"name": {"type": "string"}}, ["name"]), t_product, False),
    ("spending", "Grocery spending over the last N days (default 30) per category and store, plus this "
                 "month against the budget.", _schema({"days": {"type": "integer"}}), t_spending, False),
    ("nutrition", "The basket's health over N days: spending per Nutri-Score grade and NOVA group, top D/E buys.",
     _schema({"days": {"type": "integer"}}), t_nutrition, False),
    ("recipes", "Saved recipes with their ingredients and whether everything is at home.", _schema(), t_recipes, False),
    ("add_to_shopping_list", "Put items on the shopping list.",
     _schema({"items": {"type": "array", "items": {"type": "object", "properties": {
         "name": {"type": "string"}, "quantity": {"type": "number"}, "note": {"type": "string"}},
         "required": ["name"]}}}, ["items"]), t_add_to_list, True),
    ("tick_off", "Tick an item off the shopping list (bought), by name or id.",
     _schema({"name": {"type": "string"}, "id": {"type": "string"}}), t_tick, True),
    ("used", "Take something out of the pantry (eaten / used up, or thrown away).",
     _schema({"product": {"type": "string"}, "quantity": {"type": "number"},
              "thrown_away": {"type": "boolean"}}, ["product"]), t_used, True),
]


# --- the protocol --------------------------------------------------------------------
def _key(request: Request, db: Session) -> ApiKey | None:
    raw = request.headers.get("x-api-key") or ""
    auth = request.headers.get("authorization") or ""
    if not raw and auth.lower().startswith("bearer "):
        raw = auth[7:].strip()
    if not raw:
        return None
    key = db.scalar(select(ApiKey).where(ApiKey.key_hash == token_hash(raw)))
    if key is None:
        return None
    member = db.scalar(select(Membership).where(Membership.household_id == key.household_id,
                                                Membership.user_id == key.user_id))
    if member is None:  # the key's owner left the household
        return None
    key.last_used_at = datetime.now(timezone.utc)
    db.commit()
    return key


def _result(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(c: Ctx, msg: dict) -> dict | None:
    """One JSON-RPC message -> its response (None for a notification)."""
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if "id" not in msg:
        return None  # notifications (initialized, cancelled...) need no answer
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(mid, {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                             "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": SERVER, "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(mid, {})
    tools = [t for t in TOOLS if not (t[4] and c.key.read_only)]
    if method == "tools/list":
        return _result(mid, {"tools": [{"name": n, "description": d, "inputSchema": s,
                                        "annotations": {"readOnlyHint": not w}} for n, d, s, _, w in tools]})
    if method == "tools/call":
        tool = next((t for t in tools if t[0] == params.get("name")), None)
        if tool is None:
            return _error(mid, -32602, f"Unknown tool: {params.get('name')}")
        try:
            out = tool[3](c, params.get("arguments") or {})
        except Exception as e:  # noqa: BLE001 - a tool failure is reported to the agent, not a 500
            log.exception("mcp tool %s failed", tool[0])
            c.db.rollback()
            return _result(mid, {"content": [{"type": "text", "text": f"Failed: {e}"}], "isError": True})
        text = json.dumps(out, default=str, ensure_ascii=False)
        return _result(mid, {"content": [{"type": "text", "text": text}], "structuredContent": out,
                             "isError": "error" in out})
    return _error(mid, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp(request: Request, db: Session = Depends(get_db)):
    key = _key(request, db)
    if key is None:
        return JSONResponse({"error": "Send a Kasita API key: Authorization: Bearer ksk_..."}, status_code=401,
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse(_error(None, -32700, "Parse error"), status_code=400)
    c = Ctx(db, key)
    if isinstance(body, list):  # a batch
        out = [r for r in (handle(c, m) for m in body if isinstance(m, dict)) if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    if not isinstance(body, dict):
        return JSONResponse(_error(None, -32600, "Invalid request"), status_code=400)
    r = handle(c, body)
    return JSONResponse(r) if r is not None else Response(status_code=202)


@router.get("/mcp")
def mcp_stream():
    """No server-initiated stream: every answer comes back on the POST."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
def mcp_end():
    return Response(status_code=405, headers={"Allow": "POST"})
