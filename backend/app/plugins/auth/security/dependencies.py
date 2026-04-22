"""Security dependency helpers for the auth plugin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.plugins.auth.domain.errors import (
    AuthErrorCode,
    AuthErrorResponse,
    TokenError,
    token_error_to_code,
)
from app.plugins.auth.domain.jwt import decode_token
from app.plugins.auth.domain.service import AuthService
from app.plugins.auth.storage import DbUserRepository, UserRepositoryProtocol


def _get_session_factory(request: Request) -> async_sessionmaker[AsyncSession] | None:
    persistence = getattr(request.app.state, "persistence", None)
    if persistence is None:
        return None
    return getattr(persistence, "session_factory", None)


@asynccontextmanager
async def _auth_session(request: Request) -> AsyncIterator[AsyncSession]:
    injected = getattr(request.state, "_auth_session", None)
    if injected is not None:
        yield injected
        return

    session_factory = _get_session_factory(request)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Auth session not available")

    async with session_factory() as session:
        yield session


async def get_user_repository(request: Request) -> UserRepositoryProtocol:
    async with _auth_session(request) as session:
        return DbUserRepository(session)


def get_auth_service(request: Request) -> AuthService:
    session_factory = _get_session_factory(request)
    if session_factory is None:
        raise HTTPException(status_code=503, detail="Auth session factory not available")
    return AuthService(session_factory)


async def get_current_user_from_request(request: Request):
    access_token = request.cookies.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.NOT_AUTHENTICATED, message="Not authenticated").model_dump(),
        )

    payload = decode_token(access_token)
    if isinstance(payload, TokenError):
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(
                code=token_error_to_code(payload),
                message=f"Token error: {payload.value}",
            ).model_dump(),
        )

    async with _auth_session(request) as session:
        user_repo = DbUserRepository(session)
        user = await user_repo.get_user_by_id(payload.sub)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(code=AuthErrorCode.USER_NOT_FOUND, message="User not found").model_dump(),
        )

    if user.token_version != payload.ver:
        raise HTTPException(
            status_code=401,
            detail=AuthErrorResponse(
                code=AuthErrorCode.TOKEN_INVALID,
                message="Token revoked (password changed)",
            ).model_dump(),
        )

    return user


async def get_optional_user_from_request(request: Request):
    try:
        return await get_current_user_from_request(request)
    except HTTPException:
        return None


async def get_current_user_id(request: Request) -> str | None:
    user = await get_optional_user_from_request(request)
    return user.id if user else None


CurrentUserRepository = Annotated[UserRepositoryProtocol, Depends(get_user_repository)]
CurrentAuthService = Annotated[AuthService, Depends(get_auth_service)]

__all__ = [
    "CurrentAuthService",
    "CurrentUserRepository",
    "get_auth_service",
    "get_current_user_from_request",
    "get_current_user_id",
    "get_optional_user_from_request",
    "get_user_repository",
]
