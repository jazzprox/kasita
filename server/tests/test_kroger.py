import httpx
import pytest

from app.config import settings
from app.services import barcodes as b


@pytest.fixture
def kroger(monkeypatch):
    monkeypatch.setattr(settings, "kroger_client_id", "id")
    monkeypatch.setattr(settings, "kroger_client_secret", "secret")
    monkeypatch.setattr(b, "_kroger_token", None)
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 1800})
        if req.url.path.endswith("/0004900002890"):
            return httpx.Response(200, json={"data": {
                "description": "Coca-Cola Soda Cans", "brand": "Coca-Cola", "categories": ["Beverages"],
                "items": [{"size": "12 pk / 12 fl oz"}],
                "images": [{"perspective": "back", "sizes": [{"size": "large", "url": "back.jpg"}]},
                           {"perspective": "front", "sizes": [{"size": "large", "url": "front.jpg"}]}]}})
        if req.url.path.endswith("/0000000000000"):
            return httpx.Response(503)
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_kroger_id():
    assert b.kroger_id("049000028904") == "0004900002890"      # UPC-A: drop check digit, pad to 13
    assert b.kroger_id("0049000028904") == "0004900002890"     # same product as EAN-13
    assert b.kroger_id("78933354") is None                     # EAN-8: Kroger can't be asked


def test_kroger_hit_uses_front_image_and_token_once(kroger):
    client, calls = kroger
    hit = b._kroger(client, "049000028904")
    assert hit == {"source": "kroger", "name": "Coca-Cola Soda Cans", "brand": "Coca-Cola",
                   "quantity_text": "12 pk / 12 fl oz", "image_url": "front.jpg", "categories": "Beverages"}
    assert b._kroger(client, "041224705272") is None            # not sold at Kroger
    assert calls.count("/v1/connect/oauth2/token") == 1          # token reused


def test_kroger_outage_is_incomplete_not_missing(kroger):
    client, _ = kroger
    with pytest.raises(b.Incomplete):
        b._kroger(client, "0000000000000")


def test_kroger_skipped_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "kroger_client_id", "")
    assert b._kroger(httpx.Client(), "049000028904") is None
