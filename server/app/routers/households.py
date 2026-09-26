from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import HouseholdAccess, current_user, household_access, household_owner
from ..models import ApiKey, Household, Invite, Location, Membership, Store, User
from ..schemas import (
    ApiKeyCreated, ApiKeyIn, ApiKeyOut, HouseholdIn, HouseholdOut, HouseholdPatch, InviteOut, LocationIn,
    LocationOut, MemberOut, StoreIn, StoreOut,
)
from ..security import new_token, token_hash

router = APIRouter(prefix="/api/households", tags=["households"])

DEFAULT_LOCATIONS = [("Fridge", False), ("Freezer", True), ("Pantry", False)]


@router.get("", response_model=list[HouseholdOut])
def my_households(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Membership).where(Membership.user_id == user.id))
    return [HouseholdOut(id=m.household.id, name=m.household.name, currency=m.household.currency, role=m.role) for m in rows]


@router.post("", response_model=HouseholdOut, status_code=201)
def create_household(body: HouseholdIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    h = Household(name=body.name.strip(), currency=body.currency.upper())
    db.add(h)
    db.flush()
    db.add(Membership(user_id=user.id, household_id=h.id, role="owner"))
    for name, freezer in DEFAULT_LOCATIONS:
        db.add(Location(household_id=h.id, name=name, is_freezer=freezer))
    db.commit()
    return HouseholdOut(id=h.id, name=h.name, currency=h.currency, role="owner")


@router.patch("/{household_id}", response_model=HouseholdOut)
def update_household(body: HouseholdPatch, a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    if body.name:
        a.household.name = body.name.strip()
    if body.currency:
        a.household.currency = body.currency.upper()
    db.commit()
    return HouseholdOut(id=a.household.id, name=a.household.name, currency=a.household.currency, role=a.role)


# --- members & invites ---------------------------------------------------------
@router.get("/{household_id}/members", response_model=list[MemberOut])
def members(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    rows = db.scalars(select(Membership).where(Membership.household_id == a.household.id))
    return [MemberOut(user_id=m.user.id, name=m.user.name, email=m.user.email, role=m.role) for m in rows]


@router.delete("/{household_id}/members/{user_id}", status_code=204)
def remove_member(user_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    # owners can remove anyone; members can only leave
    if a.role != "owner" and user_id != a.user.id:
        raise HTTPException(403, "Only the owner can remove other members")
    m = db.scalar(select(Membership).where(Membership.household_id == a.household.id, Membership.user_id == user_id))
    if not m:
        raise HTTPException(404, "Not a member")
    owners = db.scalars(select(Membership).where(Membership.household_id == a.household.id, Membership.role == "owner")).all()
    if m.role == "owner" and len(owners) == 1:
        raise HTTPException(400, "A household needs at least one owner")
    db.delete(m)
    db.commit()


@router.post("/{household_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    token = new_token(24)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    db.add(Invite(token_hash=token_hash(token), household_id=a.household.id, created_by=a.user.id, expires_at=expires))
    db.commit()
    return InviteOut(token=token, url=f"{settings.public_url.rstrip('/')}/#/invite/{token}", expires_at=expires)


# --- API keys ---------------------------------------------------------------
@router.get("/{household_id}/api-keys", response_model=list[ApiKeyOut])
def list_keys(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    return db.scalars(select(ApiKey).where(ApiKey.household_id == a.household.id)).all()


@router.post("/{household_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
def create_key(body: ApiKeyIn, a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    key = "ksk_" + new_token(30)
    row = ApiKey(key_hash=token_hash(key), prefix=key[:10], name=body.name, household_id=a.household.id, user_id=a.user.id)
    db.add(row)
    db.commit()
    return ApiKeyCreated(id=row.id, name=row.name, prefix=row.prefix, created_at=row.created_at,
                         last_used_at=None, key=key)


@router.delete("/{household_id}/api-keys/{key_id}", status_code=204)
def delete_key(key_id: str, a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if not row or row.household_id != a.household.id:
        raise HTTPException(404, "Key not found")
    db.delete(row)
    db.commit()


# --- locations & stores ---------------------------------------------------------
@router.get("/{household_id}/locations", response_model=list[LocationOut])
def locations(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return db.scalars(select(Location).where(Location.household_id == a.household.id).order_by(Location.name)).all()


@router.post("/{household_id}/locations", response_model=LocationOut, status_code=201)
def add_location(body: LocationIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    row = Location(household_id=a.household.id, name=body.name.strip(), is_freezer=body.is_freezer)
    db.add(row)
    db.commit()
    return row


@router.get("/{household_id}/stores", response_model=list[StoreOut])
def stores(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return db.scalars(select(Store).where(Store.household_id == a.household.id).order_by(Store.name)).all()


@router.post("/{household_id}/stores", response_model=StoreOut, status_code=201)
def add_store(body: StoreIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    row = Store(household_id=a.household.id, name=body.name.strip(), payee_match=body.payee_match)
    db.add(row)
    db.commit()
    return row
