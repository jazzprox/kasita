"""A household's ChatGPT connection: encrypted tokens in `Integration(kind="chatgpt")`.

`data` holds {"secret": sealed tokens, "pending": sealed device code, "model",
"email", "plan", "connected_at"}. Tokens never leave the server.
"""
import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..crypto import seal, unseal
from ..models import Integration
from . import codex

KIND = "chatgpt"
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(household_id: str) -> threading.Lock:
    # refresh tokens rotate: two receipts refreshing at once would lose one of them
    with _locks_guard:
        return _locks.setdefault(household_id, threading.Lock())


def get(db: Session, household_id: str) -> Integration | None:
    return db.scalar(select(Integration).where(Integration.household_id == household_id, Integration.kind == KIND))


def _save(db: Session, household_id: str, data: dict) -> Integration:
    row = get(db, household_id)
    if row is None:
        row = Integration(household_id=household_id, kind=KIND, data={})
        db.add(row)
    row.data = data  # new dict so SQLAlchemy sees the change
    return row


def status(db: Session, household_id: str) -> dict:
    row = get(db, household_id)
    d = row.data if row else {}
    pending = None
    if d.get("pending"):
        p = unseal(d["pending"])
        if time.time() - p["started_at"] < codex.DEVICE_CODE_TTL:
            pending = {"user_code": p["user_code"], "verification_url": codex.VERIFICATION_URL,
                       "interval": p["interval"], "expires_at": int(p["started_at"]) + codex.DEVICE_CODE_TTL}
    return {"connected": bool(d.get("secret")), "email": d.get("email"), "plan": d.get("plan"),
            "model": d.get("model"), "connected_at": d.get("connected_at"), "pending": pending}


def start(db: Session, household_id: str) -> dict:
    code = codex.request_device_code()
    row = get(db, household_id)
    data = dict(row.data) if row else {}
    data["pending"] = seal(code)
    _save(db, household_id, data)
    db.commit()
    return status(db, household_id)


def poll(db: Session, household_id: str) -> dict:
    """One check whether the user approved the code; connects when they have."""
    row = get(db, household_id)
    if not row or not row.data.get("pending"):
        return status(db, household_id)
    p = unseal(row.data["pending"])
    if time.time() - p["started_at"] >= codex.DEVICE_CODE_TTL:
        data = dict(row.data)
        data.pop("pending")
        _save(db, household_id, data)
        db.commit()
        raise codex.CodexError("The code expired. Start again.")
    got = codex.poll_device_code(p["device_auth_id"], p["user_code"])
    if got is None:
        return status(db, household_id)
    secret = codex.exchange_code(*got)
    try:
        model = codex.pick_model(codex.list_models(secret), preferred_models())
    except codex.CodexError:
        model = preferred_models()[0]
    data = {"secret": seal(secret.to_dict()), "model": model, "email": secret.email, "plan": secret.plan,
            "connected_at": int(time.time())}
    _save(db, household_id, data)
    db.commit()
    return status(db, household_id)


def preferred_models() -> list[str]:
    return [m.strip() for m in settings.chatgpt_models.split(",") if m.strip()]


def models(db: Session, household_id: str) -> list[str]:
    return codex.list_models(fresh_secret(db, household_id))


def set_model(db: Session, household_id: str, model: str) -> dict:
    row = get(db, household_id)
    if not row or not row.data.get("secret"):
        raise codex.CodexError("ChatGPT is not connected")
    row.data = {**row.data, "model": model}
    db.commit()
    return status(db, household_id)


def disconnect(db: Session, household_id: str) -> None:
    row = get(db, household_id)
    if row:
        db.delete(row)
        db.commit()


def fresh_secret(db: Session, household_id: str) -> codex.Secret:
    with _lock(household_id):
        db.expire_all()
        row = get(db, household_id)
        if not row or not row.data.get("secret"):
            raise codex.CodexError("ChatGPT is not connected. Connect it under More → ChatGPT.")
        secret, refreshed = codex.ensure_fresh(codex.Secret.from_dict(unseal(row.data["secret"])))
        if refreshed:
            row.data = {**row.data, "secret": seal(secret.to_dict()), "email": secret.email or row.data.get("email"),
                        "plan": secret.plan or row.data.get("plan")}
            db.commit()
        return secret


def model_for(db: Session, household_id: str) -> str:
    row = get(db, household_id)
    return (row.data.get("model") if row else None) or preferred_models()[0]
