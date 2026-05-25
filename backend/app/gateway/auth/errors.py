"""Typed error definitions for auth module.

AuthErrorCode: exhaustive enum of all auth failure conditions.
TokenError: exhaustive enum of JWT decode failures.
AuthErrorResponse: structured error payload for HTTP responses.
AuthErrorCategory: user-facing error classification per spec.
"""

from enum import StrEnum

from pydantic import BaseModel, model_validator


class AuthErrorCategory(StrEnum):
    """User-facing auth error categories (ISSUE-08 §1.1).

    These map to the four canonical user-visible error codes:
      AUTH_INVALID_TOKEN  → 401
      AUTH_FORBIDDEN      → 403
      TENANT_CONFIG_ERROR → 400/500
      AUTH_UPSTREAM_UNAVAILABLE → 503
    """

    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_FORBIDDEN = "AUTH_FORBIDDEN"
    TENANT_CONFIG_ERROR = "TENANT_CONFIG_ERROR"
    AUTH_UPSTREAM_UNAVAILABLE = "AUTH_UPSTREAM_UNAVAILABLE"


class AuthErrorCode(StrEnum):
    """Exhaustive list of auth error conditions (internal detail).

    User-facing category is derived via :func:`auth_error_category`.
    """

    INVALID_CREDENTIALS = "invalid_credentials"
    TOKEN_EXPIRED = "token_expired"
    TOKEN_INVALID = "token_invalid"
    USER_NOT_FOUND = "user_not_found"
    EMAIL_ALREADY_EXISTS = "email_already_exists"
    PROVIDER_NOT_FOUND = "provider_not_found"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NOT_AUTHENTICATED = "not_authenticated"
    SYSTEM_ALREADY_INITIALIZED = "system_already_initialized"
    TENANT_SELECTION_REQUIRED = "tenant_selection_required"
    TENANT_CONFIG_ERROR = "tenant_config_error"
    PERMISSION_DENIED = "permission_denied"
    TENANT_NOT_FOUND = "tenant_not_found"
    TENANT_DISABLED = "tenant_disabled"


class TokenError(StrEnum):
    """Exhaustive list of JWT decode failure reasons."""

    EXPIRED = "expired"
    INVALID_SIGNATURE = "invalid_signature"
    MALFORMED = "malformed"


class AuthErrorResponse(BaseModel):
    """Structured error response — replaces bare ``detail`` strings.

    ``category`` is auto-derived from ``code`` via :func:`auth_error_category`.
    Callers only need to set ``code`` and ``message``.
    """

    code: AuthErrorCode
    message: str
    category: AuthErrorCategory | None = None
    tenants: list[dict] | None = None

    @model_validator(mode="after")
    def _set_category(self) -> "AuthErrorResponse":
        if self.category is None:
            self.category = auth_error_category(self.code)
        return self


def auth_error_category(code: AuthErrorCode) -> AuthErrorCategory:
    """Map a granular ``AuthErrorCode`` to its user-facing category.

    Single source of truth — every code maps to exactly one category.
    """
    _MAP: dict[AuthErrorCode, AuthErrorCategory] = {
        AuthErrorCode.INVALID_CREDENTIALS: AuthErrorCategory.AUTH_INVALID_TOKEN,
        AuthErrorCode.TOKEN_EXPIRED: AuthErrorCategory.AUTH_INVALID_TOKEN,
        AuthErrorCode.TOKEN_INVALID: AuthErrorCategory.AUTH_INVALID_TOKEN,
        AuthErrorCode.USER_NOT_FOUND: AuthErrorCategory.AUTH_INVALID_TOKEN,
        AuthErrorCode.NOT_AUTHENTICATED: AuthErrorCategory.AUTH_INVALID_TOKEN,
        AuthErrorCode.PROVIDER_NOT_FOUND: AuthErrorCategory.AUTH_UPSTREAM_UNAVAILABLE,
        AuthErrorCode.PROVIDER_UNAVAILABLE: AuthErrorCategory.AUTH_UPSTREAM_UNAVAILABLE,
        AuthErrorCode.PERMISSION_DENIED: AuthErrorCategory.AUTH_FORBIDDEN,
        AuthErrorCode.TENANT_CONFIG_ERROR: AuthErrorCategory.TENANT_CONFIG_ERROR,
        AuthErrorCode.TENANT_SELECTION_REQUIRED: AuthErrorCategory.TENANT_CONFIG_ERROR,
        AuthErrorCode.SYSTEM_ALREADY_INITIALIZED: AuthErrorCategory.AUTH_FORBIDDEN,
        AuthErrorCode.TENANT_NOT_FOUND: AuthErrorCategory.TENANT_CONFIG_ERROR,
        AuthErrorCode.TENANT_DISABLED: AuthErrorCategory.TENANT_CONFIG_ERROR,
    }
    return _MAP.get(code, AuthErrorCategory.AUTH_INVALID_TOKEN)


def token_error_to_code(err: TokenError) -> AuthErrorCode:
    """Map TokenError to AuthErrorCode — single source of truth."""
    if err == TokenError.EXPIRED:
        return AuthErrorCode.TOKEN_EXPIRED
    return AuthErrorCode.TOKEN_INVALID
