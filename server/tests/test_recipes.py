from datetime import date, timedelta


def _pantry(client, h, base):
    ids = {}
    for name, qty in (("Chicken wings 6 ct", 6), ("Fresh garlic 250 g", 1), ("Rice", 2)):
        ids[name] = client.post(f"{base}/products", json={"name": name}, headers=h).json()["id"]
        client.post(f"{base}/stock/purchase", json={"product_id": ids[name], "quantity": qty}, headers=h)
    return ids


def test_save_cook_and_undo(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    ids = _pantry(client, h, base)
    r = client.post(f"{base}/recipes", json={"title": "Garlic wings", "minutes": 40, "steps": ["Season", "Bake"],
                                             "uses": ["Chicken wings 6 ct", "fresh garlic"], "missing": ["lime"]},
                    headers=h).json()
    got = [(i["name"], i["product_id"] is not None, i["have"]) for i in r["ingredients"]]
    assert got == [("Chicken wings 6 ct", True, True), ("Fresh garlic 250 g", True, True), ("lime", False, False)]
    assert r["ready"] is False                                   # lime is missing
    done = client.post(f"{base}/recipes/{r['id']}/cooked", json={"items": [
        {"product_id": ids["Chicken wings 6 ct"], "quantity": 6},
        {"product_id": ids["Fresh garlic 250 g"], "quantity": 0.5}]}, headers=h).json()
    stock = lambda pid: float(client.get(f"{base}/products/{pid}", headers=h).json()["in_stock"])  # noqa: E731
    assert stock(ids["Chicken wings 6 ct"]) == 0 and stock(ids["Fresh garlic 250 g"]) == 0.5 and done["short"] == []
    client.post(f"{base}/stock/undo", json={"event_ids": done["event_ids"]}, headers=h)
    assert stock(ids["Chicken wings 6 ct"]) == 6 and stock(ids["Fresh garlic 250 g"]) == 1


def test_week_plan_fills_the_list_once(client, jazz):
    h, hid = jazz
    base = f"/api/households/{hid}"
    ids = _pantry(client, h, base)
    wings = client.post(f"{base}/recipes", json={"title": "Wings", "uses": ["Chicken wings 6 ct"], "missing": ["lime"]},
                        headers=h).json()
    curry = client.post(f"{base}/recipes", json={"title": "Curry", "uses": ["Rice"], "missing": ["coconut milk", "lime"]},
                        headers=h).json()
    today, tomorrow = date.today(), date.today() + timedelta(days=1)
    client.put(f"{base}/plan/{today.isoformat()}", json={"recipe_id": wings["id"]}, headers=h)
    client.put(f"{base}/plan/{tomorrow.isoformat()}", json={"recipe_id": curry["id"]}, headers=h)
    client.put(f"{base}/plan/{(today + timedelta(days=2)).isoformat()}", json={"note": "eating out"}, headers=h)
    plan = client.get(f"{base}/plan", headers=h).json()
    assert [(p["recipe"] or {}).get("title") or p["note"] for p in plan[:3]] == ["Wings", "Curry", "eating out"]
    client.post(f"{base}/shopping", json={"name": "Lime"}, headers=h)          # already on the list
    added = client.post(f"{base}/plan/shopping", headers=h).json()["added"]
    assert added == ["coconut milk"]                              # wings + rice are at home, lime already listed
    assert client.post(f"{base}/plan/shopping", headers=h).json()["added"] == []   # no duplicates the second time
    # clearing a day
    client.put(f"{base}/plan/{today.isoformat()}", json={}, headers=h)
    assert client.get(f"{base}/plan", headers=h).json()[0]["recipe"] is None
