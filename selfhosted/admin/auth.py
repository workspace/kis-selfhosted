"""Authentication: client credentials, session cookies, rate limiting."""

from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

# ─── Config ───────────────────────────────────────────────────────────────────

CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production")
SESSION_MAX_AGE = int(os.environ.get("SESSION_MAX_AGE", "86400"))  # 24h

_signer = URLSafeTimedSerializer(JWT_SECRET, salt="session")


# ─── Client credentials verification ────────────────────────────────────────

def verify_client(client_id: str, client_secret: str) -> bool:
    """Check client_id/client_secret against env vars."""
    if not CLIENT_ID or not CLIENT_SECRET:
        return False
    return secrets.compare_digest(client_id, CLIENT_ID) and \
           secrets.compare_digest(client_secret, CLIENT_SECRET)


# ─── Session cookie helpers ──────────────────────────────────────────────────

def create_session_token(client_id: str) -> str:
    return _signer.dumps({"sub": client_id})


def verify_session_token(token: str) -> str | None:
    """Return client_id if valid, else None."""
    try:
        data = _signer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("sub")
    except (BadSignature, SignatureExpired):
        return None


# ─── Rate Limiter ────────────────────────────────────────────────────────────

class LoginRateLimiter:
    """IP-based login attempt rate limiter."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def is_blocked(self, ip: str) -> bool:
        now = time.time()
        attempts = self._attempts[ip]
        self._attempts[ip] = [t for t in attempts if now - t < self.window_seconds]
        return len(self._attempts[ip]) >= self.max_attempts

    def record_failure(self, ip: str) -> None:
        self._attempts[ip].append(time.time())

    def reset(self, ip: str) -> None:
        self._attempts.pop(ip, None)


rate_limiter = LoginRateLimiter()
