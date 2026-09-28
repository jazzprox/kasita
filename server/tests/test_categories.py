import pytest

from app.services.categories import CATEGORIES, guess


@pytest.mark.parametrize("name,cats,want", [
    ("Dove Men Invisible Dry 48hr Anti-perspirant Deodorant Roll-on 50ml", None, "Personal care"),
    ("Coca-Cola", "Colas, pt:bebidas cafeína", "Drinks"),
    ("LIFEWTR", "Table waters", "Drinks"),
    ("Skippy creamy peanut butter", None, "Pantry"),
    ("Ben & Jerry's cookie dough ice cream", None, "Frozen"),
    ("Heineken lager beer 6 pack", None, "Alcohol"),
    ("Ginger ale", None, "Drinks"),
    ("Campbell's chicken noodle soup", None, "Pantry"),
    ("Goisco toilet paper 12 rolls", None, "Household & cleaning"),
    ("Whole milk 1 L", None, "Dairy & eggs"),
    ("Orange juice", None, "Drinks"),
    ("Bananas", None, "Produce"),
    ("Pringles Original", "en:snacks, en:salty-snacks, en:crisps", "Snacks & sweets"),
    ("XJ-500 thing", None, None),
])
def test_guess(name, cats, want):
    assert guess(name, cats) == want
    assert want is None or want in CATEGORIES


def test_barcode_lookup_suggests_category(client, jazz):
    h, hid = jazz
    r = client.get(f"/api/households/{hid}/barcodes/5449000000996", headers=h).json()  # Coca-Cola, "Sodas"
    assert r["category"] == "Drinks"
    cats = client.get(f"/api/households/{hid}/categories", headers=h).json()
    assert cats[0] == "Produce" and "Personal care" in cats


def test_beauty_database_defaults_to_personal_care():
    from app.services.categories import SOURCE_DEFAULT
    assert guess("AXE", None) is None and SOURCE_DEFAULT["openbeautyfacts"] == "Personal care"
