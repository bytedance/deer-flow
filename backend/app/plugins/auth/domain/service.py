from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.plugins.auth.domain.errors import AuthErrorCode
from app.plugins.auth.domain.models import User
from app.plugins.auth.domain.password import hash_password_async, verify_password_async
from app.plugins.auth.storage import DbUserRepository, UserCreate
from app.plugins.auth.storage.contracts import User as StoreUser


@dataclass(slots=True)
class AuthServiceError(Exception):
    code: AuthErrorCode
    message: str
    status_code: int


def _to_auth_user(user: StoreUser) -> User:
    return User(
        id=UUID(user.id),
        email=user.email,
        password_hash=user.password_hash,
        system_role=user.system_role,  # type: ignore[arg-type]
        created_at=user.created_time,
        oauth_provider=user.oauth_provider,
        oauth_id=user.oauth_id,
        needs_setup=user.needs_setup,
        token_version=user.token_version,
    )


def _to_store_user(user: User) -> StoreUser:
    return StoreUser(
        id=str(user.id),
        email=user.email,
        password_hash=user.password_hash,
        system_role=user.system_role,
        oauth_provider=user.oauth_provider,
        oauth_id=user.oauth_id,
        needs_setup=user.needs_setup,
        token_version=user.token_version,
        created_time=user.created_at,
        updated_time=None,
    )


class AuthService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def login_local(self, email: str, password: str) -> User:
        async with self._session_factory() as session:
            repo = DbUserRepository(session)
            user = await repo.get_user_by_email(email)
            if user is None or user.password_hash is None:
                raise AuthServiceError(
                    code=AuthErrorCode.INVALID_CREDENTIALS,
                    message="Incorrect email or password",
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
            if not await verify_password_async(password, user.password_hash):
                raise AuthServiceError(
                    code=AuthErrorCode.INVALID_CREDENTIALS,
                    message="Incorrect email or password",
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
            return _to_auth_user(user)

    async def register(self, email: str, password: str) -> User:
        async with self._session_factory() as session:
            repo = DbUserRepository(session)
            try:
                user = await repo.create_user(
                    UserCreate(
                        email=email,
                        password_hash=await hash_password_async(password),
                        system_role="user",
                    )
                )
                await session.commit()
            except ValueError as exc:
                await session.rollback()
                raise AuthServiceError(
                    code=AuthErrorCode.EMAIL_ALREADY_EXISTS,
                    message="Email already registered",
                    status_code=HTTPStatus.BAD_REQUEST,
                ) from exc
            return _to_auth_user(user)

    async def change_password(
        self,
        user: User | StoreUser,
        *,
        current_password: str,
        new_password: str,
        new_email: str | None = None,
    ) -> User:
        if user.password_hash is None:
            raise AuthServiceError(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="OAuth users cannot change password",
                status_code=HTTPStatus.BAD_REQUEST,
            )
        if not await verify_password_async(current_password, user.password_hash):
            raise AuthServiceError(
                code=AuthErrorCode.INVALID_CREDENTIALS,
                message="Current password is incorrect",
                status_code=HTTPStatus.BAD_REQUEST,
            )

        async with self._session_factory() as session:
            repo = DbUserRepository(session)
            updated_email = user.email
            if new_email is not None:
                existing = await repo.get_user_by_email(new_email)
                if existing and existing.id != str(user.id):
                    raise AuthServiceError(
                        code=AuthErrorCode.EMAIL_ALREADY_EXISTS,
                        message="Email already in use",
                        status_code=HTTPStatus.BAD_REQUEST,
                    )
                updated_email = new_email

            updated_user = user.model_copy(
                update={
                    "email": updated_email,
                    "password_hash": await hash_password_async(new_password),
                    "token_version": user.token_version + 1,
                    "needs_setup": False if user.needs_setup and new_email is not None else user.needs_setup,
                }
            )

            updated = await repo.update_user(_to_store_user(_to_auth_user(updated_user) if isinstance(updated_user, StoreUser) else updated_user))
            await session.commit()
            return _to_auth_user(updated)

    async def get_setup_status(self) -> bool:
        async with self._session_factory() as session:
            repo = DbUserRepository(session)
            admin_count = await repo.count_admin_users()
            return admin_count == 0

    async def initialize_admin(self, email: str, password: str) -> User:
        async with self._session_factory() as session:
            repo = DbUserRepository(session)
            admin_count = await repo.count_admin_users()
            if admin_count > 0:
                raise AuthServiceError(
                    code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED,
                    message="System already initialized",
                    status_code=HTTPStatus.CONFLICT,
                )
            try:
                user = await repo.create_user(
                    UserCreate(
                        email=email,
                        password_hash=await hash_password_async(password),
                        system_role="admin",
                        needs_setup=False,
                    )
                )
                await session.commit()
            except ValueError as exc:
                await session.rollback()
                raise AuthServiceError(
                    code=AuthErrorCode.SYSTEM_ALREADY_INITIALIZED,
                    message="System already initialized",
                    status_code=HTTPStatus.CONFLICT,
                ) from exc
            return _to_auth_user(user)
