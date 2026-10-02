"""Receipt lines that name a shop department, not a product.

Small shops here (many of them Chinese minimarkets) ring things up by POS
department: "FRUTA / BERDURA 7.25", "COMESTIBELS 7.99", "WEBU / ARINA 6.75".
The same text means something different every time, so such a line must never
be remembered as "this text is that product". It is recognised three ways:

1. the receipt AI marks it with kind "department" (see receipts.INSTRUCTIONS);
2. the words below: a line made up only of department words is one;
3. per store, learned: a text that was linked to two different products
   (`ReceiptDepartment`, written when a receipt is booked).

The same words give a department its likely categories ("WEBU / ARINA" is
eggs and flour: Dairy & eggs, then Pantry), which helps pick the line a
scanned product belongs on and is the default category for spending only.
"""
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ReceiptDepartment
from . import categories

# word -> categories it suggests, most likely first. Papiamentu, Spanish, Dutch and English POS words.
WORDS: dict[str, list[str]] = {}


def _add(cats: list[str], *words: str) -> None:
    for w in words:
        WORDS[w] = cats


_add(["Produce"], "FRUTA", "FRUTAS", "FRUIT", "FRUITS", "BERDURA", "BERDURAS", "VERDURA", "VERDURAS", "GROENTE",
     "GROENTEN", "GROENTES", "VEGETABLES", "VEGETABLE", "VEGGIES", "PRODUCE", "LEGUMES", "HORTALIZAS", "AGF")
_add(["Pantry"], "AROS", "ARROZ", "RIJST", "BONCHI", "BONCHIS", "FRIJOL", "FRIJOLES", "HABICHUELAS", "BONEN")
_add(["Dairy & eggs", "Pantry"], "WEBU", "WEBUS", "HUEVO", "HUEVOS", "EIEREN", "EGGS")
_add(["Pantry", "Bakery"], "ARINA", "HARINA", "MEEL", "BLOEM", "FLOUR")
_add(["Pantry", "Snacks & sweets", "Drinks", "Dairy & eggs", "Household & cleaning"],
     "COMESTIBELS", "COMESTIBEL", "COMESTIBLE", "COMESTIBLES", "KOMESTIBEL", "KOMESTIBELS", "KUMESTIBEL",
     "KUMESTIBELS", "ABARROTES", "VIVERES", "GROCERY", "GROCERIES", "KRUIDENIERS", "KRUIDENIERSWAREN",
     "LEVENSMIDDELEN", "ALIMENTOS", "FOOD", "KUMINDA", "KUMIDA")
_add(["Meat & fish"], "KARNI", "CARNE", "CARNES", "VLEES", "MEAT", "PISKA", "PESCADO", "FISH", "CHARCUTERIA",
     "SLAGERIJ", "BUTCHER", "DELI", "VLEESWAREN", "CARNICERIA")
_add(["Dairy & eggs"], "LECHI", "LECHE", "MELK", "KESO", "QUESO", "KAAS", "ZUIVEL", "DAIRY", "LACTEOS")
_add(["Bakery"], "BAKERY", "PANADERIA", "BAKKERIJ", "PASTELERIA")
_add(["Drinks"], "BEBIDA", "BEBIDAS", "BIBIDA", "BIBIDAS", "REFRESCO", "REFRESCOS", "FRISDRANK", "FRISDRANKEN",
     "DRANK", "DRANKEN", "DRINKS", "BEVERAGES")
_add(["Alcohol"], "CERVEZA", "CERVEZAS", "SERBES", "BIER", "LICOR", "LICORES", "LIQUOR", "STERKEDRANK", "WIJN",
     "VINO", "BIÑA", "BINA", "ALCOHOL")
_add(["Snacks & sweets"], "DULCES", "SNOEP", "SNACKS", "GALLETAS", "KOEKJES", "CANDY", "CHUCHERIAS", "GOLOSINAS")
_add(["Frozen"], "FROZEN", "CONGELADO", "CONGELADOS", "DIEPVRIES", "FREEZER")
_add(["Household & cleaning"], "LIMPIEZA", "LIMPIA", "SCHOONMAAK", "HUISHOUD", "HUISHOUDELIJK", "HOUSEHOLD",
     "CLEANING", "FERETERIA", "FERRETERIA", "HARDWARE", "BAZAR")
_add(["Personal care"], "HIGIENE", "COSMETICA", "COSMETICOS", "COSMETICS", "DROGISTERIJ", "PERFUMERIA",
     "TOILETRIES", "BELLEZA")
_add(["Health"], "FARMACIA", "BOTICA", "APOTHEEK", "PHARMACY", "MEDICINA")
_add(["Pet"], "MASCOTA", "MASCOTAS", "DIERENVOER")
_add(["Other"], "DEPT", "DEPTO", "DEPARTAMENTO", "DEPARTMENT", "AFDELING", "DEP", "MISC", "MISCELLANEOUS",
     "DIVERSEN", "DIVERSOS", "VARIOS", "VARIA", "OTROS", "OTRO", "OVERIG", "OVERIGE", "GENERAL", "ALGEMEEN",
     "GENERICO", "ITEM", "ARTICULO", "ARTIKEL")

# glue words that may sit between department words ("FRUTA Y BERDURA", "AROS & BONCHI", "BROOD EN BANKET")
_GLUE = {"Y", "I", "E", "EN", "AND", "N", "DI", "DE", "DEL", "LA", "LAS", "LOS", "Ñ"}
# a department number is only allowed next to a word that says "department" ("DEPT 03")
_NUMBERED = {"DEPT", "DEPTO", "DEPARTAMENTO", "DEPARTMENT", "AFDELING", "DEP", "ITEM", "ARTICULO", "ARTIKEL",
             "GENERAL"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^0-9A-ZÑ]+", (text or "").upper()) if t]


def is_department_text(text: str) -> bool:
    """True when every word of the line is a department word (numbers only after DEPT and the like)."""
    toks = [t for t in _tokens(text) if t not in _GLUE]
    words = [t for t in toks if not t.isdigit()]
    if not words or any(w not in WORDS for w in words):
        return False
    if len(words) < len(toks) and not any(w in _NUMBERED for w in words):
        return False
    return True


def likely_categories(raw_text: str, name: str | None = None) -> list[str]:
    """Categories this department (or line) most likely holds, best first."""
    out: list[str] = []
    for t in _tokens(raw_text):
        for c in WORDS.get(t, []):
            if c not in out:
                out.append(c)
    if not out:
        g = categories.guess(name) or categories.guess(raw_text)
        if g:
            out.append(g)
    # "Other" only when nothing better was said
    return [c for c in out if c != "Other"] or out


def default_category(raw_text: str, name: str | None = None) -> str:
    cats = likely_categories(raw_text, name)
    return cats[0] if cats else "Other"


def learned(db: Session, household_id: str, store_id: str | None, key: str) -> ReceiptDepartment | None:
    return db.scalar(select(ReceiptDepartment).where(
        ReceiptDepartment.household_id == household_id,
        ReceiptDepartment.store_id.is_(None) if store_id is None else ReceiptDepartment.store_id == store_id,
        ReceiptDepartment.text_key == key))


def learn(db: Session, household_id: str, store_id: str | None, key: str) -> None:
    if key and learned(db, household_id, store_id, key) is None:
        db.add(ReceiptDepartment(household_id=household_id, store_id=store_id, text_key=key))
        db.flush()


def forget(db: Session, household_id: str, store_id: str | None, key: str) -> None:
    row = learned(db, household_id, store_id, key)
    if row is not None:
        db.delete(row)
        db.flush()
