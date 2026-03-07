"""KIS Admin Gateway — FastAPI app (auth gateway + OAuth)."""

from __future__ import annotations

import os
from urllib.parse import urlencode

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from auth import (
    verify_client,
    create_session_token,
    verify_session_token,
    rate_limiter,
)
from oauth import (
    generate_auth_code,
    exchange_code,
    client_credentials_grant,
    revoke_token,
    get_metadata,
)
from gateway import proxy_request, match_route

app = FastAPI(title="KIS Admin Gateway")
templates = Jinja2Templates(directory="templates")

GITHUB_URL = os.environ.get(
    "GITHUB_URL", "https://github.com/koreainvestment/open-trading-api"
)


def _get_issuer(request: Request) -> str:
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    return f"{scheme}://{host}"


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_authenticated(request: Request) -> bool:
    session = request.cookies.get("session")
    return session is not None and verify_session_token(session) is not None


# ─── Startup ─────────────────────────────────────────────────────────────────

# ─── Public: Landing page ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "github_url": GITHUB_URL,
    })


# ─── OAuth 2.1 endpoints ────────────────────────────────────────────────────

@app.get("/.well-known/oauth-authorization-server")
async def oauth_metadata(request: Request):
    return JSONResponse(get_metadata(_get_issuer(request)))


@app.get("/oauth/authorize", response_class=HTMLResponse)
async def oauth_authorize_get(
    request: Request,
    response_type: str = "",
    client_id: str = "",
    redirect_uri: str = "",
    code_challenge: str = "",
    code_challenge_method: str = "",
    state: str = "",
):
    """Show login form for browser-based OAuth authorization."""
    if response_type != "code" or not code_challenge or code_challenge_method != "S256":
        return JSONResponse({"error": "invalid_request"}, status_code=400)

    return templates.TemplateResponse("login.html", {
        "request": request,
        "mode": "oauth",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge,
        "code_challenge_method": code_challenge_method,
        "state": state,
        "error": None,
    })


@app.post("/oauth/authorize")
async def oauth_authorize_post(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    redirect_uri: str = Form(""),
    code_challenge: str = Form(""),
    code_challenge_method: str = Form(""),
    state: str = Form(""),
):
    ip = _get_client_ip(request)

    if rate_limiter.is_blocked(ip):
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "oauth",
            "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "error": "Too many attempts. Try again later.",
        }, status_code=429)

    if not verify_client(client_id, client_secret):
        rate_limiter.record_failure(ip)
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "oauth",
            "client_id": client_id, "redirect_uri": redirect_uri,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "state": state,
            "error": "Invalid credentials",
        }, status_code=401)

    rate_limiter.reset(ip)

    code = generate_auth_code(
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
    )
    params = {"code": code}
    if state:
        params["state"] = state
    return RedirectResponse(
        url=f"{redirect_uri}?{urlencode(params)}",
        status_code=302,
    )


@app.post("/oauth/token")
async def oauth_token(request: Request):
    form = await request.form()
    grant_type = form.get("grant_type")

    # Client Credentials Grant
    if grant_type == "client_credentials":
        ip = _get_client_ip(request)
        if rate_limiter.is_blocked(ip):
            return JSONResponse({"error": "too_many_requests"}, status_code=429)

        result = client_credentials_grant(
            client_id=str(form.get("client_id", "")),
            client_secret=str(form.get("client_secret", "")),
        )
        if result is None:
            rate_limiter.record_failure(ip)
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        rate_limiter.reset(ip)
        return JSONResponse(result)

    # Authorization Code Grant
    if grant_type == "authorization_code":
        result = exchange_code(
            code=str(form.get("code", "")),
            client_id=str(form.get("client_id", "")),
            redirect_uri=str(form.get("redirect_uri", "")),
            code_verifier=str(form.get("code_verifier", "")),
        )
        if result is None:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return JSONResponse(result)

    return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)


@app.post("/oauth/revoke")
async def oauth_revoke(request: Request):
    form = await request.form()
    token = form.get("token", "")
    if token:
        revoke_token(str(token))
    return JSONResponse({})


# ─── Web login (session cookie via client credentials) ──────────────────────

@app.get("/oauth/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/strategy/"):
    if _is_authenticated(request):
        return RedirectResponse(url=next, status_code=302)
    return templates.TemplateResponse("login.html", {
        "request": request,
        "mode": "web",
        "next": next,
        "error": None,
    })


@app.post("/oauth/login")
async def login_submit(
    request: Request,
    client_id: str = Form(...),
    client_secret: str = Form(...),
    next: str = Form("/strategy/"),
):
    ip = _get_client_ip(request)

    if rate_limiter.is_blocked(ip):
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "web", "next": next,
            "error": "Too many attempts. Try again later.",
        }, status_code=429)

    if not verify_client(client_id, client_secret):
        rate_limiter.record_failure(ip)
        return templates.TemplateResponse("login.html", {
            "request": request, "mode": "web", "next": next,
            "error": "Invalid credentials",
        }, status_code=401)

    rate_limiter.reset(ip)
    token = create_session_token(client_id)
    response = RedirectResponse(url=next, status_code=302)
    response.set_cookie(
        "session", token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=86400,
    )
    return response


@app.get("/oauth/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("session")
    return response


# ─── Reverse proxy middleware ─────────────────────────────────────────────────

@app.middleware("http")
async def proxy_middleware(request: Request, call_next):
    """Intercept proxy-able paths before FastAPI router processes them."""
    if match_route(request.url.path) is not None:
        return await proxy_request(request)
    return await call_next(request)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
