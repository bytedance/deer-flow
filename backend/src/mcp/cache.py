"""Cache for MCP tools to avoid repeated loading.

Uses a stale-while-revalidate strategy: when the config file changes,
the cached tools are returned immediately while a background task
refreshes the cache. This avoids blocking the caller during MCP
server reconnection.
"""

import asyncio
import logging
import os
import threading

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()
_config_mtime: float | None = None  # Track config file modification time
_background_refresh_in_progress = False  # Prevents duplicate background refreshes


def _get_config_mtime() -> float | None:
    """Get the modification time of the extensions config file.

    Returns:
        The modification time as a float, or None if the file doesn't exist.
    """
    from src.config.extensions_config import ExtensionsConfig

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path and config_path.exists():
        return os.path.getmtime(config_path)
    return None


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    if not _cache_initialized:
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


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime

    async with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from src.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools...")
        _mcp_tools_cache = await get_mcp_tools()
        _cache_initialized = True
        _config_mtime = _get_config_mtime()  # Record config file mtime
        logger.info(f"MCP tools initialized: {len(_mcp_tools_cache)} tool(s) loaded (config mtime: {_config_mtime})")

        return _mcp_tools_cache


def _background_refresh() -> None:
    """Refresh MCP tools in a background thread without blocking callers."""
    global _mcp_tools_cache, _config_mtime, _background_refresh_in_progress

    async def _do_refresh():
        global _mcp_tools_cache, _config_mtime, _background_refresh_in_progress
        try:
            from src.mcp.tools import get_mcp_tools

            logger.info("Background refresh: reloading MCP tools...")
            new_tools = await get_mcp_tools()
            _mcp_tools_cache = new_tools
            _config_mtime = _get_config_mtime()
            logger.info(f"Background refresh complete: {len(new_tools)} tool(s) loaded (config mtime: {_config_mtime})")
        except Exception as e:
            logger.error(f"Background refresh failed: {e}")
        finally:
            _background_refresh_in_progress = False

    try:
        asyncio.run(_do_refresh())
    except Exception as e:
        logger.error(f"Background refresh thread error: {e}")
        _background_refresh_in_progress = False


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them (blocking).
    If tools are cached but stale, returns the stale cache immediately
    and triggers a background refresh (stale-while-revalidate).

    Returns:
        List of cached MCP tools.
    """
    global _background_refresh_in_progress

    # Stale-while-revalidate: serve stale cache, refresh in background
    if _is_cache_stale() and _cache_initialized and _mcp_tools_cache is not None:
        if not _background_refresh_in_progress:
            _background_refresh_in_progress = True
            logger.info("MCP cache is stale, serving cached tools while refreshing in background...")
            thread = threading.Thread(target=_background_refresh, daemon=True)
            thread.start()
        return _mcp_tools_cache

    if not _cache_initialized:
        logger.info("MCP tools not initialized, performing lazy initialization...")
        try:
            # Try to initialize in the current event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If loop is already running (e.g., in LangGraph Studio),
                # we need to create a new loop in a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools())
                    future.result()
            else:
                # If no loop is running, we can use the current loop
                loop.run_until_complete(initialize_mcp_tools())
        except RuntimeError:
            # No event loop exists, create one
            asyncio.run(initialize_mcp_tools())
        except Exception as e:
            logger.error(f"Failed to lazy-initialize MCP tools: {e}")
            return []

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime, _background_refresh_in_progress
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
    _background_refresh_in_progress = False
    logger.info("MCP tools cache reset")
