"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import logging
import os

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: dict[str, list[BaseTool]] = {}
_initialization_lock = asyncio.Lock()
_config_mtime: float | None = None  # Track config file modification time


def _scope_key(user_id: str | None = None) -> str:
    return str(user_id) if user_id else "default"


def _get_config_mtime() -> float | None:
    """Get the modification time of the extensions config file.

    Returns:
        The modification time as a float, or None if the file doesn't exist.
    """
    from deerflow.config.extensions_config import ExtensionsConfig

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path and config_path.exists():
        return os.path.getmtime(config_path)
    return None


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    global _config_mtime

    if not _mcp_tools_cache:
        return False  # Not initialized yet, not stale

    current_mtime = _get_config_mtime()

    # If we couldn't get mtime before or now, assume not stale
    if _config_mtime is None or current_mtime is None:
        return False

    # If the config file has been modified since we cached, it's stale
    if current_mtime > _config_mtime:
        logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False


async def initialize_mcp_tools(user_id: str | None = None) -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _config_mtime

    async with _initialization_lock:
        key = _scope_key(user_id)
        if key in _mcp_tools_cache:
            logger.info("MCP tools already initialized for scope=%s", key)
            return _mcp_tools_cache[key]

        from deerflow.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools for scope=%s...", key)
        _mcp_tools_cache[key] = await get_mcp_tools(user_id=user_id)
        _config_mtime = _get_config_mtime()  # Record config file mtime
        logger.info(
            "MCP tools initialized for scope=%s: %d tool(s) loaded (config mtime: %s)",
            key,
            len(_mcp_tools_cache[key]),
            _config_mtime,
        )

        return _mcp_tools_cache[key]


def get_cached_mcp_tools(user_id: str | None = None) -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them.
    This ensures MCP tools work in both FastAPI and LangGraph Studio contexts.

    Also checks if the config file has been modified since last initialization,
    and re-initializes if needed. This ensures that changes made through the
    Gateway API are reflected in the Gateway-embedded LangGraph runtime.

    Returns:
        List of cached MCP tools.
    """
    # Check if cache is stale due to config file changes
    if _is_cache_stale():
        logger.info("MCP cache is stale, resetting for re-initialization...")
        reset_mcp_tools_cache()

    key = _scope_key(user_id)
    if key not in _mcp_tools_cache:
        logger.info("MCP tools not initialized for scope=%s, performing lazy initialization...", key)
        try:
            # Try to initialize in the current event loop
            try:
                asyncio.get_running_loop()
                loop_is_running = True
            except RuntimeError:
                loop_is_running = False

            if loop_is_running:
                # If loop is already running (e.g., in LangGraph Studio),
                # we need to create a new loop in a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools(user_id=user_id))
                    future.result()
            else:
                asyncio.run(initialize_mcp_tools(user_id=user_id))
        except RuntimeError:
            # No event loop exists, create one
            try:
                asyncio.run(initialize_mcp_tools(user_id=user_id))
            except Exception:
                logger.exception("Failed to lazy-initialize MCP tools")
                return []
        except Exception:
            logger.exception("Failed to lazy-initialize MCP tools")
            return []

    return _mcp_tools_cache.get(key, [])


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    Also closes all persistent MCP sessions so they are recreated on
    the next tool load.
    """
    global _config_mtime
    _mcp_tools_cache.clear()
    _config_mtime = None

    # Close persistent sessions – they will be recreated by the next
    # get_mcp_tools() call with the (possibly updated) connection config.
    #
    # close_all_sync() already picks the correct strategy per owning loop:
    #   * sessions owned by the *current* running loop are only *signalled*
    #     (their owner task runs __aexit__ once the loop regains control –
    #     this is correct and leak-free, since the loop keeps the task alive),
    #   * sessions on other threads' loops are torn down deterministically,
    #   * idle/closed loops are handled or skipped.
    # We deliberately do NOT try to synchronously wait for the current running
    # loop to finish teardown here: that is a self-deadlock (the loop can only
    # run the teardown after this synchronous call returns control to it).
    try:
        from deerflow.mcp.session_pool import get_session_pool

        get_session_pool().close_all_sync()
    except Exception:
        logger.debug("Could not close MCP session pool on cache reset", exc_info=True)

    from deerflow.mcp.session_pool import reset_session_pool

    reset_session_pool()
    logger.info("MCP tools cache reset")
