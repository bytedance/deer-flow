"""User Pydantic models for authentication."""

from datetime import UTC, datetime
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
    # Plain string on purpose: the DB column is String(16) and the RBAC
    # provider accepts arbitrary configured role names (RFC #4063 gap 2 —
    # custom roles must be assignable to authenticated users). "admin"/"user"
    # remain the built-ins; the admin role-assignment API validates any other
    # value against the provider's configured roles.
    system_role: str = Field(default="user", min_length=1)
    created_at: datetime = Field(default_factory=_utc_now)

    # OAuth linkage (optional)
    oauth_provider: str | None = Field(None, description="e.g. 'github', 'google'")
    oauth_id: str | None = Field(None, description="User ID from OAuth provider")

    # Auth lifecycle
    needs_setup: bool = Field(default=False, description="True when a reset account must complete setup")
    token_version: int = Field(default=0, description="Incremented on password change to invalidate old JWTs")
    # Account lifecycle (RFC #4063 / #3462 gap 3): a disabled account is
    # rejected at every authentication surface; the row (credentials, role,
    # OAuth linkage) is retained so re-enabling restores what was suspended.
    disabled: bool = Field(default=False)


class UserResponse(BaseModel):
    """Response model for user info endpoint."""

    id: str
    email: str
    system_role: str = Field(..., min_length=1)
    disabled: bool = False
    needs_setup: bool = False
    oauth_provider: str | None = Field(None, description="OAuth/SSO provider ID if the user logged in via SSO (e.g. 'keycloak')")
    permissions: list[str] | None = Field(
        None,
        description=("Effective route permissions granted to this credential (RFC #4063 Phase 4). Only GET /api/v1/auth/me resolves them; credential-creation responses leave it None."),
    )
