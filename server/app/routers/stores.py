"""Stores: profile (address, phone, CRIB, map pin), the map of where you shop, per-store summary."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access
from ..models import Store
from ..schemas import HomeIn, StoreOut, StorePatch
from ..services import geocode
from ..services import store_stats as stats
from ..services.receipts import crib_key

router = APIRouter(prefix="/api/households/{household_id}/stores", tags=["stores"])


def get_store(db: Session, household_id: str, store_id: str) -> Store:
    s = db.get(Store, store_id)
    if not s or s.household_id != household_id:
        raise HTTPException(404, "Store not found")
    return s


@router.get("/map")
def store_map(days: int | None = None, a: HouseholdAccess = Depends(household_access),
              db: Session = Depends(get_db)):
    """Every store with its pin (lat/lon, null = not on the map yet) and visits / spending there
    (booked receipts; `days` = only the last so many days)."""
    return stats.map_stores(db, a.household.id, days=max(1, min(days, 3660)) if days else None)


@router.get("/{store_id}/summary")
def summary(store_id: str, days: int | None = None, a: HouseholdAccess = Depends(household_access),
            db: Session = Depends(get_db)):
    """Visits, total spent, average basket and the items bought there most."""
    s = get_store(db, a.household.id, store_id)
    return stats.store_summary(db, a.household.id, s, days=max(1, min(days, 3660)) if days else None)


@router.post("/{store_id}/geocode", response_model=StoreOut)
def find_on_map(store_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Look the store up on OpenStreetMap now (address, then name). A pin placed by hand is kept."""
    s = get_store(db, a.household.id, store_id)
    geocode.geocode_store(db, s)
    db.commit()
    return s


@router.get("/{store_id}", response_model=StoreOut)
def store(store_id: str, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return get_store(db, a.household.id, store_id)


@router.patch("/{store_id}", response_model=StoreOut)
def update_store(store_id: str, body: StorePatch, background: BackgroundTasks,
                 a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    s = get_store(db, a.household.id, store_id)
    data = body.model_dump(exclude_unset=True)
    old_address = s.address
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
    if "kind" in data:
        s.kind = data["kind"]
    if "lat" in data or "lon" in data:
        lat, lon = data.get("lat", s.lat), data.get("lon", s.lon)
        if (lat is None) != (lon is None):
            raise HTTPException(422, "Give both lat and lon, or neither")
        s.lat, s.lon = lat, lon
        s.location_source = "manual" if lat is not None else None
    if s.address != old_address and s.location_source != "manual" and "lat" not in data:
        # a new address: the old map pin (if it was looked up) no longer applies
        s.lat = s.lon = s.location_source = None
        if s.address:
            background.add_task(geocode.geocode_store_id, s.id)
    db.commit()
    return s


# --- fun stats ---------------------------------------------------------------------
stats_router = APIRouter(prefix="/api/households/{household_id}", tags=["stores"])


@stats_router.get("/home")
def home(a: HouseholdAccess = Depends(household_access)):
    """Home on the map (for the travel stat), or nulls."""
    return {"lat": a.household.home_lat, "lon": a.household.home_lon}


@stats_router.put("/home")
def set_home(body: HomeIn, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    if (body.lat is None) != (body.lon is None):
        raise HTTPException(422, "Give both lat and lon, or neither")
    a.household.home_lat, a.household.home_lon = body.lat, body.lon
    db.commit()
    return {"lat": body.lat, "lon": body.lon}


@stats_router.get("/stats")
def fun_stats(days: int = 365, a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    """Home turf, trips per week and month, favourite days and times, how far you travel, and
    minimarkets vs supermarkets. From booked receipts over the last `days`."""
    return stats.fun_stats(db, a.household, days=max(7, min(days, 3660)))
