"""Who is calling, and may they touch this household?

Two ways in: a user's access token (`Authorization: Bearer ...`) from the
app, or an API key (`X-Api-Key: ...`) for scripts and agents. An API key is
bound to one household and can only ever reach that household.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, Household, Membership, User
from .security import read_access_token, token_hash


@dataclass
class Caller:
    user: User
    api_key_household: str | None = None  # set when authenticated with an API key


def get_caller(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Caller:
    if x_api_key:
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == token_hash(x_api_key)))
        if key:
            key.last_used_at = datetime.now(timezone.utc)
            db.commit()
            user = db.get(User, key.user_id)
            if user:
                return Caller(user=user, api_key_household=key.household_id)
    if authorization and authorization.lower().startswith("bearer "):
        user_id = read_access_token(authorization[7:])
        user = db.get(User, user_id) if user_id else None
        if user:
            return Caller(user=user)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in", headers={"WWW-Authenticate": "Bearer"})


def current_user(caller: Caller = Depends(get_caller)) -> User:
    return caller.user


@dataclass
class HouseholdAccess:
    household: Household
    user: User
    role: str


def household_access(household_id: str, caller: Caller = Depends(get_caller), db: Session = Depends(get_db)) -> HouseholdAccess:
    if caller.api_key_household and caller.api_key_household != household_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This API key belongs to another household")
    m = db.scalar(select(Membership).where(Membership.household_id == household_id, Membership.user_id == caller.user.id))
    if not m:
        # same answer as a missing household, so ids can't be probed
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Household not found")
    return HouseholdAccess(household=m.household, user=caller.user, role=m.role)


def household_owner(access: HouseholdAccess = Depends(household_access)) -> HouseholdAccess:
    if access.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the household owner can do this")
    return access
