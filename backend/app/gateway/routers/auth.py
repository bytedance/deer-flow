"""Authentication endpoints."""

import asyncio
import logging
import os
import re
import secrets
import time
import urllib.parse
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
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
from app.gateway.auth.pat import PAT_MAX_NAME_LENGTH
from app.gateway.auth.session_cookie import ACCESS_TOKEN_COOKIE_NAME, SESSION_PERSISTENCE_COOKIE_NAME, set_session_cookie
from app.gateway.auth.session_cookie_state import SKIP_AUTH_CSRF_COOKIE_STATE_ATTR
from app.gateway.auth.user_provisioning import get_or_provision_oidc_user
from app.gateway.csrf_middleware import CSRF_COOKIE_NAME, _request_origin, auth_csrf_cookie_settings, generate_csrf_token, is_secure_request
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
    remember_me: bool = True

    _strong_password = field_validator("password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class ChangePasswordRequest(BaseModel):
    """Request model for password change (also handles setup flow)."""

    current_password: str
    new_password: str = Field(..., min_length=8)
    new_email: EmailStr | None = None
    remember_me: bool | None = None

    _strong_password = field_validator("new_password")(classmethod(lambda cls, v: _validate_strong_password(v)))


class MessageResponse(BaseModel):
    """Generic message response."""

    message: str


# ── Helpers ───────────────────────────────────────────────────────────────


def _set_session_cookie(response: Response, token: str, request: Request, *, remember_me: bool | None = None) -> None:
    """Set the access_token HttpOnly cookie on the response."""
    set_session_cookie(response, request, token, remember_me=remember_me)


# ── Rate Limiting ────────────────────────────────────────────────────────
# In-process dict — not shared across workers.
#
# **Limitation**: with multi-worker deployments (e.g., gunicorn -w N), each
# worker maintains its own lockout table, so an attacker effectively gets
# N × max_login_attempts guesses before being locked out everywhere. For
# production multi-worker setups, replace this with a shared store (Redis,
# database-backed counter) to enforce a true per-IP limit.
#
# The policy values are operator-configurable via auth.local.max_login_attempts /
# auth.local.lockout_seconds (read live per call, matching _local_registration_enabled,
# so a config reload applies to the next login without a Gateway restart). The
# no-config.yaml fallback is the LocalAuthConfig model defaults — a single source
# of truth, not a second copy of the numbers.

# ip → (fail_count, locked_at, locked_duration). The stored duration always
# matches the policy the lock was last evaluated under (its creation counts
# as an evaluation, and every check that leaves the lock active commits the
# then-current duration, decreases included): a lowered lockout_seconds
# releases an active lock early, a raised one extends it — and a sentence
# that already served the last-evaluated duration is never resurrected.
_login_attempts: dict[str, tuple[int, float, float]] = {}


def _login_throttle_policy() -> tuple[int, float]:
    """(max_login_attempts, lockout_seconds) from auth.local config, read live.

    Only ``FileNotFoundError`` falls back to the model defaults, matching
    ``_local_registration_enabled``: ``config.yaml`` is absent in bare-app
    contexts that never load it (tests build the gateway without one), and the
    throttle must keep its pre-config-era behavior there. A malformed config
    propagates instead — like every other config consumer, and so an operator
    who tightened the policy never silently gets the more permissive defaults.

    Callers on request paths resolve this at most once per helper invocation;
    ``get_app_config`` re-hashes the config file on every call, and the login
    endpoint is unauthenticated.
    """
    from deerflow.config.app_config import get_app_config
    from deerflow.config.auth_config import LocalAuthConfig

    try:
        local = get_app_config().auth.local
    except FileNotFoundError:
        local = LocalAuthConfig()
    return local.max_login_attempts, local.lockout_seconds


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


async def _check_rate_limit(ip: str) -> None:
    """Raise 429 if the IP is currently locked out.

    The record lookup comes before policy resolution on purpose: a clean IP
    (no failed attempts recorded — the overwhelming majority of logins) must
    not pay a config read, and ``get_app_config`` re-hashes config.yaml on
    every call while this endpoint is unauthenticated. When a record exists
    the policy is resolved off the event loop via ``asyncio.to_thread``:
    every request from a recorded IP — including an already-locked attacker
    flooding the endpoint — pays that read on the way to its answer, and the
    stat + hash must not block the loop.
    """
    record = _login_attempts.get(ip)
    if record is None:
        return
    max_attempts, lockout_seconds = await asyncio.to_thread(_login_throttle_policy)
    # The await above is a yield point: while this coroutine was suspended,
    # another request for the same IP may have deleted or replaced the record
    # (the pre-async version was atomic on the loop). The pre-read served only
    # as the cheap clean-IP skip; decide on a fresh snapshot from here on —
    # everything below is synchronous, and every mutation is guarded by
    # re-comparing against that snapshot so a record replaced mid-flight
    # (e.g. a successful login followed by a new failure) is never clobbered.
    record = _login_attempts.get(ip)
    if record is None:
        return
    fail_count, locked_at, locked_duration = record
    if fail_count < max_attempts:
        return
    if locked_at == 0.0:
        # Over the *current* threshold but the lock never started under the
        # threshold these failures accumulated under (the operator tightened
        # max_login_attempts mid-count). Keep the record: the next failure
        # starts the lock and a successful login clears it — deleting here
        # would hand the IP a fresh budget under a stricter policy.
        return
    now = time.time()
    if now >= locked_at + locked_duration:
        # The lock served the full sentence of the duration in force when it
        # started — a later duration increase must not resurrect it.
        if _login_attempts.get(ip) == record:
            del _login_attempts[ip]
        return
    if now < locked_at + lockout_seconds:
        # Still locked. The sentence now follows the current duration, and
        # that evaluation is committed — including decreases — so the stored
        # sentence always matches the policy the lock was last evaluated
        # under; a later raise can never resurrect time the lock already
        # served under a shorter policy.
        if lockout_seconds != locked_duration and _login_attempts.get(ip) == record:
            _login_attempts[ip] = (fail_count, locked_at, lockout_seconds)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
        )
    # Original sentence still running, but the current (lowered) duration has
    # already elapsed — release early.
    if _login_attempts.get(ip) == record:
        del _login_attempts[ip]


_MAX_TRACKED_IPS = 10000


def _record_failure_under_policy(ip: str, max_attempts: int, lockout_seconds: float) -> None:
    """Apply one failed login to the counter under an explicit policy."""
    # Evict expired lockouts when dict grows too large. Expiry is a property
    # of each record's own committed sentence — `t > 0 and now >= t + d` —
    # independent of the live threshold: a record locked under an old, lower
    # threshold must still be swept once its sentence is served, even if the
    # current max has moved past its count. Gating on the current threshold
    # here would retain expired records while the capacity fallback below
    # evicts live counters (they sort first), granting active offenders
    # fresh budgets.
    if len(_login_attempts) >= _MAX_TRACKED_IPS:
        now = time.time()
        expired = [k for k, (c, t, d) in _login_attempts.items() if t > 0.0 and now >= t + d]
        for k in expired:
            del _login_attempts[k]
        # If still too large, evict cheapest-to-lose half ordered by each
        # record's own expiry: never-locked counters (t + d == 0.0) first,
        # then locked records whose committed sentence expires earliest.
        if len(_login_attempts) >= _MAX_TRACKED_IPS:
            by_time = sorted(_login_attempts.items(), key=lambda kv: kv[1][1] + kv[1][2])
            for k, _ in by_time[: len(by_time) // 2]:
                del _login_attempts[k]

    record = _login_attempts.get(ip)
    if record is None:
        _login_attempts[ip] = (1, 0.0, 0.0)
    else:
        new_count = record[0] + 1
        if new_count >= max_attempts:
            _login_attempts[ip] = (new_count, time.time(), lockout_seconds)
        else:
            _login_attempts[ip] = (new_count, 0.0, 0.0)


async def _record_login_failure(ip: str) -> None:
    """Record a failed login attempt for the given IP.

    Policy resolution runs off the event loop (see ``_check_rate_limit``):
    this is the first config read for a previously clean IP, and the login
    endpoint is unauthenticated.
    """
    try:
        max_attempts, lockout_seconds = await asyncio.to_thread(_login_throttle_policy)
    except Exception:
        # A malformed config keeps failing loudly, but dropping the failure
        # here would leave the IP clean — and a clean IP skips the config
        # read in _check_rate_limit, so every subsequent wrong password would
        # reach authenticate() again: unlimited password verification for as
        # long as the file stays broken. Count under the model defaults so
        # the throttle fails closed (the next check reads the broken config
        # before authenticate), then re-raise.
        from deerflow.config.auth_config import LocalAuthConfig

        fallback = LocalAuthConfig()
        _record_failure_under_policy(ip, fallback.max_login_attempts, fallback.lockout_seconds)
        raise
    _record_failure_under_policy(ip, max_attempts, lockout_seconds)


def _record_login_success(ip: str) -> None:
    """Clear failure counter for the given IP on successful login."""
    _login_attempts.pop(ip, None)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/login/local", response_model=LoginResponse)
async def login_local(
    request: Request,
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    remember_me: bool = Form(default=True),
):
    """Local email/password login."""
    client_ip = _get_client_ip(request)
    await _check_rate_limit(client_ip)

    user = await get_local_provider().authenticate({"email": form_data.username, "password": form_data.password})

    if user is None:
        await _record_login_failure(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(code=AuthErrorCode.INVALID_CREDENTIALS, message="Incorrect email or password").model_dump(),
        )

    _record_login_success(client_ip)
    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request, remember_me=remember_me)

    return LoginResponse(
        expires_in=get_auth_config().token_expiry_days * 24 * 3600,
        needs_setup=user.needs_setup,
    )


def _local_registration_enabled() -> bool:
    """Whether visitors may self-register a local account.

    Local registration bypasses the OIDC provisioning policy entirely
    (allowed_email_domains, require_verified_email, auto_create_users are only
    enforced in the SSO callback), so SSO-provisioned deployments need a way to
    close this path.

    ``config.yaml`` is absent in bare-app contexts that never load it (tests build the
    gateway without one). Registration was unconditionally open before this gate existed,
    so an absent config file falls back to that same default rather than turning these two
    endpoints into a hard dependency on the file. Only ``FileNotFoundError`` is caught:
    a malformed config must not silently re-open a closed deployment, so it propagates.

    ``/register`` reads this fresh on every request (``get_app_config`` reloads on file
    change); ``/setup-status`` may serve it up to 60s stale via its per-IP result cache.
    """
    from deerflow.config.app_config import get_app_config

    try:
        return get_app_config().auth.local.allow_registration
    except FileNotFoundError:
        return True


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(request: Request, response: Response, body: RegisterRequest):
    """Register a new user account (always 'user' role).

    The first admin is created explicitly through /initialize. This endpoint creates regular users.
    Auto-login by setting the session cookie.

    Returns 403 when ``auth.local.allow_registration`` is false.
    """
    if not _local_registration_enabled():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=AuthErrorResponse(code=AuthErrorCode.REGISTRATION_DISABLED, message="Self-registration is disabled on this deployment").model_dump(),
        )

    try:
        user = await get_local_provider().create_user(email=body.email, password=body.password, system_role="user")
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=AuthErrorResponse(code=AuthErrorCode.EMAIL_ALREADY_EXISTS, message="Email already registered").model_dump(),
        )

    token = create_access_token(str(user.id), token_version=user.token_version)
    _set_session_cookie(response, token, request, remember_me=body.remember_me)

    return UserResponse(id=str(user.id), email=user.email, system_role=user.system_role, oauth_provider=user.oauth_provider)


@router.post("/logout", response_model=MessageResponse)
async def logout(request: Request, response: Response):
    """Logout current user by clearing the cookie."""
    is_https = is_secure_request(request)
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE_NAME, secure=is_https, samesite="lax")
    response.delete_cookie(key=CSRF_COOKIE_NAME, secure=is_https, samesite="strict")
    response.delete_cookie(key=SESSION_PERSISTENCE_COOKIE_NAME, secure=is_https, samesite="lax")
    setattr(request.state, SKIP_AUTH_CSRF_COOKIE_STATE_ATTR, True)
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
    from app.gateway.auth_disabled import AUTH_SOURCE_AUTH_DISABLED, AUTH_SOURCE_PAT

    user = await get_current_user_from_request(request)

    if getattr(request.state, "auth_source", None) in {AUTH_SOURCE_PAT, AUTH_SOURCE_AUTH_DISABLED}:
        # PAT-authenticated callers must not alter auth state (#4849 point 6);
        # auth-disabled mode has no passwords to change.
        if getattr(request.state, "auth_source", None) == AUTH_SOURCE_PAT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Password changes require interactive session authentication",
            )
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
    _set_session_cookie(response, token, request, remember_me=body.remember_me)
    _set_csrf_cookie(response, request)

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


# ── Personal Access Tokens (#4849) ────────────────────────────────────────


def require_session_source(request: Request) -> None:
    """Reject non-session credentials from auth-state-altering routes.

    PAT-authenticated callers must not manage PATs or change passwords
    (#4849 point 6): a leaked automation token could otherwise mint fresh
    long-lived credentials or lock out the human owner.
    """
    from app.gateway.auth_disabled import AUTH_SOURCE_SESSION

    if getattr(request.state, "auth_source", None) != AUTH_SOURCE_SESSION:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This endpoint requires interactive session authentication")


class PATCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=PAT_MAX_NAME_LENGTH)
    scopes: list[str] = Field(min_length=1)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)  # None = never expires

    @field_validator("name")
    @classmethod
    def _strip_and_require_non_empty_name(cls, value: str) -> str:
        # A whitespace-only name passes min_length but would persist as an
        # empty label; the trimmed value is what gets stored and shown.
        stripped = value.strip()
        if not stripped:
            raise ValueError("PAT name must contain at least one non-whitespace character")
        return stripped


class PATCreatedResponse(BaseModel):
    """Create response — ``token`` is the raw show-once credential."""

    id: str
    name: str
    scopes: list[str]
    expires_at: str | None
    created_at: str
    token: str


class PATSummaryResponse(BaseModel):
    id: str
    name: str
    scopes: list[str]
    expires_at: str | None
    last_used_at: str | None
    created_at: str
    revoked_at: str | None


def _pat_summary(record: dict) -> PATSummaryResponse:
    return PATSummaryResponse(
        id=str(record["id"]),
        name=str(record["name"]),
        scopes=list(record.get("scopes") or []),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        last_used_at=str(record["last_used_at"]) if record.get("last_used_at") else None,
        created_at=str(record["created_at"]),
        revoked_at=str(record["revoked_at"]) if record.get("revoked_at") else None,
    )


@router.post("/pats", status_code=status.HTTP_201_CREATED, response_model=PATCreatedResponse, dependencies=[Depends(require_session_source)])
async def create_pat(request: Request, body: PATCreateRequest):
    """Create a personal access token for the session user.

    The raw token is returned exactly once and cannot be retrieved again;
    only its SHA-256 digest is persisted.
    """
    from datetime import UTC, datetime, timedelta

    from app.gateway.auth.pat import generate_pat_token, pat_token_digest, validate_scopes
    from app.gateway.deps import get_pat_repo

    user = await get_current_user_from_request(request)
    try:
        scopes = validate_scopes(body.scopes)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    token = generate_pat_token()
    expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days) if body.expires_in_days is not None else None
    record = await get_pat_repo(request).create(
        user_id=str(user.id),
        name=body.name.strip(),
        scopes=scopes,
        token_digest=pat_token_digest(token),
        expires_at=expires_at,
    )
    return PATCreatedResponse(
        id=str(record["id"]),
        name=str(record["name"]),
        scopes=list(record.get("scopes") or []),
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        created_at=str(record["created_at"]),
        token=token,
    )


@router.get("/pats", response_model=list[PATSummaryResponse], dependencies=[Depends(require_session_source)])
async def list_pats(request: Request):
    """List the session user's tokens. Never returns digests or raw tokens."""
    from app.gateway.deps import get_pat_repo

    user = await get_current_user_from_request(request)
    records = await get_pat_repo(request).list_for_user(str(user.id))
    return [_pat_summary(record) for record in records]


@router.delete("/pats/{pat_id}", response_model=MessageResponse, dependencies=[Depends(require_session_source)])
async def revoke_pat(request: Request, pat_id: str):
    """Revoke one of the session user's tokens. Revocation is immediate."""
    from app.gateway.deps import get_pat_repo

    user = await get_current_user_from_request(request)
    revoked = await get_pat_repo(request).revoke(pat_id, str(user.id))
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return MessageResponse(message="Token revoked")


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
                return {"needs_setup": admin_count == 0, "registration_enabled": _local_registration_enabled()}

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
    remember_me: bool = True

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
    _set_session_cookie(response, token, request, remember_me=body.remember_me)

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
    secure, max_age = auth_csrf_cookie_settings(request)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=csrf_token,
        httponly=False,  # Must be JS-readable for Double Submit Cookie pattern
        secure=secure,
        samesite="strict",
        # Persist for the same lifetime as the access_token (see _set_session_cookie)
        # so the double-submit pair is evicted together, never leaving a logged-in
        # session whose csrf_token was dropped (e.g. iOS Safari PWA termination).
        max_age=max_age,
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
    remember_me: bool = True,
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
        remember_me=remember_me,
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

    # Revalidate as defense-in-depth if future state writers populate this target.
    redirect_target = validate_next_param(state_payload.next_path) or "/workspace"
    frontend_base = oidc_config.frontend_base_url or ""
    callback_redirect = f"{frontend_base}/auth/callback?next={urllib.parse.quote(redirect_target)}"

    redirect_response = RedirectResponse(url=callback_redirect, status_code=status.HTTP_302_FOUND)

    # Set session cookie (reuse existing helper)
    _set_session_cookie(redirect_response, token, request, remember_me=state_payload.remember_me)

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
    URLs (``//``), absolute URLs, URLs with embedded protocols, and backslashes
    that URL parsers may reinterpret as forward slashes.
    """
    if not next_param:
        return None
    if not next_param.startswith("/"):
        return None
    if next_param.startswith("//") or next_param.startswith("http://") or next_param.startswith("https://"):
        return None
    if "\\" in next_param:
        return None
    if ":" in next_param:
        return None
    return next_param
