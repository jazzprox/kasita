import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ["KASITA_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["KASITA_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services import barcodes  # noqa: E402

FAKE_DB = {
    "5449000000996": {"source": "openfoodfacts", "name": "Coca-Cola", "brand": "Coca-Cola",
                      "quantity_text": "330 ml", "image_url": None, "categories": "Sodas"},
}


@pytest.fixture(autouse=True)
def fresh_db(monkeypatch):
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    calls = []

    def fake_fetch(code):
        calls.append(code)
        return FAKE_DB.get(code)

    monkeypatch.setattr(barcodes, "fetch_remote", fake_fetch)
    yield calls


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def make_user(email="jazz@example.com", password="correct-horse-battery", name="Jazz"):
    with SessionLocal() as db:
        db.add(User(email=email, name=name, password_hash=hash_password(password)))
        db.commit()
    return email, password


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def jazz(client):
    h = login(client, *make_user())
    hh = client.post("/api/households", json={"name": "Jazz"}, headers=h).json()
    return h, hh["id"]
