"""User Pydantic models for authentication."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(UTC)


class User(BaseModel):
    """Internal user representation.

    Enterprise RBAC (M1 / RFC §11.5) widens ``system_role`` from a
    closed ``Literal["admin", "user"]`` to plain ``str`` and adds a
    multi-valued ``roles`` field. Both changes are backwards-compatible:

    * ``system_role: str`` is a type *widening* — every former
      ``Literal`` value still parses, so existing JWTs and DB rows
      deserialize unchanged.
    * ``roles: list[str]`` defaults to ``[]`` so callers that do not opt
      into enterprise RBAC keep the previous shape.

    Permission resolution now reads both fields:
    ``RbacPermissionProvider`` prefers ``roles`` when non-empty and
    falls back to mapping ``system_role`` (see
    ``deerflow.enterprise.rbac.permission_provider``).
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(default_factory=uuid4, description="Primary key")
    email: EmailStr = Field(..., description="Unique email address")
    password_hash: str | None = Field(None, description="bcrypt hash, nullable for OAuth users")
    system_role: str = Field(
        default="user",
        description="Legacy system role label (`admin` / `user`). Widened from Literal to str for enterprise RBAC — see RFC §11.5",
    )
    roles: list[str] = Field(
        default_factory=list,
        description="Enterprise RBAC roles assigned to the user (empty list = fall back to system_role mapping)",
    )
    created_at: datetime = Field(default_factory=_utc_now)

    # OAuth linkage (optional)
    oauth_provider: str | None = Field(None, description="e.g. 'github', 'google'")
    oauth_id: str | None = Field(None, description="User ID from OAuth provider")

    # Auth lifecycle
    needs_setup: bool = Field(default=False, description="True when a reset account must complete setup")
    token_version: int = Field(default=0, description="Incremented on password change to invalidate old JWTs")


class UserResponse(BaseModel):
    """Response model for user info endpoint.

    ``system_role`` is exposed as ``str`` to match the widened ``User``
    field (RFC §11.5). Clients that previously assumed only ``"admin"``
    / ``"user"`` continue to receive those values for unchanged users —
    new role strings only appear when an operator assigns them.
    """

    id: str
    email: str
    system_role: str
    roles: list[str] = Field(default_factory=list, description="Enterprise RBAC roles")
    needs_setup: bool = False
