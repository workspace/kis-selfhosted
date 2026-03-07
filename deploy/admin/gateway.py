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
    ("/mcp/backtest", "http://backtest-mcp:3846", "/mcp/backtest"),
    ("/mcp/trading", "http://trading-mcp:3100", "/mcp/trading"),
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


def match_route(path: str) -> tuple[str, str] | None:
    """Find matching route. Returns (upstream_base, prefix_to_strip) or None."""
    for prefix, upstream, strip in ROUTE_MAP:
        if path.startswith(prefix) or path == prefix.rstrip("/"):
            return upstream, strip
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

    upstream_base, strip_prefix = route

    # Build upstream URL
    upstream_path = path
    if strip_prefix and path.startswith(strip_prefix):
        upstream_path = path[len(strip_prefix):] or "/"

    # For MCP routes, map to /mcp
    if any(path.startswith(mp) for mp in MCP_PATHS):
        upstream_path = "/mcp" + upstream_path.split("/mcp/backtest", 1)[-1].split("/mcp/trading", 1)[-1]
        if upstream_path == "/mcp":
            upstream_path = "/mcp"


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

    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=dict(resp.headers),
    )
