from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _new_user_id() -> str:
    return str(uuid4())


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=_new_user_id)
    email: str
    password_hash: str | None = None
    system_role: str = "user"
    oauth_provider: str | None = None
    oauth_id: str | None = None
    needs_setup: bool = False
    token_version: int = 0


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    email: str
    password_hash: str | None
    system_role: str
    oauth_provider: str | None
    oauth_id: str | None
    needs_setup: bool
    token_version: int
    created_time: datetime
    updated_time: datetime | None


class UserRepositoryProtocol(Protocol):
    async def create_user(self, data: UserCreate) -> User: ...

    async def get_user_by_id(self, user_id: str) -> User | None: ...

    async def get_user_by_email(self, email: str) -> User | None: ...

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None: ...

    async def update_user(self, data: User) -> User: ...

    async def count_users(self) -> int: ...

    async def count_admin_users(self) -> int: ...
