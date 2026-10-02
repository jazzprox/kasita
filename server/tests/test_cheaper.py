"""Cheaper elsewhere: latest fresh price per store vs where an item is usually bought."""
from datetime import date, timedelta


def _setup(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    ids = {n: client.post(f"{base}/stores", json={"name": n}, headers=h).json()["id"]
           for n in ("Centrum", "Mangusa", "Goisco")}
    return h, base, ids


def product(client, h, base, name):
    return client.post(f"{base}/products", json={"name": name}, headers=h).json()["id"]


def buy(client, h, base, pid, store, price, days_ago=1):
    r = client.post(f"{base}/stock/purchase", headers=h, json={
        "product_id": pid, "store_id": store, "unit_price": price,
        "purchased_at": (date.today() - timedelta(days=days_ago)).isoformat()})
    assert r.status_code in (200, 201), r.text


def listed(client, h, base, **body):
    client.post(f"{base}/shopping", json=body, headers=h)


def prices(client, h, base):
    return {x["name"]: x for x in client.get(f"{base}/shopping/prices", headers=h).json()}


def test_cheaper_at_another_store(client, jazz):
    h, base, s = _setup(client, jazz)
    coffee = product(client, h, base, "Coffee")
    for d in (40, 20, 5):
        buy(client, h, base, coffee, s["Centrum"], 7.15, days_ago=d)  # usually here
    buy(client, h, base, coffee, s["Mangusa"], 5.95, days_ago=10)
    listed(client, h, base, product_id=coffee)
    got = prices(client, h, base)["Coffee"]
    assert got["usual_store"] == "Centrum" and got["cheapest_store"] == "Mangusa"
    assert got["hint"] == "1.20 cheaper at Mangusa (last 5.95 vs 7.15)"
    assert [p["store"] for p in got["prices"]] == ["Mangusa", "Centrum"]
    split = client.get(f"{base}/shopping/by-store", headers=h).json()
    assert split[0]["store"] == "Mangusa" and split[0]["items"][0]["hint"].startswith("1.20 cheaper")


def test_stale_prices_are_ignored(client, jazz):
    h, base, s = _setup(client, jazz)
    rice = product(client, h, base, "Rice")
    buy(client, h, base, rice, s["Centrum"], 9.00, days_ago=3)
    buy(client, h, base, rice, s["Centrum"], 9.00, days_ago=30)
    buy(client, h, base, rice, s["Goisco"], 6.00, days_ago=200)  # cheap, but long ago
    listed(client, h, base, product_id=rice)
    got = prices(client, h, base)["Rice"]
    assert got["cheapest_store"] == "Centrum" and got["hint"] is None
    assert [p["store"] for p in got["prices"]] == ["Centrum"]


def test_latest_price_per_store_counts(client, jazz):
    h, base, s = _setup(client, jazz)
    milk = product(client, h, base, "Milk")
    buy(client, h, base, milk, s["Centrum"], 4.00, days_ago=60)
    buy(client, h, base, milk, s["Centrum"], 5.00, days_ago=2)   # went up
    buy(client, h, base, milk, s["Goisco"], 4.50, days_ago=30)
    listed(client, h, base, product_id=milk)
    got = prices(client, h, base)["Milk"]
    assert got["cheapest_store"] == "Goisco" and got["hint"] == "0.50 cheaper at Goisco (last 4.50 vs 5.00)"


def test_tie_goes_to_the_usual_store_without_a_hint(client, jazz):
    h, base, s = _setup(client, jazz)
    eggs = product(client, h, base, "Eggs")
    buy(client, h, base, eggs, s["Goisco"], 6.00, days_ago=9)
    buy(client, h, base, eggs, s["Goisco"], 6.00, days_ago=8)
    buy(client, h, base, eggs, s["Mangusa"], 6.00, days_ago=1)
    listed(client, h, base, product_id=eggs)
    got = prices(client, h, base)["Eggs"]
    assert got["cheapest_store"] == "Goisco" and got["usual_store"] == "Goisco" and got["hint"] is None


def test_items_without_prices(client, jazz):
    h, base, s = _setup(client, jazz)
    soap = product(client, h, base, "Soap")
    buy(client, h, base, soap, s["Mangusa"], None)  # bought, no price typed
    listed(client, h, base, product_id=soap)
    listed(client, h, base, name="birthday candles")
    got = prices(client, h, base)
    assert got["birthday candles"]["cheapest_store"] is None and got["birthday candles"]["prices"] == []
    assert got["Soap"]["cheapest_store"] is None and got["Soap"]["hint"] is None
    split = client.get(f"{base}/shopping/by-store", headers=h).json()
    assert [g["store"] for g in split] == ["Anywhere (no prices yet)"] and len(split[0]["items"]) == 2


def test_cheapest_only_at_one_store_has_no_hint(client, jazz):
    h, base, s = _setup(client, jazz)
    bread = product(client, h, base, "Bread")
    buy(client, h, base, bread, s["Mangusa"], 3.00)
    listed(client, h, base, product_id=bread)
    got = prices(client, h, base)["Bread"]
    assert got["cheapest_store"] == "Mangusa" and got["usual_store"] == "Mangusa" and got["hint"] is None
