"""Authentication endpoints."""

import asyncio
import logging
import os
import re
import secrets
import time
import urllib.parse
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator
from starlette.responses import RedirectResponse

from app.gateway.auth import (
    UserResponse,
    create_access_token,
)
from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.auth.oidc import OIDCError, OIDCService
from app.gateway.auth.oidc_state import (
    OIDCStatePayload,
    compute_code_challenge,
    delete_state_cookie,
    generate_code_verifier,
    generate_nonce,
    generate_oidc_state,
    get_state_cookie,
    set_state_cookie,
)
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, _request_origin, generate_csrf_token, is_secure_request
from app.gateway.deps import get_current_user_from_request, get_local_provider
from deerflow.config.auth_config import OIDCProviderConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# ── Request/Response Models ──────────────────────────────────────────────


class LoginResponse(BaseModel):
    """Response model for login — token only lives in HttpOnly cookie."""

    expires_in: int  # seconds
    needs_setup: bool = False


# Top common-password blocklist. Drawn from the public SecLists "10k worst
# passwords" set, lowercased + length>=8 only (shorter ones already fail
# the min_length check). Kept tight on purpose: this is the **lower bound**
# defense, not a full HIBP / passlib check, and runs in-process per request.
_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty12",
        "qwertyui",
        "qwerty123",
        "abc12345",
        "abcd1234",
        "iloveyou",
        "letmein1",
        "welcome1",
        "welcome123",
        "admin123",
        "administrator",
        "passw0rd",
        "p@ssw0rd",
        "monkey12",
        "trustno1",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "batman123",
        "starwars",
        "dragon123",
        "master123",
        "shadow12",
        "michael1",
        "jennifer",
        "computer",
    }
)


def _password_is_common(password: str) -> bool:
    """Case-insensitive blocklist check.

    Lowercases the input so trivial mutations like ``Password`` /
    ``PASSWORD`` are also rejected. Does not normalize digit substitutions
    (``p@ssw0rd`` is included as a literal entry instead) — keeping the
    rule cheap and predictable.
    """
    return password.lower() in _COMMON_PASSWORDS


def _validate_strong_password(value: str) -> str:
    """Pydantic field-validator body shared by Register + ChangePassword.

    Constraint = function, not type-level mixin. The two request models
    have no "is-a" relationship; they only share the password-strength
    rule. Lifting it into a free function lets each model bind it via
    ``@field_validator(field_name)`` without inheritance gymnastics.
    """
    if _password_is_common(value):
        raise ValueError("Password is too common; choose a stronger password.")
    return value


class RegisterRequest(BaseModel):
    """Request model for user registration."""

    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class ChangePasswordRequest(BaseModel):
    """Request model for password change (also handles setup flow)."""

    current_password: str
    new_password: str = Field(..., min_length=8)
    new_email: EmailStr | None = None

    _strong_password = field_validator("new_password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


# ── Helpers ───────────────────────────────────────────────────────────────


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    """Set the access_token HttpOnly cookie on the response."""
    config = get_auth_config()
    is_https = is_secure_request(request)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=config.token_expiry_days * 24 * 3600 if is_https else None,
    )


# ── Rate Limiting ────────────────────────────────────────────────────────
# In-process dict — not shared across workers.
#
# **Limitation**: with multi-worker deployments (e.g., gunicorn -w N), each
# worker maintains its own lockout table, so an attacker effectively gets
# N × _MAX_LOGIN_ATTEMPTS guesses before being locked out everywhere. For
# production multi-worker setups, replace this with a shared store (Redis,
# database-backed counter) to enforce a true per-IP limit.

_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300  # 5 minutes

# ip → (fail_count, lock_until_timestamp)
_login_attempts: dict[str, tuple[int, float]] = {}


def _trusted_proxies() -> list:
    """Parse ``AUTH_TRUSTED_PROXIES`` env var into a list of ip_network objects.

    Comma-separated CIDR or single-IP entries. Empty / unset = no proxy is
    trusted (direct mode). Invalid entries are skipped with a logger warning.
    Read live so env-var overrides take effect immediately and tests can
    ``monkeypatch.setenv`` without poking a module-level cache.
    """
    raw = os.getenv("AUTH_TRUSTED_PROXIES", "").strip()
    if not raw:
        return []
    nets = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            nets.append(ip_network(entry, strict=False))
        except ValueError:
            logger.warning("AUTH_TRUSTED_PROXIES: ignoring invalid entry %r", entry)
    return nets


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP for rate limiting.

    Trust model:

    - The TCP peer (``request.client.host``) is always the baseline. It is
      whatever the kernel reports as the connecting socket — unforgeable
      by the client itself.
    - ``X-Real-IP`` is **only** honored if the TCP peer is in the
      ``AUTH_TRUSTED_PROXIES`` allowlist (set via env var, comma-separated
      CIDR or single IPs). When set, the gateway is assumed to be behind a
      reverse proxy (nginx, Cloudflare, ALB, …) that overwrites
      ``X-Real-IP`` with the original client address.
    - With no ``AUTH_TRUSTED_PROXIES`` set, ``X-Real-IP`` is silently
      ignored — closing the bypass where any client could rotate the
      header to dodge per-IP rate limits in dev / direct-gateway mode.

    ``X-Forwarded-For`` is intentionally NOT used because it is naturally
    client-controlled at the *first* hop and the trust chain is harder to
    audit per-request.
    """
    peer_host = request.client.host if request.client else None

    trusted = _trusted_proxies()
    if trusted and peer_host:
        try:
            peer_ip = ip_address(peer_host)
            if any(peer_ip in net for net in trusted):
                real_ip = request.headers.get("x-real-ip", "").strip()
                if real_ip:
                    return real_ip
        except ValueError:
            # peer_host wasn't a parseable IP (e.g. "unknown") — fall through
            pass

    return peer_host or "unknown"


def _check_rate_limit(ip: str) -> None:
    """Raise 429 if the IP is currently locked out."""
    record = _login_attempts.get(ip)
    if record is None:
        return
    fail_count, lock_until = record
    if fail_count >= _MAX_LOGIN_ATTEMPTS:
        if time.time() < lock_until:
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
            )
        del _login_attempts[ip]


_MAX_TRACKED_IPS = 10000


def _record_login_failure(ip: str) -> None:
    """Record a failed login attempt for the given IP."""
    # Evict expired lockouts when dict grows too large
    if len(_login_attempts) >= _MAX_TRACKED_IPS:
        now = time.time()
        expired = [k for k, (c, t) in _login_attempts.items() if c >= _MAX_LOGIN_ATTEMPTS and now >= t]
        for k in expired:
            del _login_attempts[k]
        # If still too large, evict cheapest-to-lose half: below-threshold
        # IPs (lock_until=0.0) sort first, then earliest-expiring lockouts.
        if len(_login_attempts) >= _MAX_TRACKED_IPS:
            by_time = sorted(_login_attempts.items(), key=lambda kv: kv[1][1])
            for k, _ in by_time[: len(by_time) // 2]:
                del _login_attempts[k]

    record = _login_attempts.get(ip)
    if record is None:
        _login_attempts[ip] = (1, 0.0)
    else:
        new_count = record[0] + 1
        lock_until = time.time() + _LOCKOUT_SECONDS if new_count >= _MAX_LOGIN_ATTEMPTS else 0.0
        _login_attempts[ip] = (new_count, lock_until)


def _record_login_success(ip: str) -> None:
    """Clear failure counter for the given IP on successful login."""
    _login_attempts.pop(ip, None)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/login/local", response_model=LoginResponse)
async def login_local(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """Local email/password login."""
    client_ip = _get_client_ip(request)
    _check_rate_limit(client_ip)

    user = await get_local_provider().authenticate({"email": form_data.username, "password": form_data.password})

    if user is None:
        _record_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Incorrect email or password").model_dump(),
        )

    _record_login_success(client_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return LoginResponse(
        expires_in=get_auth_config().token_expiry_days * 24 * 3600,
        needs_setup=user.needs_setup,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest):
    """Register a new user account (always 'user' role).

    The first admin is created explicitly through /initialize. This endpoint creates regular users.
    Auto-login by setting the session cookie.
    """
    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password, system_role="user")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, oauth_provider=user.oauth_provider)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    """Logout current user by clearing the cookie."""
    response.delete_cookie(key="access_token", secure=is_secure_request(request), samesite="lax")
    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
async def change_password(request: Request, response: Response, body: ChangePasswordRequest):
    """Change password for the currently authenticated user.

    Also handles the first-boot setup flow:
    - If new_email is provided, updates email (checks uniqueness)
    - If user.needs_setup is True and new_email is given, clears needs_setup
    - Always increments token_version to invalidate old sessions
    - Re-issues session cookie with new token_version
    """
    from app.gateway.auth.password import hash_password_async, verify_password_async
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED

    user = await get_current_user_from_request(request)

    if getattr(request.state, "auth_source", None) == AUTH_SOURCE_AUTH_DISABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="Password changes are not available when DEER_FLOW_AUTH_DISABLED=1.",
            ).model_dump(),
        )

    if user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="OAuth users cannot change password").model_dump())

    if not await verify_password_async(body.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Current password is incorrect").model_dump())

    provider = get_local_provider()

    # Update email if provided
    if body.new_email is not None:
        existing = await provider.get_user_by_email(body.new_email)
        if existing and str(existing.id) != str(user.id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already in use").model_dump())
        user.email = body.new_email

    # Update password + bump version
    user.password_hash = await hash_password_async(body.new_password)
    user.token_version += 1

    # Clear setup flag if this is the setup flow
    if user.needs_setup and body.new_email is not None:
        user.needs_setup = False

    await provider.update_user(user)

    # Re-issue cookie with new token_version
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return MessageResponse(message="Password changed successfully")


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request):
    """Get current authenticated user info."""
    user = await get_current_user_from_request(request)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        system_role=user.system_role,
        needs_setup=user.needs_setup,
        oauth_provider=user.oauth_provider,
    )


# Per-IP cache: ip → (timestamp, result_dict).
# Returns the cached result within the TTL instead of 429, because
# the answer (whether an admin exists) rarely changes and returning
# 429 breaks multi-tab / post-restart reconnection storms.
_SETUP_STATUS_CACHE: dict[str, tuple[float, dict]] = {}
_SETUP_STATUS_CACHE_TTL_SECONDS = 60
_MAX_TRACKED_SETUP_STATUS_IPS = 10000
_SETUP_STATUS_INFLIGHT: dict[str, asyncio.Task[dict]] = {}
_SETUP_STATUS_INFLIGHT_GUARD = asyncio.Lock()


@router.get("/setup-status")
async def setup_status(request: Request):
    """Check if an admin account exists. Returns needs_setup=True when no admin exists."""
    client_ip = _get_client_ip(request)
    now = time.time()

    # Return cached result when within TTL — avoids 429 on multi-tab reconnection.
    cached = _SETUP_STATUS_CACHE.get(client_ip)
    if cached is not None:
        cached_time, cached_result = cached
        if now - cached_time < _SETUP_STATUS_CACHE_TTL_SECONDS:
            return cached_result

    async with _SETUP_STATUS_INFLIGHT_GUARD:
        # Recheck cache after waiting for the inflight guard.
        now = time.time()
        cached = _SETUP_STATUS_CACHE.get(client_ip)
        if cached is not None:
            cached_time, cached_result = cached
            if now - cached_time < _SETUP_STATUS_CACHE_TTL_SECONDS:
                return cached_result

        task = _SETUP_STATUS_INFLIGHT.get(client_ip)
        if task is None:
            # Evict stale entries when dict grows too large to bound memory usage.
            if len(_SETUP_STATUS_CACHE) >= _MAX_TRACKED_SETUP_STATUS_IPS:
                cutoff = now - _SETUP_STATUS_CACHE_TTL_SECONDS
                stale = [k for k, (t, _) in _SETUP_STATUS_CACHE.items() if t < cutoff]
                for k in stale:
                    del _SETUP_STATUS_CACHE[k]
                if len(_SETUP_STATUS_CACHE) >= _MAX_TRACKED_SETUP_STATUS_IPS:
                    by_time = sorted(_SETUP_STATUS_CACHE.items(), key=lambda entry: entry[1][0])
                    for k, _ in by_time[: len(by_time) // 2]:
                        del _SETUP_STATUS_CACHE[k]

            async def _compute_setup_status() -> dict:
                admin_count = await get_local_provider().count_admin_users()
                return {"needs_setup": admin_count == 0}

            task = asyncio.create_task(_compute_setup_status())
            _SETUP_STATUS_INFLIGHT[client_ip] = task

    try:
        result = await task
    finally:
        async with _SETUP_STATUS_INFLIGHT_GUARD:
            if _SETUP_STATUS_INFLIGHT.get(client_ip) is task:
                del _SETUP_STATUS_INFLIGHT[client_ip]

    # Cache only the stable "initialized" result to avoid stale setup redirects.
    if result["needs_setup"] is False:
        _SETUP_STATUS_CACHE[client_ip] = (time.time(), result)
    else:
        _SETUP_STATUS_CACHE.pop(client_ip, None)
    return result


class InitializeAdminRequest(BaseModel):
    """Request model for first-boot admin account creation."""

    email: EmailStr
    password: str = Field(..., min_length=8)

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


@router.post("/initialize", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def initialize_admin(request: Request, response: Response, body: InitializeAdminRequest):
    """Create the first admin account on initial system setup.

    Only callable when no admin exists. Returns 409 Conflict if an admin
    already exists.

    On success, the admin account is created with ``needs_setup=False`` and
    the session cookie is set.
    """
    admin_count = await get_local_provider().count_admin_users()
    if admin_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthErrorResponse(code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED, message="System already initialized").model_dump(),
        )

    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password, system_role="admin", needs_setup=False)
    except ValueError:
        admin_count = await get_local_provider().count_admin_users()
        if admin_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthErrorResponse(code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED, message="System already initialized").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, oauth_provider=user.oauth_provider)


# ── OIDC / SSO Endpoints ────────────────────────────────────────────────

_OIDC_PROVIDER_KEY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _get_oidc_service() -> OIDCService:
    """Get (or create) the singleton OIDC service instance."""
    if not hasattr(_get_oidc_service, "_instance"):
        _get_oidc_service._instance = OIDCService()  # type: ignore[attr-defined]
    return _get_oidc_service._instance  # type: ignore[attr-defined]


async def close_oidc_service() -> None:
    service = getattr(_get_oidc_service, "_instance", None)
    if service is not None:
        await service.close()
        delattr(_get_oidc_service, "_instance")


def _set_csrf_cookie(response: Response, request: Request) -> None:
    """Set the CSRF double-submit cookie (needed for GET-based OIDC callback)."""
    csrf_token = generate_csrf_token()
    is_https = is_secure_request(request)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,  # Must be JS-readable for Double Submit Cookie pattern
        secure=is_https,
        samesite="strict",
        # Persist for the same lifetime as the access_token (see _set_session_cookie)
        # so the double-submit pair is evicted together, never leaving a logged-in
        # session whose csrf_token was dropped (e.g. iOS Safari PWA termination).
        max_age=get_auth_config().token_expiry_days * 24 * 3600 if is_https else None,
    )


def _resolve_oidc_redirect_uri(request: Request, provider_id: str, provider_config: OIDCProviderConfig) -> str:
    """Resolve the redirect URI for an OIDC provider.

    Prefers the explicitly configured ``redirect_uri``. Falls back to
    constructing one from the request's own base URL for development.
    """
    if provider_config.redirect_uri:
        return provider_config.redirect_uri

    # Development fallback: build from the request's proxy-aware origin (honors
    # Forwarded / X-Forwarded-* the same way CSRF origin checks do) rather than
    # the raw Host header, so a spoofed Host cannot steer the IdP redirect_uri
    # and the scheme reflects the real client-facing protocol behind a proxy.
    origin = _request_origin(request)
    if not origin:
        origin = f"{request.url.scheme}://{request.headers.get('host', 'localhost:8001')}"
    return f"{origin}/api/v1/auth/callback/{provider_id}"


@router.get("/providers")
async def list_auth_providers():
    """List enabled SSO providers for the login page.

    Returns only safe frontend metadata — no secrets, endpoints, or
    internal configuration.
    """
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    if not oidc_config.enabled:
        return {"providers": []}

    providers = []
    for provider_id, provider_cfg in oidc_config.providers.items():
        providers.append(
            {
                "id": provider_id,
                "display_name": provider_cfg.display_name,
                "type": "oidc",
            }
        )
    return {"providers": providers}


@router.get("/oauth/{provider}")
async def oauth_login(
    request: Request,
    provider: str,
    next: str | None = None,  # noqa: A002 (shadowing built-in is intentional — this is the query param name)
):
    """Initiate OIDC login flow.

    Redirects to the OIDC provider's authorization URL with state, nonce,
    and PKCE parameters. The ``next`` query parameter specifies where to
    redirect after successful login (default: /workspace).
    """
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    if not oidc_config.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO authentication is not enabled")

    if not _OIDC_PROVIDER_KEY_RE.match(provider):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider ID")

    provider_config = oidc_config.providers.get(provider)
    if not provider_config:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown SSO provider: {provider}")

    # Validate `next` / open redirect prevention
    redirect_path = validate_next_param(next) or "/workspace"

    # Resolve redirect URI
    redirect_uri = _resolve_oidc_redirect_uri(request, provider, provider_config)

    # Generate state, nonce, PKCE
    state_value = generate_oidc_state()
    nonce_value = generate_nonce() if provider_config.nonce_enabled else None
    code_verifier = generate_code_verifier() if provider_config.pkce_enabled else None
    code_challenge = compute_code_challenge(code_verifier) if code_verifier else None

    # Get provider metadata via discovery
    overrides = {
        "authorization_endpoint": provider_config.authorization_endpoint,
        "token_endpoint": provider_config.token_endpoint,
        "userinfo_endpoint": provider_config.userinfo_endpoint,
        "jwks_uri": provider_config.jwks_uri,
    }
    service = _get_oidc_service()
    try:
        metadata = await service.discover(provider_config.issuer, overrides)
    except OIDCError as exc:
        logger.error("OIDC discovery failed for provider %s: %s", provider, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to SSO provider")

    auth_url = service.build_authorization_url(
        metadata=metadata,
        client_id=provider_config.client_id,
        redirect_uri=redirect_uri,
        scopes=provider_config.scopes,
        state=state_value,
        nonce=nonce_value,
        code_challenge=code_challenge,
    )

    # Set signed state cookie
    state_payload = OIDCStatePayload(
        provider=provider,
        state=state_value,
        nonce=nonce_value,
        code_verifier=code_verifier,
        next_path=redirect_path,
    )
    redirect_response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)
    set_state_cookie(redirect_response, request, state_payload)

    return redirect_response


@router.get("/callback/{provider}")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """OIDC callback endpoint.

    Handles the OIDC provider's redirect after user authorization.
    Validates the state cookie, exchanges the code for tokens, validates
    the ID token, provisions/links the DeerFlow user, and sets the
    session cookie.
    """
    from deerflow.config.app_config import get_app_config

    app_config = get_app_config()
    oidc_config = app_config.auth.oidc

    # ── Provider error ───────────────────────────────────────────────
    if error:
        logger.warning("OIDC provider returned error for %s: %s (description: %s)", provider, error, error_description)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, "sso_failed")
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    if not oidc_config.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO authentication is not enabled")

    if not _OIDC_PROVIDER_KEY_RE.match(provider):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid provider ID")

    provider_config = oidc_config.providers.get(provider)
    if not provider_config:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown SSO provider: {provider}")

    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state parameter")

    # ── Verify state cookie ──────────────────────────────────────────
    state_payload = get_state_cookie(request, provider)
    if not state_payload:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing or expired OIDC state cookie")

    if not secrets.compare_digest(state_payload.state, state):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="OIDC state mismatch")

    # ── Resolve redirect URI ─────────────────────────────────────────
    redirect_uri = _resolve_oidc_redirect_uri(request, provider, provider_config)

    # ── Get metadata ─────────────────────────────────────────────────
    overrides = {
        "authorization_endpoint": provider_config.authorization_endpoint,
        "token_endpoint": provider_config.token_endpoint,
        "userinfo_endpoint": provider_config.userinfo_endpoint,
        "jwks_uri": provider_config.jwks_uri,
    }
    service = _get_oidc_service()
    try:
        metadata = await service.discover(provider_config.issuer, overrides)
    except OIDCError as exc:
        logger.error("OIDC discovery failed for provider %s during callback: %s", provider, exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to connect to SSO provider")

    # ── Authenticate ─────────────────────────────────────────────────
    try:
        identity = await service.authenticate_callback(
            provider_id=provider,
            metadata=metadata,
            client_id=provider_config.client_id,
            client_secret=provider_config.client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=state_payload.code_verifier,
            nonce=state_payload.nonce,
            auth_method=provider_config.token_endpoint_auth_method,
        )
    except OIDCError as exc:
        logger.error("OIDC callback authentication failed for %s: %s", provider, exc)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, "sso_failed")
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    # ── Provision / link user ────────────────────────────────────────
    try:
        result = await get_or_provision_oidc_user(provider, provider_config, identity, get_local_provider())
    except HTTPException as exc:
        error_map = {
            status.HTTP_403_FORBIDDEN: "sso_not_allowed",
            status.HTTP_409_CONFLICT: "sso_account_exists",
        }
        error_code = error_map.get(exc.status_code, "sso_failed")
        logger.warning("OIDC user provisioning failed for %s (%s): %s", identity.email, provider, exc.detail)
        redirect = _build_error_redirect(oidc_config.frontend_base_url, error_code)
        return RedirectResponse(url=redirect, status_code=status.HTTP_302_FOUND)

    user = result["user"]

    # ── Issue DeerFlow session ───────────────────────────────────────
    token = create_access_token(str(user.id), token_version=user.token_version)

    redirect_target = state_payload.next_path or "/workspace"
    frontend_base = oidc_config.frontend_base_url or ""
    callback_redirect = f"{frontend_base}/auth/callback?next={urllib.parse.quote(redirect_target)}"

    redirect_response = RedirectResponse(url=callback_redirect, status_code=status.HTTP_302_FOUND)

    # Set session cookie (reuse existing helper)
    _set_session_cookie(redirect_response, token, request)

    # Set CSRF cookie (callback is a GET, so CSRF middleware won't set it)
    _set_csrf_cookie(redirect_response, request)

    # Delete state cookie
    delete_state_cookie(redirect_response, request, provider)

    return redirect_response


def _build_error_redirect(frontend_base_url: str | None, error_code: str) -> str:
    """Build a frontend redirect URL with an error parameter."""
    base = frontend_base_url or ""
    return f"{base}/login?error={error_code}"


def validate_next_param(next_param: str | None) -> str | None:
    """Validate and sanitize the ``next`` redirect parameter.

    Only allows relative paths starting with ``/``. Rejects protocol-relative
    URLs (``//``), absolute URLs, and URLs with embedded protocols.
    """
    if not next_param:
        return None
    if not next_param.startswith("/"):
        return None
    if next_param.startswith("//") or next_param.startswith("http://") or next_param.startswith("https://"):
        return None
    if ":" in next_param:
        return None
    return next_param
