"""Authentication models for JWT tokens."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    """User roles for multi-tenant authentication."""

    USER = "user"
    ADMIN = "admin"


class TokenData(BaseModel):
    """JWT token payload data."""

    user_id: str = Field(..., description="User ID from token 'sub' claim (UUID as string)")
    email: str | None = Field(default=None, description="User email from token")
    role: UserRole = Field(default=UserRole.USER, description="User role")


class User(BaseModel):
    """User model for authentication."""

    user_id: UUID = Field(..., description="User ID (UUID primary key)")
    email: str = Field(..., description="User email")
    hashed_password: str = Field(..., description="Hashed password")
    role: UserRole = Field(default=UserRole.USER, description="User role")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Account creation time")
    quota_limits: dict[str, int | float] | None = Field(default=None, description="Resource quota limits")


class AuthenticationError(Exception):
    """Authentication error with detail message."""

    def __init__(self, detail: str = "Could not validate credentials") -> None:
        self.detail = detail
        super().__init__(detail)
