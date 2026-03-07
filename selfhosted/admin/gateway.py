"""Reverse proxy gateway with authentication middleware."""

from __future__ import annotations

import logging
import httpx
from fastapi import Request, Response
from starlette.responses import RedirectResponse

from auth import verify_session_token
from oauth import verify_bearer_token

# ─── Route map: external path prefix → (internal base URL, strip prefix) ─────

ROUTE_MAP = [
    ("/strategy/api/", "http://strategy-backend:8000", "/strategy"),
    ("/strategy/", "http://strategy-frontend:3000", ""),
    ("/backtest/api/", "http://backtest-backend:8002", "/backtest"),
    ("/backtest/", "http://backtest-frontend:3001", ""),
    # MCP: /mcp/backtest → backtest-mcp:3846/mcp, /mcp/trading → trading-mcp:3100/mcp
    # rewrite_prefix replaces the matched gateway prefix with the upstream prefix
    ("/mcp/backtest", "http://backtest-mcp:3846", "/mcp/backtest", "/mcp"),
    ("/mcp/trading", "http://trading-mcp:3100", "/mcp/trading", "/mcp"),
]

# Paths that require Bearer token (MCP)
MCP_PATHS = {"/mcp/backtest", "/mcp/trading"}

_client = httpx.AsyncClient(timeout=120.0, follow_redirects=False)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_auth(request: Request) -> str | None:
    """Return username if authenticated, else None."""
    # Check Bearer token
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        return verify_bearer_token(token)

    # Check session cookie
    session = request.cookies.get("session")
    if session:
        return verify_session_token(session)

    return None


def match_route(path: str) -> tuple[str, str, str] | None:
    """Find matching route. Returns (upstream_base, strip_prefix, rewrite_prefix) or None."""
    for entry in ROUTE_MAP:
        prefix, upstream, strip = entry[0], entry[1], entry[2]
        rewrite = entry[3] if len(entry) > 3 else ""
        if path.startswith(prefix) or path == prefix.rstrip("/"):
            return upstream, strip, rewrite
    return None


async def proxy_request(request: Request) -> Response:
    """Authenticate and proxy request to upstream service."""
    path = request.url.path

    # Check authentication
    user = _check_auth(request)
    if user is None:
        # MCP paths → 401 JSON
        if any(path.startswith(mp) for mp in MCP_PATHS):
            return Response(
                content='{"error":"unauthorized"}',
                status_code=401,
                media_type="application/json",
                headers={"WWW-Authenticate": 'Bearer'},
            )
        # Web paths → redirect to login
        return RedirectResponse(
            url=f"/oauth/login?next={path}",
            status_code=302,
        )

    route = match_route(path)
    if route is None:
        return Response(content="Not Found", status_code=404)

    upstream_base, strip_prefix, rewrite_prefix = route

    # Build upstream path: strip gateway prefix, prepend upstream prefix
    upstream_path = path
    if strip_prefix and path.startswith(strip_prefix):
        upstream_path = path[len(strip_prefix):]
    upstream_path = rewrite_prefix + upstream_path
    # Normalise: ensure path starts with /
    if not upstream_path.startswith("/"):
        upstream_path = "/" + upstream_path
    # Remove trailing slash only for rewritten paths (MCP) to avoid 404
    if rewrite_prefix and upstream_path != "/" and upstream_path.endswith("/"):
        upstream_path = upstream_path.rstrip("/")


    upstream_url = f"{upstream_base}{upstream_path}"
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
