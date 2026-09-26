"""Encrypt secrets (ChatGPT tokens) before they are stored in the database.

AES-GCM with a key derived from KASITA_SECRET_KEY, so a database dump alone
does not hand out anyone's ChatGPT session. Changing the secret key makes
stored connections unreadable; they then simply need connecting again.
"""
import base64
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import settings


def _key() -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"kasita-integrations-v1").derive(settings.secret_key.encode())


def seal(value: dict) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(_key()).encrypt(nonce, json.dumps(value).encode(), None)
    return base64.urlsafe_b64encode(nonce + ct).decode()


def unseal(token: str) -> dict:
    raw = base64.urlsafe_b64decode(token.encode())
    return json.loads(AESGCM(_key()).decrypt(raw[:12], raw[12:], None))
