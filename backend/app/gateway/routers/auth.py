"""Authentication endpoints."""

import logging
import os
import time
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, field_validator

from app.gateway.auth import (
    UserResponse,
    create_access_token,
)
from app.gateway.auth.config import get_auth_config
from app.gateway.auth.errors import AuthErrorCode, AuthErrorResponse
from app.gateway.csrf_middleware import is_secure_request
from app.gateway.deps import get_current_user_from_request, get_local_provider

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

    Admin is auto-created on first boot. This endpoint creates regular users.
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

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role)


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

    user = await get_current_user_from_request(request)

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
    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, needs_setup=user.needs_setup)


_SETUP_STATUS_COOLDOWN: dict[str, float] = {}
_SETUP_STATUS_COOLDOWN_SECONDS = 60
_MAX_TRACKED_SETUP_STATUS_IPS = 10000


@router.get("/setup-status")
async def setup_status(request: Request):
    """Check if an admin account exists. Returns needs_setup=True when no admin exists."""
    client_ip = _get_client_ip(request)
    now = time.time()
    last_check = _SETUP_STATUS_COOLDOWN.get(client_ip, 0)
    elapsed = now - last_check
    if elapsed < _SETUP_STATUS_COOLDOWN_SECONDS:
        retry_after = max(1, int(_SETUP_STATUS_COOLDOWN_SECONDS - elapsed))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Setup status check is rate limited",
            headers={"Retry-After": str(retry_after)},
        )
    # Evict stale entries when dict grows too large to bound memory usage.
    if len(_SETUP_STATUS_COOLDOWN) >= _MAX_TRACKED_SETUP_STATUS_IPS:
        cutoff = now - _SETUP_STATUS_COOLDOWN_SECONDS
        stale = [k for k, t in _SETUP_STATUS_COOLDOWN.items() if t < cutoff]
        for k in stale:
            del _SETUP_STATUS_COOLDOWN[k]
        # If still too large after evicting expired entries, remove oldest half.
        if len(_SETUP_STATUS_COOLDOWN) >= _MAX_TRACKED_SETUP_STATUS_IPS:
            by_time = sorted(_SETUP_STATUS_COOLDOWN.items(), key=lambda kv: kv[1])
            for k, _ in by_time[: len(by_time) // 2]:
                del _SETUP_STATUS_COOLDOWN[k]
    _SETUP_STATUS_COOLDOWN[client_ip] = now
    admin_count = await get_local_provider().count_admin_users()
    return {"needs_setup": admin_count == 0}


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
        # DB unique-constraint race: another concurrent request beat us.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=AuthErrorResponse(code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED, message="System already initialized").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role)


# ── OAuth Endpoints (Future/Placeholder) ─────────────────────────────────


@router.get("/oauth/{provider}")
async def oauth_login(provider: str):
    """Initiate OAuth login flow.

    Redirects to the OAuth provider's authorization URL.
    Currently a placeholder - requires OAuth provider implementation.
    """
    if provider not in ["github", "google"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported OAuth provider: {provider}",
        )

    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="OAuth login not yet implemented",
    )


@router.get("/callback/{provider}")
async def oauth_callback(provider: str, code: str, state: str):
    """OAuth callback endpoint.

    Handles the OAuth provider's callback after user authorization.
    Currently a placeholder.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="OAuth callback not yet implemented",
    )
