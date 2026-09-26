import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from .config import settings

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_token(nbytes: int = 32) -> str:
    """Random URL-safe secret (refresh tokens, invites, API keys)."""
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    """Only hashes of secrets are stored, so a database leak doesn't hand out logins."""
    return hashlib.sha256(token.encode()).hexdigest()


def make_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": user_id, "iat": now, "exp": now + timedelta(minutes=settings.access_token_minutes), "typ": "access"}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def read_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    return payload.get("sub") if payload.get("typ") == "access" else None
