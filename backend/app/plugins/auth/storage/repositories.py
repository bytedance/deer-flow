from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.plugins.auth.storage.contracts import User, UserCreate, UserRepositoryProtocol
from app.plugins.auth.storage.models import User as UserModel


def _to_user(model: UserModel) -> User:
    return User(
        id=model.id,
        email=model.email,
        password_hash=model.password_hash,
        system_role=model.system_role,
        oauth_provider=model.oauth_provider,
        oauth_id=model.oauth_id,
        needs_setup=model.needs_setup,
        token_version=model.token_version,
        created_time=model.created_time,
        updated_time=model.updated_time,
    )


class DbUserRepository(UserRepositoryProtocol):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(self, data: UserCreate) -> User:
        model = UserModel(
            id=data.id,
            email=data.email,
            password_hash=data.password_hash,
            system_role=data.system_role,
            oauth_provider=data.oauth_provider,
            oauth_id=data.oauth_id,
            needs_setup=data.needs_setup,
            token_version=data.token_version,
        )
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ValueError("User already exists") from exc
        await self._session.refresh(model)
        return _to_user(model)

    async def get_user_by_id(self, user_id: str) -> User | None:
        model = await self._session.get(UserModel, user_id)
        return _to_user(model) if model else None

    async def get_user_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        model = result.scalar_one_or_none()
        return _to_user(model) if model else None

    async def get_user_by_oauth(self, provider: str, oauth_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(
                UserModel.oauth_provider == provider,
                UserModel.oauth_id == oauth_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_user(model) if model else None

    async def update_user(self, data: User) -> User:
        model = await self._session.get(UserModel, data.id)
        if model is None:
            raise LookupError(f"User {data.id} not found")
        model.email = data.email
        model.password_hash = data.password_hash
        model.system_role = data.system_role
        model.oauth_provider = data.oauth_provider
        model.oauth_id = data.oauth_id
        model.needs_setup = data.needs_setup
        model.token_version = data.token_version
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ValueError("User already exists") from exc
        await self._session.refresh(model)
        return _to_user(model)

    async def count_users(self) -> int:
        return await self._session.scalar(select(func.count()).select_from(UserModel)) or 0

    async def count_admin_users(self) -> int:
        return (
            await self._session.scalar(
                select(func.count()).select_from(UserModel).where(UserModel.system_role == "admin")
            )
            or 0
        )
