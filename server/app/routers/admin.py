"""Server admin: everyone on this Kasita, across households.

Only users with is_admin, signed in with their own session (never an API key,
so no agent or script can reach this). Household owners manage their own
household in the app; this is for the person running the server.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Caller, get_caller
from ..models import (
    ApiKey, Bill, Household, Integration, Invite, Membership, Product, Receipt, RefreshToken, Recipe, StockEntry,
    StockEvent, User,
)
from ..security import hash_password, new_token

router = APIRouter(prefix="/api/admin", tags=["admin"])


def admin(caller: Caller = Depends(get_caller)) -> User:
    if caller.api_key_household is not None:
        raise HTTPException(403, "Admin pages need a signed-in admin, not an API key")
    if not caller.user.is_admin:
        raise HTTPException(403, "Only a server admin can do this")
    return caller.user


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _last_seen(db: Session, user_id: str) -> datetime | None:
    """When the app last opened a session: refresh tokens are issued at sign-in and on every refresh
    (the access token lasts an hour), so the newest one's issue time is a good 'last seen'."""
    newest = db.scalar(select(func.max(RefreshToken.expires_at)).where(RefreshToken.user_id == user_id))
    newest = _aware(newest)
    key = _aware(db.scalar(select(func.max(ApiKey.last_used_at)).where(ApiKey.user_id == user_id)))
    seen = newest - timedelta(days=settings.refresh_token_days) if newest else None
    return max(x for x in (seen, key) if x) if (seen or key) else None


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() else 0


@router.get("/overview")
def overview(_: User = Depends(admin), db: Session = Depends(get_db)):
    count = lambda model: db.scalar(select(func.count()).select_from(model))  # noqa: E731
    week = datetime.now(timezone.utc) - timedelta(days=7)
    active = sum(1 for (uid,) in db.execute(select(User.id))
                 if (s := _last_seen(db, uid)) and s >= week)
    db_bytes = None
    if db.bind.dialect.name == "postgresql":
        db_bytes = db.scalar(select(func.pg_database_size(func.current_database())))
    return {"users": count(User), "active_this_week": active, "households": count(Household),
            "products": count(Product), "stock_events": count(StockEvent), "receipts": count(Receipt),
            "bills": count(Bill), "recipes": count(Recipe),
            "uploads_bytes": _dir_size(Path(settings.upload_dir)), "database_bytes": db_bytes}


@router.get("/users")
def users(_: User = Depends(admin), db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    out = []
    for u in db.scalars(select(User).order_by(User.created_at)):
        sessions = [t for t in db.scalars(select(RefreshToken).where(RefreshToken.user_id == u.id,
                                                                      RefreshToken.revoked_at.is_(None)))
                    if _aware(t.expires_at) > now]
        homes = db.execute(select(Household.id, Household.name, Membership.role)
                           .join(Membership, Membership.household_id == Household.id)
                           .where(Membership.user_id == u.id)).all()
        out.append({"id": u.id, "email": u.email, "name": u.name, "is_admin": u.is_admin,
                    "created_at": u.created_at, "last_seen": _last_seen(db, u.id),
                    "sessions": len(sessions), "devices": sorted({t.device for t in sessions if t.device}),
                    "api_keys": db.scalar(select(func.count()).select_from(ApiKey).where(ApiKey.user_id == u.id)),
                    "households": [{"id": h, "name": n, "role": r} for h, n, r in homes]})
    return out


@router.get("/households")
def households(_: User = Depends(admin), db: Session = Depends(get_db)):
    out = []
    for h in db.scalars(select(Household).order_by(Household.created_at)):
        members = db.execute(select(User.name, User.email, Membership.role)
                             .join(Membership, Membership.user_id == User.id)
                             .where(Membership.household_id == h.id)).all()
        n = lambda model, col: db.scalar(select(func.count()).select_from(model).where(col == h.id))  # noqa: E731
        last = _aware(db.scalar(select(func.max(StockEvent.at)).where(StockEvent.household_id == h.id)))
        out.append({"id": h.id, "name": h.name, "currency": h.currency, "created_at": h.created_at,
                    "members": [{"name": a, "email": b, "role": r} for a, b, r in members],
                    "products": n(Product, Product.household_id), "receipts": n(Receipt, Receipt.household_id),
                    "in_stock": db.scalar(select(func.count()).select_from(StockEntry).where(
                        StockEntry.household_id == h.id, StockEntry.quantity > 0)),
                    "last_activity": last,
                    "connected": sorted(db.scalars(select(Integration.kind).where(Integration.household_id == h.id))),
                    "open_invites": db.scalar(select(func.count()).select_from(Invite).where(
                        Invite.household_id == h.id, Invite.used_at.is_(None),
                        Invite.expires_at > datetime.now(timezone.utc)))})
    return out


def _user(db: Session, user_id: str) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "User not found")
    return u


def _sign_out(db: Session, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    rows = list(db.scalars(select(RefreshToken).where(RefreshToken.user_id == user_id,
                                                      RefreshToken.revoked_at.is_(None))))
    for t in rows:
        t.revoked_at = now
    return len(rows)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: str, me: User = Depends(admin), db: Session = Depends(get_db)):
    """A temporary password (shown once) and every session signed out. They change it in the app."""
    u = _user(db, user_id)
    temp = new_token(9)
    u.password_hash = hash_password(temp)
    _sign_out(db, u.id)
    db.commit()
    return {"email": u.email, "temporary_password": temp}


@router.post("/users/{user_id}/sign-out")
def sign_out_everywhere(user_id: str, me: User = Depends(admin), db: Session = Depends(get_db)):
    n = _sign_out(db, _user(db, user_id).id)
    db.commit()
    return {"signed_out_sessions": n}


class AdminPatch(BaseModel):
    is_admin: bool


@router.patch("/users/{user_id}")
def set_admin(user_id: str, body: AdminPatch, me: User = Depends(admin), db: Session = Depends(get_db)):
    u = _user(db, user_id)
    if u.id == me.id and not body.is_admin:
        raise HTTPException(409, "You can't remove your own admin rights")
    u.is_admin = body.is_admin
    db.commit()
    return {"id": u.id, "is_admin": u.is_admin}
