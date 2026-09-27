"""Connections to outside services. For now: the household's ChatGPT, which reads receipts."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import HouseholdAccess, household_access, household_owner
from ..schemas import ChatGPTStatus, ModelIn, SecuroConnectIn, SecuroStatus
from ..services import chatgpt, codex, securo

router = APIRouter(prefix="/api/households/{household_id}/integrations", tags=["integrations"])


def _run(fn, *args):
    try:
        return fn(*args)
    except codex.CodexError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/chatgpt", response_model=ChatGPTStatus)
def chatgpt_status(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return chatgpt.status(db, a.household.id)


@router.post("/chatgpt/connect", response_model=ChatGPTStatus)
def chatgpt_connect(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    """Start "Sign in with ChatGPT": returns a code to enter at the verification URL."""
    return _run(chatgpt.start, db, a.household.id)


@router.post("/chatgpt/poll", response_model=ChatGPTStatus)
def chatgpt_poll(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    """Call every few seconds while the code is shown; `connected` turns true once approved."""
    return _run(chatgpt.poll, db, a.household.id)


@router.get("/chatgpt/models", response_model=list[str])
def chatgpt_models(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    return _run(chatgpt.models, db, a.household.id)


@router.patch("/chatgpt", response_model=ChatGPTStatus)
def chatgpt_model(body: ModelIn, a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    return _run(chatgpt.set_model, db, a.household.id, body.model)


@router.delete("/chatgpt", status_code=204)
def chatgpt_disconnect(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    chatgpt.disconnect(db, a.household.id)


# --- Securo (finance app): link receipts to card payments -----------------------------
@router.get("/securo", response_model=SecuroStatus)
def securo_status(a: HouseholdAccess = Depends(household_access), db: Session = Depends(get_db)):
    return securo.status(db, a.household.id)


@router.post("/securo", response_model=SecuroStatus)
def securo_connect(body: SecuroConnectIn, a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    """Sign in to Securo once; the password is not stored, only Securo's access token (encrypted)."""
    try:
        return securo.connect(db, a.household.id, body.url, body.email, body.password)
    except securo.SecuroError as e:
        raise HTTPException(400, str(e)) from e


@router.delete("/securo", status_code=204)
def securo_disconnect(a: HouseholdAccess = Depends(household_owner), db: Session = Depends(get_db)):
    securo.disconnect(db, a.household.id)
