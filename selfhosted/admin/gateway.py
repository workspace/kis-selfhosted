"""Reverse proxy gateway with authentication middleware."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import httpx
from fastapi import Request, Response
from starlette.responses import RedirectResponse

from auth import verify_session_token
from oauth import verify_bearer_token


# ─── Rewrite factories ──────────────────────────────────────────────────────


def passthrough() -> Callable[[str], str]:
    """Keep path unchanged."""
    return lambda path: path


def strip_prefix(prefix: str, default: str = "/") -> Callable[[str], str]:
    """Strip prefix from path; use default when nothing remains."""
    def _rewrite(path: str) -> str:
        remainder = path[len(prefix):] if path.startswith(prefix) else path
        return remainder if remainder else default
    return _rewrite


# ─── Route definition ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Route:
    prefix: str                          # Gateway path prefix to match
    upstream: str                        # Upstream base URL
    rewrite: Callable[[str], str]        # Transform gateway path → upstream path
    auth_mode: str = "session"           # "bearer" | "session"


# Order matters: more specific prefixes first
ROUTES: list[Route] = [
    Route("/strategy/api/", "http://strategy-backend:8000",  strip_prefix("/strategy"),              "session"),
    Route("/strategy/",     "http://strategy-frontend:3000",  passthrough(),                          "session"),
    Route("/backtest/api/", "http://backtest-backend:8002",   strip_prefix("/backtest"),              "session"),
    Route("/backtest/",     "http://backtest-frontend:3001",  passthrough(),                          "session"),
    Route("/mcp/backtest",  "http://backtest-mcp:3846",       strip_prefix("/mcp/backtest", "/mcp"),  "bearer"),
    Route("/mcp/trading",   "http://trading-mcp:3100",        strip_prefix("/mcp/trading", "/mcp"),   "bearer"),
]

_client = httpx.AsyncClient(timeout=120.0, follow_redirects=False)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_auth(request: Request) -> str | None:
    """Return username if authenticated, else None."""
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return verify_bearer_token(token)

    session = request.cookies.get("session")
    if session:
        return verify_session_token(session)

    return None


def match_route(path: str) -> Route | None:
    """Find matching route for the given path."""
    for route in ROUTES:
        if path.startswith(route.prefix) or path == route.prefix.rstrip("/"):
            return route
    return None


async def proxy_request(request: Request) -> Response:
    """Authenticate and proxy request to upstream service."""
    path = request.url.path

    route = match_route(path)
    if route is None:
        return Response(content="Not Found", status_code=404)

    user = _check_auth(request)
    if user is None:
        if route.auth_mode == "bearer":
            return Response(
                content='{"error":"unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return RedirectResponse(
            url=f"/oauth/login?next={path}",
            status_code=302,
        )

    upstream_path = route.rewrite(path)

    upstream_url = f"{route.upstream}{upstream_path}"
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    print(f"[proxy] {request.method} {path} -> {upstream_url}", flush=True)

    # Forward headers (strip hop-by-hop)
    headers = dict(request.headers)
    for h in ("host", "transfer-encoding"):
        headers.pop(h, None)
    headers["x-forwarded-for"] = _get_client_ip(request)
    headers["x-forwarded-user"] = user

    body = await request.body()

    resp = await _client.request(
        method=request.method,
        url=upstream_url,
        headers=headers,
        content=body,
    )

    print(f"[proxy] {upstream_url} -> {resp.status_code} Location={resp.headers.get('location', '-')}", flush=True)

    # Filter hop-by-hop and encoding headers that conflict with decoded content
    resp_headers = dict(resp.headers)
    for h in ("content-encoding", "content-length", "transfer-encoding"):
        resp_headers.pop(h, None)

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
    )
