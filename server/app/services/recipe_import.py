"""Import a recipe from a web page.

Most recipe sites publish the recipe as schema.org/Recipe JSON-LD for search
engines: title, ingredient lines, steps, times. That is read directly (no AI).
A page without it is read by the household's ChatGPT from its visible text.
Ingredient lines ("2 cups all-purpose flour, sifted") are split into an amount
("2 cups") and the thing to buy ("all-purpose flour"), which is matched to the
pantry like 'What can I cook?' ideas are.
"""
import html as htmllib
import ipaddress
import json
import re
import socket
from urllib.parse import urlparse

import httpx

UA = "Mozilla/5.0 (Kasita recipe import; self-hosted)"
MAX_BYTES = 3_000_000


class ImportError_(ValueError):
    pass


def _check_url(url: str) -> str:
    """http(s) to a public host only: the server must not be talked into fetching its own network."""
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ImportError_("That is not a web link")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror as e:
        raise ImportError_(f"Can't find {u.hostname}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ImportError_("That link points into a private network")
    return url.strip()


def fetch(url: str) -> str:
    url = _check_url(url)
    try:
        with httpx.Client(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as c:
            r = c.get(url)
            for hop in r.history:  # a redirect must not lead into the private network either
                _check_url(str(hop.headers.get("location") or hop.url))
            _check_url(str(r.url))
    except httpx.HTTPError as e:
        raise ImportError_(f"Could not open the page ({e.__class__.__name__})") from e
    if r.status_code >= 400:
        raise ImportError_(f"The page answered {r.status_code}")
    return r.text[:MAX_BYTES]


def _iter_nodes(data):
    if isinstance(data, list):
        for x in data:
            yield from _iter_nodes(x)
    elif isinstance(data, dict):
        yield data
        for k in ("@graph", "mainEntity", "itemListElement"):
            if k in data:
                yield from _iter_nodes(data[k])


def _is_recipe(node: dict) -> bool:
    t = node.get("@type")
    return t == "Recipe" or (isinstance(t, list) and "Recipe" in t)


def _text(v) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))).strip()


def _steps(v) -> list[str]:
    out: list[str] = []
    if isinstance(v, str):
        out += [s for s in (_text(x) for x in re.split(r"\n+|(?<=\.)\s{2,}", v)) if s]
    elif isinstance(v, list):
        for x in v:
            out += _steps(x)
    elif isinstance(v, dict):
        if v.get("itemListElement"):  # HowToSection
            out += _steps(v["itemListElement"])
        elif v.get("text") or v.get("name"):
            out.append(_text(v.get("text") or v.get("name")))
    return out


def _minutes(iso: str | None) -> int | None:
    """"PT1H20M" -> 80."""
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", (iso or "").strip())
    if not m or not (m.group(1) or m.group(2)):
        return None
    return int(m.group(1) or 0) * 60 + int(m.group(2) or 0)


def from_json_ld(page: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for node in _iter_nodes(data):
            if _is_recipe(node) and node.get("recipeIngredient"):
                y = node.get("recipeYield")
                return {"title": _text(node.get("name"))[:160] or "Imported recipe",
                        "minutes": _minutes(node.get("totalTime")) or _minutes(node.get("cookTime")),
                        "servings": _text(y[0] if isinstance(y, list) and y else y)[:40] or None,
                        "ingredients": [_text(x) for x in node["recipeIngredient"] if _text(x)][:60],
                        "steps": _steps(node.get("recipeInstructions"))[:40]}
    return None


def page_text(page: str) -> str:
    page = re.sub(r"<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    return _text(page)[:24000]


_UNITS = (r"cups?|c\.|tablespoons?|tbsps?|tbs|tbsp\.|teaspoons?|tsps?|tsp\.|grams?|g|kg|kilograms?|ml|millilit(?:er|re)s?|"
          r"l|lit(?:er|re)s?|oz|ounces?|lbs?|pounds?|pinch(?:es)?|dash(?:es)?|cloves?|cans?|tins?|packages?|"
          r"packets?|sticks?|slices?|bunch(?:es)?|sprigs?|handfuls?|pieces?|large|medium|small|whole|heads?|"
          r"stalks?|eetlepels?|theelepels?|el|tl|gram|snufje")
_AMOUNT = re.compile(rf"^\s*((?:[\d¼½¾⅓⅔⅛]+(?:[\s/.,-]+[\d¼½¾⅓⅔⅛]+)*)\s*(?:(?:{_UNITS})\b\.?)?(?:\s*\([^)]*\))?)\s*(?:of\s+)?",
                     re.I)


def split_ingredient(line: str) -> tuple[str | None, str]:
    """"2 cups all-purpose flour, sifted" -> ("2 cups", "all-purpose flour").
    "Salt and pepper to taste" -> (None, "Salt and pepper")."""
    line = _text(line)
    amount = None
    m = _AMOUNT.match(line)
    if m and m.group(1).strip():
        amount, line = m.group(1).strip(), line[m.end():]
    item = re.split(r",|\(| - | – |\bto taste\b|\bfor serving\b|\boptional\b", line, maxsplit=1)[0].strip(" .;:")
    return (amount[:60] if amount else None), (item or line)[:160]


AI_INSTRUCTIONS = """You read a recipe from the visible text of a web page and reply with ONLY a JSON object:
{"title": string, "minutes": number|null, "servings": string|null,
 "ingredients": [{"item": string, "amount": string|null}], "steps": [string]}
- "item": the thing to buy, in English, short ("all-purpose flour", "chicken thighs"); "amount" as written ("2 cups").
- Translate to English if the page is in another language. Keep at most 40 steps.
- If the text holds no recipe: {"title": null}."""


def from_ai(db, household_id: str, text: str) -> dict | None:
    """Tests replace this function."""
    from . import chatgpt, codex
    from .receipts import extract_json
    secret = chatgpt.fresh_secret(db, household_id)
    got = extract_json(codex.respond(secret, chatgpt.model_for(db, household_id), AI_INSTRUCTIONS, [
        {"type": "input_text", "text": text}], timeout=90))
    if not got.get("title"):
        return None
    return {"title": str(got["title"])[:160], "minutes": got.get("minutes"), "servings": got.get("servings"),
            "ingredients": [(i.get("amount"), i.get("item")) for i in got.get("ingredients") or [] if i.get("item")],
            "steps": [str(s) for s in got.get("steps") or []][:40]}


def read(db, household_id: str, url: str) -> dict:
    """{"title", "minutes", "servings", "ingredients": [(amount, item)], "steps", "via": "page"|"chatgpt"}"""
    page = fetch(url)
    r = from_json_ld(page)
    if r:
        r["ingredients"] = [split_ingredient(x) for x in r["ingredients"]]
        r["via"] = "page"
        return r
    from . import codex
    try:
        r = from_ai(db, household_id, f"Page: {url}\n\n{page_text(page)}")
    except codex.CodexError as e:
        raise ImportError_(f"The page has no recipe data, and ChatGPT could not read it: {e}") from e
    if not r:
        raise ImportError_("No recipe found on that page")
    r["via"] = "chatgpt"
    return r
