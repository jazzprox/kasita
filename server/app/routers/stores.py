"""One store: its profile (address, phone, CRIB, map pin)."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Store
from ..schemas import StoreOut, StorePatch
from ..services.receipts import crib_key

router = APIRouter(prefix="/api/households/{household_id}/stores", tags=["stores"])


def get_store(db: Session, household_id: str, store_id: str) -> Store:
    s = db.get(Store, store_id)
    if not s or s.household_id != household_id:
        raise HTTPException(404, "Store not found")
    return s


@router.get("/{store_id}", response_model=StoreOut)
def store(store_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return get_store(db, a.household.id, store_id)


@router.patch("/{store_id}", response_model=StoreOut)
def update_store(store_id: str, body: StorePatch, a: HouseholdAccess = Depends(household_access),
                 db: Session = Depends(get_db)):
    s = get_store(db, a.household.id, store_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        name = (data.pop("name") or "").strip()
        if not name:
            raise HTTPException(422, "A store needs a name")
        if name != s.name and db.scalar(select(Store).where(Store.household_id == s.household_id, Store.name == name)):
            raise HTTPException(409, "There is already a store with that name")
        s.name = name
    for field in ("payee_match", "address", "phone"):
        if field in data:
            setattr(s, field, (data[field] or "").strip() or None)
    if "crib" in data:
        s.crib = crib_key(data["crib"])
    if "lat" in data or "lon" in data:
        lat, lon = data.get("lat", s.lat), data.get("lon", s.lon)
        if (lat is None) != (lon is None):
            raise HTTPException(422, "Give both lat and lon, or neither")
        s.lat, s.lon = lat, lon
        s.location_source = "manual" if lat is not None else None
    db.commit()
    return s
