"""A short, fixed list of household categories, and a guess from a product's name.

The public databases disagree (Open Food Facts gives "Colas, pt:bebidas
cafeína", UPCitemdb often nothing), so Kasita keeps its own dozen categories
and picks one from keywords in the name plus whatever category text the
database gave. Order matters: the first matching group wins, so "ice cream"
lands in Frozen before "cream" can make it Dairy, and beer is Alcohol, not Drinks.
"""
import re

CATEGORIES = [
    "Produce", "Dairy & eggs", "Meat & fish", "Bakery", "Pantry", "Snacks & sweets", "Drinks", "Alcohol",
    "Frozen", "Personal care", "Household & cleaning", "Baby", "Pet", "Health", "Other",
]

# when neither the name nor the category text says anything: what the source database itself holds
SOURCE_DEFAULT = {"openbeautyfacts": "Personal care"}

_RULES: list[tuple[str, list[str]]] = [
    ("Drinks", ["root beer", "ginger beer", "ginger ale", "non-alcoholic", "alcohol-free"]),
    ("Alcohol", ["beer", "wine", "rum", "whisky", "whiskey", "vodka", "gin", "tequila", "liqueur", "cerveza",
                 "bier", "alcoholic beverage", "spirit", "champagne", "cider", "brandy", "cognac", "prosecco"]),
    ("Baby", ["baby", "infant", "diaper", "nappy", "pampers", "huggies", "baby formula", "wipes baby"]),
    ("Pet", ["dog food", "cat food", "pet food", "pet", "puppy", "kitten", "pedigree", "whiskas", "friskies",
             "cat litter"]),
    ("Health", ["vitamin", "supplement", "paracetamol", "acetaminophen", "ibuprofen", "aspirin", "medicine",
                "pain relief", "bandage", "plaster", "antacid", "cough"]),
    ("Personal care", ["deodorant", "anti-perspirant", "antiperspirant", "shampoo", "conditioner", "toothpaste",
                       "toothbrush", "mouthwash", "dental floss", "lotion", "razor", "shaving", "body wash",
                       "shower gel", "bar soap", "hand soap", "cosmetic", "beauty", "hygiene", "sanitary pad",
                       "tampon", "cotton swab", "cotton bud", "skin care", "sunscreen", "sunblock", "hair gel",
                       "hair care", "perfume", "cologne", "lip balm", "nail"]),
    ("Household & cleaning", ["detergent", "laundry", "bleach", "cleaner", "cleaning", "dishwashing", "dish soap",
                              "toilet paper", "toilet tissue", "paper towel", "kitchen roll", "trash bag",
                              "garbage bag", "bin bag", "aluminium foil", "aluminum foil", "cling film", "sponge",
                              "fabric softener", "air freshener", "insecticide", "bug spray", "battery", "batteries",
                              "light bulb", "napkin", "disinfectant", "household"]),
    # shelf-stable things whose names contain a fresh-food word ("peanut BUTTER", "chicken SOUP")
    ("Pantry", ["peanut butter", "coconut milk", "condensed milk", "evaporated milk", "soup", "noodle",
                "bouillon", "stock cube", "canned", "tinned"]),
    ("Frozen", ["frozen", "ice cream", "ice-cream", "popsicle", "ice pop"]),
    ("Dairy & eggs", ["milk", "cheese", "yogurt", "yoghurt", "butter", "cream", "egg", "dairy", "kefir",
                      "margarine", "cream cheese", "sour cream", "custard"]),
    ("Meat & fish", ["meat", "chicken", "beef", "pork", "sausage", "ham", "bacon", "salami", "fish", "salmon",
                     "shrimp", "prawn", "seafood", "turkey", "hot dog", "mince", "steak", "tuna"]),
    ("Bakery", ["bread", "bun", "bagel", "tortilla", "croissant", "cake", "bakery", "pastry", "muffin", "roll",
                "pan dulce", "brood"]),
    ("Snacks & sweets", ["chips", "crisps", "chocolate", "candy", "sweets", "cookie", "biscuit", "snack",
                         "cracker", "chewing gum", "gum", "confectionery", "nut", "popcorn", "pretzel", "wafer",
                         "gummy", "lollipop", "cacao", "cocoa bar"]),
    ("Drinks", ["water", "juice", "soda", "cola", "beverage", "drink", "coffee", "tea", "lemonade",
                "soft drink", "malta", "energy drink", "ginger ale", "root beer", "iced tea", "sparkling", "tonic", "nectar"]),
    ("Produce", ["fruit", "vegetable", "apple", "banana", "tomato", "onion", "potato", "lettuce", "fresh produce",
                 "carrot", "lemon", "lime", "orange", "garlic", "pepper", "cucumber", "avocado", "mango",
                 "plantain", "herb"]),
    ("Pantry", ["rice", "pasta", "spaghetti", "flour", "sugar", "salt", "oil", "sauce", "spice", "cereal",
                "bean", "canned", "soup", "ketchup", "mayonnaise", "noodle", "oat", "honey", "jam",
                "peanut butter", "condiment", "seasoning", "vinegar", "stock cube", "bouillon", "corn meal",
                "cornmeal", "mustard", "grocery", "groceries", "food"]),
]

# "\bword" + optional plural, then a boundary, so "gin" does not match "ginger"
_COMPILED = [(cat, re.compile(r"\b(?:" + "|".join(re.escape(k) + r"(?:s|es)?" for k in kws) + r")\b"))
             for cat, kws in _RULES]


def guess(name: str | None, categories: str | None = None) -> str | None:
    """Best category for a product, or None when nothing matches."""
    # the database's own category text says more than the name, so try it first
    for text in (categories, name):
        if not text:
            continue
        low = re.sub(r"\b[a-z]{2}:", " ", text.lower())  # drop OFF language prefixes like "en:"
        for cat, rx in _COMPILED:
            if rx.search(low):
                return cat
    return None
