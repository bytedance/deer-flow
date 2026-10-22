"""Share MCP OAuth tokens through the application database for one Gateway lifetime."""

import asyncio
import logging
from collections.abc import Collection
from contextlib import asynccontextmanager

from deerflow.config.app_config import AppConfig
from deerflow.mcp.oauth_store import McpOAuthTokenStore, McpOAuthTokenStoreUnavailable, get_mcp_oauth_token_store, set_mcp_oauth_token_store

logger = logging.getLogger(__name__)


def build_mcp_oauth_token_store(app_config: AppConfig) -> McpOAuthTokenStore | None:
    """The ``mcp_oauth_tokens`` store for a sqlite/postgres database, else ``None`` (tokens stay in process).

    The store opens the shared synchronous engine
    (``deerflow.persistence.agents.sql.get_sync_sessionmaker``) because token
    refreshes run on whichever loop calls the tool. Its table comes from the
    persistence bootstrap, which runs before any tool call; the credentials
    key loads on the first refresh_token use.
    """
    database = getattr(app_config, "database", None)
    if getattr(database, "backend", None) not in ("sqlite", "postgres"):
        return None
    from deerflow.persistence.agents.sql import get_sync_sessionmaker
    from deerflow.persistence.mcp_oauth_tokens import SqlMcpOAuthTokenRepository

    return McpOAuthTokenStore(SqlMcpOAuthTokenRepository(get_sync_sessionmaker(database.app_sync_sqlalchemy_url)))


@asynccontextmanager
async def mcp_oauth_token_persistence(app_config: AppConfig):
    """Install the store for every OAuth manager in this process, around the whole runtime.

    Entered before and left after the LangGraph runtime, whose exit drains
    active runs: a refresh during that drain must still reach the database, or
    the rotated refresh token is lost to the next process.
    """
    store = await asyncio.to_thread(build_mcp_oauth_token_store, app_config)
    previous = set_mcp_oauth_token_store(store)
    try:
        yield
    finally:
        set_mcp_oauth_token_store(previous)


def forget_unconfigured_mcp_oauth_tokens(owner_user_id: str | None, configured_server_keys: Collection[str]) -> None:
    """After a saved MCP configuration, drop stored tokens of connections it no longer has.

    ``owner_user_id`` is ``None`` for the deployment's servers. Best effort and
    blocking: a database failure is logged by the store and leaves the rows for
    the next save; it never fails the configuration write that already landed.
    """
    store = get_mcp_oauth_token_store()
    if store is None:
        return
    try:
        removed = store.forget_unconfigured(owner_user_id, configured_server_keys)
    except McpOAuthTokenStoreUnavailable:
        return
    if removed:
        logger.info("Deleted stored OAuth tokens of %d removed MCP connection(s)", removed)
