"""Pydantic models for authentication requests and responses."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class User(BaseModel):
    """Internal user representation."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4, description="Primary key")
    email: EmailStr = Field(..., description="Unique email address")
    password_hash: str | None = Field(None, description="bcrypt hash, nullable for OAuth users")
    system_role: Literal["admin", "user"] = Field(default="user")
    created_at: datetime = Field(default_factory=_utc_now)

    # OAuth linkage (optional)
    oauth_provider: str | None = Field(None, description="e.g. 'github', 'google'")
    oauth_id: str | None = Field(None, description="User ID from OAuth provider")

    # Auth lifecycle
    needs_setup: bool = Field(default=False, description="True for auto-created admin until setup completes")
    token_version: int = Field(default=0, description="Incremented on password change to invalidate old JWTs")

    # Multi-tenant
    tenant_id: str = Field(default="default", description="Tenant this user belongs to")


class UserResponse(BaseModel):
    """Response model for user info endpoint."""

    id: str
    email: str
    system_role: Literal["admin", "user"]
    needs_setup: bool = False
    tenant_id: str = "default"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, description="Username")
    password: str = Field(min_length=1, description="Password")


class TokenResponse(BaseModel):
    access_token: str = Field(description="JWT access token")
    token_type: str = Field(default="bearer", description="Token type")
    expires_in: int = Field(description="Token expiry in seconds")


class RefreshRequest(BaseModel):
    access_token: str = Field(description="Current (possibly expired) access token")


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human-readable name for this API key")


class ApiKeyResponse(BaseModel):
    id: str = Field(description="Unique key identifier")
    name: str = Field(description="Human-readable name")
    key_prefix: str = Field(description="First 8 characters of the key for identification")
    created_at: str = Field(description="ISO-8601 creation timestamp")
    last_used_at: str | None = Field(default=None, description="ISO-8601 last-used timestamp")


class ApiKeyCreateResponse(BaseModel):
    id: str = Field(description="Unique key identifier")
    name: str = Field(description="Human-readable name")
    raw_key: str = Field(description="The full API key — shown only once")
    key_prefix: str = Field(description="First 8 characters of the key for identification")
    created_at: str = Field(description="ISO-8601 creation timestamp")
