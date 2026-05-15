from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict


class UserNotFoundError(LookupError):
    """Raised when an update targets a user row that no longer exists."""


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    email: str
    password_hash: str | None = None
    system_role: Literal["admin", "user"] = "user"
    created_at: datetime | None = None
    oauth_provider: str | None = None
    oauth_id: str | None = None
    needs_setup: bool = False
    token_version: int = 0


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    email: str
    password_hash: str | None
    system_role: Literal["admin", "user"]
    created_at: datetime
    oauth_provider: str | None
    oauth_id: str | None
    needs_setup: bool
    token_version: int


class UserRepositoryProtocol(Protocol):
    async def create_user(self, data: UserCreate) -> User:
        pass

    async def get_user_by_id(self, user_id: str) -> User | None:
        pass

    async def get_user_by_email(self, email: str) -> User | None:
        pass

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        pass

    async def get_first_admin(self) -> User | None:
        pass

    async def update_user(self, data: User) -> User:
        pass

    async def count_users(self) -> int:
        pass

    async def count_admin_users(self) -> int:
        pass
