from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import Caller, current_user, get_caller
from ..models import Invite, Membership, RefreshToken, User
from ..schemas import AcceptInviteIn, ChangePasswordIn, LoginIn, RefreshIn, TokensOut, UserOut
from ..security import hash_password, make_access_token, new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def issue_tokens(db: Session, user: User, device: str = "") -> TokensOut:
    refresh = new_token()
    db.add(RefreshToken(user_id=user.id, token_hash=token_hash(refresh), device=device[:120],
                        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days)))
    db.commit()
    return TokensOut(access_token=make_access_token(user.id), refresh_token=refresh)


@router.post("/login", response_model=TokensOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return issue_tokens(db, user, body.device)


@router.post("/refresh", response_model=TokensOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    """Swap a refresh token for a new pair; the old one is revoked (rotation)."""
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(body.refresh_token)))
    now = datetime.now(timezone.utc)
    if not row or row.revoked_at or _aware(row.expires_at) < now:
        raise HTTPException(401, "Session expired, sign in again")
    row.revoked_at = now
    user = db.get(User, row.user_id)
    return issue_tokens(db, user, row.device)


@router.post("/change-password", response_model=TokensOut)
def change_password(body: ChangePasswordIn, caller: Caller = Depends(get_caller), db: Session = Depends(get_db)):
    """Needs the current password. Signs out every device, then returns a fresh session for this one."""
    if caller.api_key_household:
        raise HTTPException(403, "API keys cannot change a password")
    user = db.get(User, caller.user.id)
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    if body.new_password == body.current_password:
        raise HTTPException(400, "The new password must be different")
    user.password_hash = hash_password(body.new_password)
    now = datetime.now(timezone.utc)
    for row in db.scalars(select(RefreshToken).where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))):
        row.revoked_at = now
    return issue_tokens(db, user, body.device)


@router.post("/logout", status_code=204)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    row = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(body.refresh_token)))
    if row and not row.revoked_at:
        row.revoked_at = datetime.now(timezone.utc)
        db.commit()


@router.post("/accept-invite", response_model=TokensOut)
def accept_invite(body: AcceptInviteIn, db: Session = Depends(get_db)):
    """Join a household with an invite. Creates the account if the email is new."""
    inv = db.scalar(select(Invite).where(Invite.token_hash == token_hash(body.token)))
    if not inv or inv.used_at or _aware(inv.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(400, "This invite is invalid or has expired")
    if not body.email:
        raise HTTPException(422, "Email is required")
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        if not body.password or not verify_password(body.password, user.password_hash):
            raise HTTPException(401, "This email already has an account: enter its password to join")
    else:
        if not body.name or not body.password:
            raise HTTPException(422, "Name and a password of at least 10 characters are required")
        user = User(email=email, name=body.name.strip(), password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
    exists = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.household_id == inv.household_id))
    if not exists:
        db.add(Membership(user_id=user.id, household_id=inv.household_id, role="member"))
    inv.used_at = datetime.now(timezone.utc)
    db.commit()
    return issue_tokens(db, user, "invite")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
