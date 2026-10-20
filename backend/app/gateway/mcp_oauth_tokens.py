"""Share MCP OAuth tokens through the application database for one Gateway lifetime."""

import asyncio
from contextlib import asynccontextmanager

from deerflow.mcp.oauth_store import McpOAuthTokenStore, set_mcp_oauth_token_store


def build_mcp_oauth_token_store(app_config) -> McpOAuthTokenStore | None:
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
async def mcp_oauth_token_persistence(app_config):
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
