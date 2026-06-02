"""Per-user MCP credential resolution.

Global MCP config still defines server shape (transport, command, URL,
non-secret defaults). This module layers user-owned secret material on top so
runtime tool calls can use the authenticated user's env/header/OAuth values.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.config.extensions_config import McpOAuthConfig, McpServerConfig
from deerflow.persistence.mcp_credentials.model import McpUserCredentialRow
from deerflow.runtime.user_context import DEFAULT_USER_ID, resolve_runtime_user_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class McpUserCredentials:
    user_id: str
    server_name: str
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    oauth: McpOAuthConfig | None = None
    version: int = 0


class McpUserCredentialStore(Protocol):
    async def get(self, user_id: str, server_name: str) -> McpUserCredentials | None:
        raise NotImplementedError

    async def upsert(
        self,
        user_id: str,
        server_name: str,
        *,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        oauth: McpOAuthConfig | None = None,
    ) -> McpUserCredentials:
        raise NotImplementedError

    async def delete(self, user_id: str, server_name: str) -> bool:
        raise NotImplementedError


def _string_dict(value: dict[str, Any] | None) -> dict[str, str]:
    if not value:
        return {}
    return {str(k): str(v) for k, v in value.items() if v is not None}


def _row_to_credentials(row: McpUserCredentialRow) -> McpUserCredentials:
    oauth = None
    if row.oauth_json:
        try:
            oauth = McpOAuthConfig.model_validate(row.oauth_json)
        except ValidationError:
            logger.warning(
                "Ignoring invalid MCP OAuth credential payload for user=%s server=%s",
                row.user_id,
                row.server_name,
                exc_info=True,
            )
    return McpUserCredentials(
        user_id=row.user_id,
        server_name=row.server_name,
        env=_string_dict(row.env_json),
        headers=_string_dict(row.headers_json),
        oauth=oauth,
        version=int(row.version or 0),
    )


class SQLMcpUserCredentialStore:
    """Async SQLAlchemy-backed store for per-user MCP credentials."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    async def get(self, user_id: str, server_name: str) -> McpUserCredentials | None:
        async with self._sf() as session:
            row = await session.get(McpUserCredentialRow, (user_id, server_name))
            return _row_to_credentials(row) if row is not None else None

    async def upsert(
        self,
        user_id: str,
        server_name: str,
        *,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        oauth: McpOAuthConfig | None = None,
    ) -> McpUserCredentials:
        async with self._sf() as session:
            row = await session.get(McpUserCredentialRow, (user_id, server_name))
            if row is None:
                row = McpUserCredentialRow(
                    user_id=user_id,
                    server_name=server_name,
                    env_json=_string_dict(env),
                    headers_json=_string_dict(headers),
                    oauth_json=oauth.model_dump() if oauth is not None else None,
                    version=1,
                )
                session.add(row)
            else:
                row.env_json = _string_dict(env)
                row.headers_json = _string_dict(headers)
                row.oauth_json = oauth.model_dump() if oauth is not None else None
                row.version = int(row.version or 0) + 1
            await session.commit()
            await session.refresh(row)
            return _row_to_credentials(row)

    async def delete(self, user_id: str, server_name: str) -> bool:
        async with self._sf() as session:
            stmt = delete(McpUserCredentialRow).where(
                McpUserCredentialRow.user_id == user_id,
                McpUserCredentialRow.server_name == server_name,
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(result.rowcount)

    async def list_for_user(self, user_id: str) -> list[McpUserCredentials]:
        async with self._sf() as session:
            stmt = select(McpUserCredentialRow).where(McpUserCredentialRow.user_id == user_id)
            result = await session.execute(stmt)
            return [_row_to_credentials(row) for row in result.scalars().all()]


class InMemoryMcpUserCredentialStore:
    """Process-local fallback store used in memory/CLI contexts."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], McpUserCredentials] = {}
        self._lock = threading.Lock()

    async def get(self, user_id: str, server_name: str) -> McpUserCredentials | None:
        with self._lock:
            return self._entries.get((user_id, server_name))

    async def upsert(
        self,
        user_id: str,
        server_name: str,
        *,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        oauth: McpOAuthConfig | None = None,
    ) -> McpUserCredentials:
        key = (user_id, server_name)
        with self._lock:
            previous = self._entries.get(key)
            credentials = McpUserCredentials(
                user_id=user_id,
                server_name=server_name,
                env=_string_dict(env),
                headers=_string_dict(headers),
                oauth=oauth,
                version=(previous.version + 1) if previous is not None else 1,
            )
            self._entries[key] = credentials
            return credentials

    async def delete(self, user_id: str, server_name: str) -> bool:
        with self._lock:
            return self._entries.pop((user_id, server_name), None) is not None

    async def list_for_user(self, user_id: str) -> list[McpUserCredentials]:
        with self._lock:
            return [entry for (entry_user, _), entry in self._entries.items() if entry_user == user_id]


_store: McpUserCredentialStore | None = None
_store_lock = threading.Lock()
_store_context: ContextVar[McpUserCredentialStore | None] = ContextVar("deerflow_mcp_credential_store", default=None)


def set_mcp_credential_store(store: McpUserCredentialStore | None) -> None:
    global _store
    with _store_lock:
        _store = store


def push_mcp_credential_store(store: McpUserCredentialStore | None) -> Token[McpUserCredentialStore | None]:
    return _store_context.set(store)


def reset_mcp_credential_store_context(token: Token[McpUserCredentialStore | None]) -> None:
    _store_context.reset(token)


def get_mcp_credential_store() -> McpUserCredentialStore:
    scoped = _store_context.get()
    if scoped is not None:
        return scoped

    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                try:
                    from deerflow.persistence.engine import get_session_factory

                    sf = get_session_factory()
                except Exception:
                    sf = None
                _store = SQLMcpUserCredentialStore(sf) if sf is not None else InMemoryMcpUserCredentialStore()
    return _store


def reset_mcp_credential_store() -> None:
    global _store
    with _store_lock:
        _store = None


async def get_user_credentials(user_id: str, server_name: str) -> McpUserCredentials | None:
    return await get_mcp_credential_store().get(user_id, server_name)


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    return loop.run_until_complete(coro)


def get_user_credentials_sync(user_id: str, server_name: str) -> McpUserCredentials | None:
    return _run_async(get_user_credentials(user_id, server_name))


def resolve_mcp_user_id(runtime: object | None) -> str:
    return resolve_runtime_user_id(runtime)


async def resolve_server_credentials(
    server_name: str,
    server_config: McpServerConfig,
    *,
    user_id: str,
    include_global_secrets: bool = True,
) -> McpUserCredentials:
    user_credentials = await get_user_credentials(user_id, server_name)
    if user_credentials is not None:
        return user_credentials

    if include_global_secrets:
        return McpUserCredentials(
            user_id=user_id,
            server_name=server_name,
            env=_string_dict(server_config.env),
            headers=_string_dict(server_config.headers),
            oauth=server_config.oauth if server_config.oauth and server_config.oauth.enabled else None,
            version=0,
        )

    return McpUserCredentials(user_id=user_id, server_name=server_name)


def resolve_server_credentials_sync(
    server_name: str,
    server_config: McpServerConfig,
    *,
    user_id: str,
    include_global_secrets: bool = True,
) -> McpUserCredentials:
    return _run_async(
        resolve_server_credentials(
            server_name,
            server_config,
            user_id=user_id,
            include_global_secrets=include_global_secrets,
        )
    )


def credential_scope_key(server_name: str, user_id: str, thread_id: str, credentials: McpUserCredentials) -> str:
    version = credentials.version if credentials.version else "global"
    return f"{user_id}:{thread_id}:v{version}"


def should_use_user_credentials(user_id: str) -> bool:
    return bool(user_id and user_id != DEFAULT_USER_ID)
