"""OAuth 2.1 Authorization Server — Client Credentials + Auth Code (PKCE S256)."""

from __future__ import annotations

import hashlib
import base64
import os
import secrets
import time
from dataclasses import dataclass, field

from jose import jwt

from auth import JWT_SECRET, verify_client

# ─── Config ───────────────────────────────────────────────────────────────────

TOKEN_EXPIRY = int(os.environ.get("TOKEN_EXPIRY", "3600"))  # 1h


# ─── In-memory stores (sufficient for personal use) ──────────────────────────

@dataclass
class AuthCode:
    code: str
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    created_at: float = field(default_factory=time.time)


@dataclass
class RegisteredClient:
    client_id: str
    client_name: str
    redirect_uris: list[str]
    created_at: float = field(default_factory=time.time)


_auth_codes: dict[str, AuthCode] = {}
_revoked_tokens: set[str] = set()
_registered_clients: dict[str, RegisteredClient] = {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _issue_token(subject: str) -> dict:
    """Issue a JWT access token."""
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": subject,
            "iat": now,
            "exp": now + TOKEN_EXPIRY,
            "jti": secrets.token_urlsafe(16),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": TOKEN_EXPIRY,
    }


# ─── Client Credentials Grant ───────────────────────────────────────────────

def client_credentials_grant(client_id: str, client_secret: str) -> dict | None:
    """Validate client credentials and return token dict, or None."""
    if not verify_client(client_id, client_secret):
        return None
    return _issue_token(client_id)


# ─── Authorization Code Grant (for browser-based MCP clients) ───────────────

def generate_auth_code(
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
) -> str:
    code = secrets.token_urlsafe(32)
    _auth_codes[code] = AuthCode(
        code=code,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    return code


def exchange_code(
    code: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict | None:
    """Exchange auth code for access token. Returns token dict or None."""
    ac = _auth_codes.pop(code, None)
    if ac is None:
        return None

    # Code expires after 60 seconds
    if time.time() - ac.created_at > 60:
        return None

    if ac.client_id != client_id or ac.redirect_uri != redirect_uri:
        return None

    # PKCE S256 verification
    if ac.code_challenge_method != "S256":
        return None
    if _s256(code_verifier) != ac.code_challenge:
        return None

    return _issue_token(client_id)


# ─── Token verification / revocation ────────────────────────────────────────

def verify_bearer_token(token: str) -> str | None:
    """Return subject if valid JWT, else None."""
    if token in _revoked_tokens:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


def revoke_token(token: str) -> None:
    _revoked_tokens.add(token)


def register_client(client_name: str, redirect_uris: list[str]) -> dict:
    """RFC 7591 Dynamic Client Registration."""
    client_id = f"mcp-{secrets.token_urlsafe(16)}"
    _registered_clients[client_id] = RegisteredClient(
        client_id=client_id,
        client_name=client_name,
        redirect_uris=redirect_uris,
    )
    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
    }


def is_registered_client(client_id: str) -> bool:
    """Check if a client_id is dynamically registered or the static one."""
    from auth import CLIENT_ID
    return client_id in _registered_clients or client_id == CLIENT_ID


def get_metadata(issuer: str) -> dict:
    """RFC 8414 Authorization Server Metadata."""
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "revocation_endpoint": f"{issuer}/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "client_credentials"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }
