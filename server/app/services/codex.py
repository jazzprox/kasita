"""ChatGPT subscription as the AI for receipts ("Sign in with ChatGPT").

Not api.openai.com and not an API key: this signs in the way the official
`codex login --device-auth` CLI does and calls the Responses API on
chatgpt.com/backend-api/codex, billed to the ChatGPT Plus/Pro plan.
Mirrors Hollowpage's lib/codex.ts. The endpoint is undocumented, so all of
it lives here and nothing else in Kasita knows about it.
"""
import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass

import httpx

ISSUER = "https://auth.openai.com"
API_BASE = f"{ISSUER}/api/accounts"
CODEX_BASE = "https://chatgpt.com/backend-api/codex"
VERIFICATION_URL = f"{ISSUER}/codex/device"
CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"  # the Codex CLI's public client id
ORIGINATOR = "codex_cli_rs"
USER_AGENT = "codex_cli_rs/0.0.0"
AUTH_CLAIM = "https://api.openai.com/auth"
PROFILE_CLAIM = "https://api.openai.com/profile"
REFRESH_SKEW = 120  # refresh this many seconds before the access token expires
DEVICE_CODE_TTL = 15 * 60  # the CLI gives up after 15 minutes

_cli_headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "originator": ORIGINATOR,
                "Accept": "application/json"}


class CodexError(Exception):
    pass


@dataclass
class Secret:
    refresh_token: str
    account_id: str
    access_token: str | None = None
    id_token: str | None = None
    expires_at: int | None = None
    plan: str | None = None
    email: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Secret":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


# --- device code flow -------------------------------------------------------------
def request_device_code() -> dict:
    """Step 1: a code the user types at VERIFICATION_URL."""
    r = httpx.post(f"{API_BASE}/deviceauth/usercode", headers=_cli_headers, json={"client_id": CLIENT_ID}, timeout=20)
    if r.status_code != 200:
        raise CodexError(f"device code request failed ({r.status_code})")
    b = r.json()
    return {"device_auth_id": b["device_auth_id"], "user_code": b.get("user_code") or b.get("usercode"),
            "interval": int(float(b.get("interval") or 5)), "started_at": int(time.time())}


def poll_device_code(device_auth_id: str, user_code: str) -> tuple[str, str] | None:
    """Step 2: None while the user hasn't approved yet, else (authorization_code, code_verifier)."""
    r = httpx.post(f"{API_BASE}/deviceauth/token", headers=_cli_headers,
                   json={"device_auth_id": device_auth_id, "user_code": user_code}, timeout=20)
    if r.status_code in (403, 404):
        return None
    if r.status_code != 200:
        raise CodexError(f"device sign-in failed ({r.status_code})")
    b = r.json()
    return b["authorization_code"], b["code_verifier"]


def _claims(token: str) -> dict:
    try:
        seg = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
    except Exception as e:  # noqa: BLE001
        raise CodexError("could not read id_token") from e


def _id_info(id_token: str) -> dict:
    c = _claims(id_token)
    auth = c.get(AUTH_CLAIM) or {}
    return {"account_id": auth.get("chatgpt_account_id"), "plan": auth.get("chatgpt_plan_type"),
            "email": c.get("email") or (c.get(PROFILE_CLAIM) or {}).get("email")}


def _token_request(form: dict) -> dict:
    r = httpx.post(f"{ISSUER}/oauth/token", data={"client_id": CLIENT_ID, **form},
                   headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code != 200:
        raise CodexError(f"token request rejected ({r.status_code})")
    return r.json()


def exchange_code(authorization_code: str, code_verifier: str) -> Secret:
    """Step 3: the approved code becomes tokens."""
    b = _token_request({"grant_type": "authorization_code", "code": authorization_code, "code_verifier": code_verifier,
                        "redirect_uri": f"{ISSUER}/deviceauth/callback"})
    if not b.get("refresh_token"):
        raise CodexError("no refresh token in the response")
    info = _id_info(b["id_token"]) if b.get("id_token") else {}
    if not info.get("account_id"):
        raise CodexError("no ChatGPT account id in the response")
    return Secret(refresh_token=b["refresh_token"], account_id=info["account_id"], access_token=b.get("access_token"),
                  id_token=b.get("id_token"), plan=info.get("plan"), email=info.get("email"),
                  expires_at=int(time.time()) + int(b["expires_in"]) if b.get("expires_in") else None)


def refresh(secret: Secret) -> Secret:
    """OpenAI may rotate the refresh token; the new one must be kept."""
    b = _token_request({"grant_type": "refresh_token", "refresh_token": secret.refresh_token})
    id_token = b.get("id_token") or secret.id_token
    info = _id_info(id_token) if id_token else {}
    return Secret(refresh_token=b.get("refresh_token") or secret.refresh_token,
                  account_id=info.get("account_id") or secret.account_id, access_token=b.get("access_token"),
                  id_token=id_token, plan=info.get("plan") or secret.plan, email=info.get("email") or secret.email,
                  expires_at=int(time.time()) + int(b["expires_in"]) if b.get("expires_in") else None)


def ensure_fresh(secret: Secret) -> tuple[Secret, bool]:
    stale = not secret.access_token or not secret.expires_at or secret.expires_at - REFRESH_SKEW <= time.time()
    return (refresh(secret), True) if stale else (secret, False)


# --- the Codex backend -----------------------------------------------------------
def _backend_headers(secret: Secret) -> dict:
    return {"Authorization": f"Bearer {secret.access_token}", "chatgpt-account-id": secret.account_id,
            "originator": ORIGINATOR, "User-Agent": USER_AGENT}


def list_models(secret: Secret) -> list[str]:
    r = httpx.get(f"{CODEX_BASE}/models", params={"client_version": "1.0.0"}, headers=_backend_headers(secret),
                  timeout=20)
    if r.status_code != 200:
        raise CodexError(f"model list failed ({r.status_code})")
    return [m["slug"] for m in r.json().get("models", []) if m.get("slug")]


def pick_model(available: list[str], preferred: list[str]) -> str | None:
    for m in preferred:
        if m in available:
            return m
    return available[0] if available else None


def respond(secret: Secret, model: str, instructions: str, content: list[dict], *, effort: str = "low",
            timeout: float = 180) -> str:
    """One Responses API call; returns the model's text output."""
    headers = {**_backend_headers(secret), "OpenAI-Beta": "responses=experimental", "session_id": str(uuid.uuid4()),
               "Accept": "text/event-stream", "Content-Type": "application/json"}
    body = {"model": model, "instructions": instructions, "stream": True, "store": False,
            "reasoning": {"effort": effort},
            "input": [{"type": "message", "role": "user", "content": content}]}
    out: list[str] = []
    final: str | None = None
    with httpx.stream("POST", f"{CODEX_BASE}/responses", headers=headers, json=body, timeout=timeout) as r:
        if r.status_code != 200:
            r.read()
            detail = r.text[:300]
            if r.status_code == 401:
                raise CodexError("ChatGPT sign-in expired; connect again in Settings")
            if r.status_code == 429:
                raise CodexError("ChatGPT usage limit reached; try again later")
            raise CodexError(f"ChatGPT request failed ({r.status_code}): {detail}")
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            try:
                ev = json.loads(line[5:].strip())
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "response.output_text.delta":
                out.append(ev.get("delta") or "")
            elif kind == "response.completed":
                texts = [c.get("text", "") for item in (ev.get("response") or {}).get("output") or []
                         for c in item.get("content") or [] if c.get("type") == "output_text"]
                if texts:
                    final = "".join(texts)
            elif kind in ("response.failed", "error"):
                msg = ((ev.get("response") or {}).get("error") or ev.get("error") or {}).get("message")
                raise CodexError(f"ChatGPT could not answer: {msg or kind}")
    return final if final is not None else "".join(out)
