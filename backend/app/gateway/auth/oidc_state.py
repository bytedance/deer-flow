"""OIDC state management via signed HttpOnly cookies.

Stores OIDC state, nonce, and PKCE verifier in a short-lived signed cookie
instead of server-side storage. This keeps the implementation stateless and
compatible with multi-worker deployments without Redis.
"""

from __future__ import annotations

import secrets
import time

import jwt
from fastapi import Request, Response
from pydantic import BaseModel, Field

from app.gateway.auth.config import get_auth_config
from app.gateway.csrf_middleware import is_secure_request

OIDC_STATE_COOKIE_PREFIX = "df_oidc_state_"
OIDC_STATE_MAX_AGE = 300  # 5 minutes
OIDC_STATE_BYTES = 32
OIDC_NONCE_BYTES = 16
OIDC_CODE_VERIFIER_BYTES = 32


class OIDCStatePayload(BaseModel):
    """Payload stored inside the signed OIDC state cookie."""

    provider: str = Field(description="OIDC provider ID (must match the state cookie)")  # noqa: E501
    state: str = Field(description="Cryptographically random state value — compared in constant time with the query param")  # noqa: E501
    nonce: str | None = Field(default=None, description="OIDC nonce, verified against the ID token nonce claim")
    code_verifier: str | None = Field(default=None, description="PKCE code verifier, sent during token exchange")
    next_path: str = Field(default="/workspace", description="Redirect target after successful auth")
    remember_me: bool = Field(default=True, description="Whether the resulting DeerFlow session should be persistent")
    issued_at: float = Field(default_factory=time.time, description="Unix timestamp of cookie creation")


def _sign_state_payload(payload: OIDCStatePayload) -> str:
    """Sign the state payload with the JWT secret to prevent tampering."""
    secret = get_auth_config().jwt_secret
    return jwt.encode(payload.model_dump(), secret, algorithm="HS256")


def _verify_state_signed(signed: str, max_age: int = OIDC_STATE_MAX_AGE) -> OIDCStatePayload | None:
    """Verify a signed state payload and return it, or None if invalid/expired."""
    secret = get_auth_config().jwt_secret
    try:
        decoded = jwt.decode(signed, secret, algorithms=["HS256"])
        payload = OIDCStatePayload(**decoded)
        if time.time() - payload.issued_at > max_age:
            return None
        return payload
    except jwt.PyJWTError:
        return None


def generate_oidc_state() -> str:
    """Generate a cryptographically random state string."""
    return secrets.token_urlsafe(OIDC_STATE_BYTES)


def generate_nonce() -> str:
    """Generate a cryptographically random nonce for ID token validation."""
    return secrets.token_urlsafe(OIDC_NONCE_BYTES)


def generate_code_verifier() -> str:
    """Generate a PKCE code verifier (plain random string)."""
    return secrets.token_urlsafe(OIDC_CODE_VERIFIER_BYTES)


def compute_code_challenge(verifier: str) -> str:
    """Compute the S256 PKCE code challenge from a verifier."""
    import hashlib

    return _base64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())


def _base64url_encode(data: bytes) -> str:
    """Base64url-encode without padding, as required by RFC 7636 and OIDC."""
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _cookie_name(provider: str) -> str:
    return f"{OIDC_STATE_COOKIE_PREFIX}{provider}"


def set_state_cookie(response: Response, request: Request, payload: OIDCStatePayload) -> None:
    """Set the signed OIDC state cookie on the response."""
    signed = _sign_state_payload(payload)
    is_https = is_secure_request(request)
    response.set_cookie(
        key=_cookie_name(payload.provider),
        value=signed,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=OIDC_STATE_MAX_AGE,
        path=f"/api/v1/auth/callback/{payload.provider}",
    )


def get_state_cookie(request: Request, provider: str) -> OIDCStatePayload | None:
    """Read and verify the signed OIDC state cookie for the given provider."""
    signed = request.cookies.get(_cookie_name(provider))
    if not signed:
        return None
    return _verify_state_signed(signed)


def delete_state_cookie(response: Response, request: Request, provider: str) -> None:
    """Delete the OIDC state cookie."""
    is_https = is_secure_request(request)
    response.delete_cookie(
        key=_cookie_name(provider),
        secure=is_https,
        samesite="lax",
        path=f"/api/v1/auth/callback/{provider}",
    )
