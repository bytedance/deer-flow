"""OIDC / SSO authentication configuration models."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean

from deerflow.config.reload_boundary import format_field_description


class OIDCProviderConfig(BaseModel):
    """Configuration for a single OIDC identity provider (Keycloak, Google, Azure AD, etc.)."""

    display_name: str = Field(description="Human-readable name shown on the login button")
    issuer: str = Field(description="OIDC issuer URL (e.g. https://keycloak.example.com/realms/deerflow)")
    client_id: str = Field(description="OAuth2 client ID assigned by the provider")
    client_secret: str | None = Field(default=None, description="OAuth2 client secret ($ENV_VAR references supported)")
    redirect_uri: str | None = Field(default=None, description="Callback URL the provider will redirect to after auth")
    scopes: list[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="OIDC scopes to request (must include openid)",
    )
    token_endpoint_auth_method: Literal["client_secret_post", "client_secret_basic", "none"] = Field(
        default="client_secret_post",
        description="How the client authenticates at the token endpoint",
    )

    # ── User provisioning ─────────────────────────────────────────────
    auto_create_users: bool = Field(
        default=True,
        description="Automatically create a DeerFlow user on first SSO login",
    )
    require_verified_email: bool = Field(
        default=True,
        description="Reject authentication if the provider does not report the email as verified",
    )
    allowed_email_domains: list[str] = Field(
        default_factory=list,
        description="If non-empty, only allow users whose email domain is in this list (e.g. ['example.com'])",
    )
    admin_emails: list[str] = Field(
        default_factory=list,
        description="Users with these email addresses are automatically granted the admin role on first login",
    )

    # ── PKCE / nonce ──────────────────────────────────────────────────
    pkce_enabled: bool = Field(default=True, description="Enable PKCE (S256) for the authorization code flow")
    nonce_enabled: bool = Field(default=True, description="Include and validate the nonce claim in ID tokens")

    # ── Endpoint overrides (for providers with non-standard discovery) ─
    authorization_endpoint: str | None = Field(default=None)
    token_endpoint: str | None = Field(default=None)
    userinfo_endpoint: str | None = Field(default=None)
    jwks_uri: str | None = Field(default=None)


class OIDCAuthConfig(BaseModel):
    """Top-level OIDC authentication configuration."""

    enabled: bool = Field(default=False, description="Enable OIDC SSO authentication")
    frontend_base_url: str | None = Field(
        default=None,
        description="Base URL of the frontend (used for callback redirects when behind a reverse proxy)",
    )
    providers: dict[str, OIDCProviderConfig] = Field(
        default_factory=dict,
        description="Map of provider IDs to their configuration (e.g. keycloak, google, azure)",
    )


class LoginThrottleStorage(StrEnum):
    """Where the per-IP failed-login counter behind ``POST /api/v1/auth/login/local`` lives."""

    AUTO = "auto"
    MEMORY = "memory"
    DB = "db"


def resolve_login_throttle_storage(selector: LoginThrottleStorage | str | None, database_backend: str | None) -> Literal["memory", "db"]:
    """Resolve ``auth.local.throttle_storage`` against ``database.backend``.

    ``auto`` (the default) shares the counter through the application database
    whenever one exists (``sqlite`` or ``postgres``), so every Gateway replica
    using that database enforces one lockout per IP; a ``memory`` database has
    no shared table and falls back to the per-process counter. ``memory``
    always keeps the per-process counter. ``db`` asks for the shared table and
    degrades to ``memory`` when there is no database to hold it — the caller
    warns about that misconfiguration.
    """
    value = str(selector.value if isinstance(selector, StrEnum) else selector or LoginThrottleStorage.AUTO)
    if value == LoginThrottleStorage.MEMORY:
        return "memory"
    return "db" if database_backend in ("sqlite", "postgres") else "memory"


class LocalAuthConfig(BaseModel):
    """Configuration for the built-in email/password authentication provider."""

    allow_registration: bool = Field(
        default=True,
        description=(
            "Allow visitors to self-register a local account via POST /api/v1/auth/register. "
            "Set to false when accounts are provisioned exclusively through SSO — the OIDC "
            "provisioning policy (allowed_email_domains, require_verified_email, auto_create_users) "
            "does not apply to local registration."
        ),
    )
    max_login_attempts: int = Field(
        default=5,
        ge=2,
        description=(
            "Failed login attempts allowed from one client IP before it is locked out of "
            "POST /api/v1/auth/login/local. Defaults preserve the historical hardcoded policy. "
            "Raise it when many users share an egress IP (corporate proxy / NAT); lower it for "
            "a stricter posture. Minimum 2: one failed attempt must never lock an IP, or a "
            "single typo would block everyone behind a shared egress — the strictest legal "
            "value locks after the second failure. Where the counter lives is decided by "
            "throttle_storage: shared through the application database (the default whenever "
            "one exists) every Gateway replica enforces one limit per IP; the in-process "
            "counter is per worker, so effective attempts scale with the worker count."
        ),
    )
    lockout_seconds: float = Field(
        default=300.0,
        gt=0,
        allow_inf_nan=False,
        description=("Seconds an IP stays locked out after reaching auth.local.max_login_attempts. Defaults preserve the historical hardcoded policy (5 minutes)."),
    )
    throttle_storage: LoginThrottleStorage = Field(
        default=LoginThrottleStorage.AUTO,
        description=format_field_description(
            "auth.local.throttle_storage",
            field_doc=(
                "Where failed-login counters and lockouts for POST /api/v1/auth/login/local are kept. "
                "'auto' uses the application database whenever database.backend is sqlite or postgres, so every "
                "Gateway replica sharing that database enforces one lockout per client IP; with database.backend=memory "
                "it falls back to an in-process counter. 'memory' forces the in-process counter (per process: N replicas "
                "give an attacker N x max_login_attempts guesses and a lockout on one replica is invisible to the others). "
                "'db' forces the shared table: it falls back to memory with a warning when the database backend is memory, and refuses to start when the configured "
                "database's engine is unavailable."
            ),
        ),
    )

    @field_validator("max_login_attempts", mode="before")
    @classmethod
    def _reject_boolean_login_threshold(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @field_validator("lockout_seconds", mode="before")
    @classmethod
    def _reject_boolean_lockout_window(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="a number")


class AuthAppConfig(BaseModel):
    """Authentication configuration section for the DeerFlow app config."""

    oidc: OIDCAuthConfig = Field(default_factory=OIDCAuthConfig, description="OIDC SSO authentication settings")
    local: LocalAuthConfig = Field(default_factory=LocalAuthConfig, description="Built-in email/password authentication settings")
