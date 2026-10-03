"""Pack sizes, so prices compare per kilo / litre / piece across pack sizes and stores.

A product's size is what one unit of its stock holds ("1.5 l", "500 g", "12 rolls"),
read from the barcode database, the product name or typed in. Products sold by
weight (unit "kg", deli cheese and meat) are already priced per kilo.

Also: weighed-item barcodes. Deli and butcher scales print store-internal
barcodes (GS1 prefix 2): the item number and the price (sometimes the weight)
are IN the code, so the same cheese gives a different code every time. Kasita
keys those products by the item part only.
"""
import re
from decimal import Decimal, InvalidOperation

# to grams / millilitres / pieces
_UNITS = {
    "kg": ("g", Decimal(1000)), "kilo": ("g", Decimal(1000)), "kilogram": ("g", Decimal(1000)),
    "g": ("g", Decimal(1)), "gr": ("g", Decimal(1)), "gram": ("g", Decimal(1)), "grams": ("g", Decimal(1)),
    "mg": ("g", Decimal("0.001")),
    "lb": ("g", Decimal("453.592")), "lbs": ("g", Decimal("453.592")), "pound": ("g", Decimal("453.592")),
    "oz": ("g", Decimal("28.3495")),
    "l": ("ml", Decimal(1000)), "lt": ("ml", Decimal(1000)), "ltr": ("ml", Decimal(1000)),
    "liter": ("ml", Decimal(1000)), "litre": ("ml", Decimal(1000)), "liters": ("ml", Decimal(1000)),
    "litres": ("ml", Decimal(1000)),
    "ml": ("ml", Decimal(1)), "cl": ("ml", Decimal(10)), "dl": ("ml", Decimal(100)),
    "floz": ("ml", Decimal("29.5735")), "gal": ("ml", Decimal("3785.41")), "gallon": ("ml", Decimal("3785.41")),
    "pcs": ("pcs", Decimal(1)), "pc": ("pcs", Decimal(1)), "pieces": ("pcs", Decimal(1)), "ct": ("pcs", Decimal(1)),
    "count": ("pcs", Decimal(1)), "pk": ("pcs", Decimal(1)), "pack": ("pcs", Decimal(1)),
    "rolls": ("pcs", Decimal(1)), "roll": ("pcs", Decimal(1)), "r": ("pcs", Decimal(1)),
    "sheets": ("pcs", Decimal(1)), "bags": ("pcs", Decimal(1)), "tabs": ("pcs", Decimal(1)),
    "capsules": ("pcs", Decimal(1)), "eggs": ("pcs", Decimal(1)), "stuks": ("pcs", Decimal(1)),
}
_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(fl\.?\s?oz|kg|kilo(?:gram)?s?|grams?|gr|g|mg|lbs?|pounds?|oz|lt?r?|lit(?:er|re)s?|ml|cl|dl|gal(?:lons?)?|" \
        r"pcs|pc|pieces|ct|count|pk|pack|rolls?|r|sheets|bags|tabs|capsules|eggs|stuks)"
_MULTI = re.compile(rf"(\d+)\s*[x×*]\s*{_NUM}\s*{_UNIT}\b", re.I)
_SINGLE = re.compile(rf"{_NUM}\s*{_UNIT}\b", re.I)


def _unit(u: str) -> tuple[str, Decimal] | None:
    u = re.sub(r"[\s.]", "", u.lower())
    if u.startswith("floz"):
        u = "floz"
    u = {"kilograms": "kg", "kilos": "kg", "pounds": "lb", "gallons": "gal", "litr": "l", "liters": "l"}.get(u, u)
    return _UNITS.get(u)


def parse_size(text: str | None) -> tuple[Decimal, str] | None:
    """"1.5 l" -> (1500, "ml"); "6 x 330 ml" -> (1980, "ml"); "16.9 FL OZ" -> (499.8, "ml");
    "12 rolls" -> (12, "pcs"); "GSC TOILET PPR 12R" -> (12, "pcs"). None when no size is in it."""
    if not text:
        return None
    t = text.replace("×", "x")
    m = _MULTI.search(t)
    count = Decimal(1)
    if m:
        count, num, unit = Decimal(m.group(1)), m.group(2), m.group(3)
    else:
        # prefer weights/volumes over piece counts when both appear ("12 x 30 g bars, 360 g")
        hits = [(n, u) for n, u in _SINGLE.findall(t)]
        if not hits:
            return None
        hits.sort(key=lambda h: (_unit(h[1]) or ("pcs", 0))[0] == "pcs")
        num, unit = hits[0]
    conv = _unit(unit)
    if not conv:
        return None
    try:
        amount = Decimal(num.replace(",", ".")) * conv[1] * count
    except InvalidOperation:
        return None
    if amount <= 0:
        return None
    return amount.quantize(Decimal("0.001")), conv[0]


def per_base(unit_price: Decimal | None, product) -> tuple[Decimal, str] | None:
    """Price per kg / per l / per piece: (value, "kg" | "l" | "each"). None when the size is unknown.

    unit "kg" (weighed) is per kg already; "pcs" uses the pack size."""
    if unit_price is None:
        return None
    u = (product.unit or "pcs").lower()
    if u in ("kg", "kilo"):
        return unit_price, "kg"
    if u == "g":
        return unit_price * 1000, "kg"
    if u in ("l", "lt", "liter", "litre"):
        return unit_price, "l"
    if u == "ml":
        return unit_price * 1000, "l"
    if u in ("lb", "lbs"):
        return unit_price / Decimal("0.453592"), "kg"
    size, size_unit = getattr(product, "size_amount", None), getattr(product, "size_unit", None)
    if not size or size <= 0 or not size_unit:
        return None
    if size_unit == "g":
        return unit_price / size * 1000, "kg"
    if size_unit == "ml":
        return unit_price / size * 1000, "l"
    if size_unit == "pcs" and size > 1:
        return unit_price / size, "each"
    return None


def fill_size(product, *texts: str | None) -> bool:
    """Set the product's size from the first text that has one (database quantity, name). Never overwrites."""
    if product.size_amount:
        return False
    for t in texts:
        got = parse_size(t)
        if got:
            product.size_amount, product.size_unit = got
            return True
    return False


# --- weighed-item (variable measure) barcodes ------------------------------------
def _ean_ok(code: str) -> bool:
    """GTIN check digit (EAN-13 and UPC-A alike): the digit next to the check digit weighs 3."""
    body, check = [int(c) for c in code[:-1]], int(code[-1])
    total = sum(x * (3 if (len(body) - i) % 2 == 1 else 1) for i, x in enumerate(body))
    return (10 - total % 10) % 10 == check


def variable(code: str) -> dict | None:
    """A store-internal weighed-item barcode? {"key": item part, "value": embedded amount}.

    EAN-13 "2" + 1 + IIIII + VVVVV + check (Europe/Caribbean scales): item = first 7 digits,
    value = next 5 (cents, or grams on some scales). UPC-A "2" + IIIII + check + VVVV + check
    (US scales): item = first 6, value = 4 digits of cents. The value is usually the price."""
    if not code or not code.isdigit():
        return None
    if len(code) == 13 and code.startswith("02"):
        code = code[1:]  # a UPC-A read as EAN-13
    if len(code) == 13 and code[0] == "2" and _ean_ok(code):
        return {"key": "W" + code[:7], "value": Decimal(int(code[7:12])) / 100}
    if len(code) == 12 and code[0] == "2" and _ean_ok(code):
        return {"key": "W" + code[:6], "value": Decimal(int(code[7:11])) / 100}
    return None
