"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import logging
import threading
import time

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = threading.Lock()
_config_fingerprint: str | None = None
_last_stale_check: float = 0.0
_STALE_CHECK_INTERVAL = 5.0


def _get_config_fingerprint() -> str | None:
    """Get a fingerprint of the extensions config file for change detection.

    Uses a combination of mtime and file size to handle file systems where
    mtime resolution is too coarse (e.g. FAT32 has 2-second granularity).

    Returns:
        A string fingerprint, or None if the file doesn't exist.
    """
    from src.config.extensions_config import ExtensionsConfig

    config_path = ExtensionsConfig.resolve_config_path()
    if config_path and config_path.exists():
        stat = config_path.stat()
        return f"{stat.st_mtime}:{stat.st_size}"
    return None


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    Throttled to at most once per _STALE_CHECK_INTERVAL seconds to avoid
    excessive file stat calls on every request.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    global _config_fingerprint, _last_stale_check

    if not _cache_initialized:
        return False

    now = time.monotonic()
    if now - _last_stale_check < _STALE_CHECK_INTERVAL:
        return False
    _last_stale_check = now

    current_fp = _get_config_fingerprint()

    if current_fp != _config_fingerprint:
        logger.info("MCP config file has been modified (fingerprint: %s -> %s), cache is stale", _config_fingerprint, current_fp)
        return True

    return False


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.
    Thread safety is handled by the caller via _initialization_lock.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_fingerprint

    if _cache_initialized:
        logger.info("MCP tools already initialized")
        return _mcp_tools_cache or []

    from src.mcp.tools import get_mcp_tools

    logger.info("Initializing MCP tools...")
    _mcp_tools_cache = await get_mcp_tools()
    _cache_initialized = True
    _config_fingerprint = _get_config_fingerprint()
    logger.info("MCP tools initialized: %d tool(s) loaded (config fingerprint: %s)", len(_mcp_tools_cache), _config_fingerprint)

    return _mcp_tools_cache


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them.
    This ensures MCP tools work in both FastAPI and LangGraph Studio contexts.

    Also checks if the config file has been modified since last initialization,
    and re-initializes if needed. This ensures that changes made through the
    Gateway API (which runs in a separate process) are reflected in the
    LangGraph Server.

    Returns:
        List of cached MCP tools.
    """
    global _cache_initialized

    with _initialization_lock:
        if _is_cache_stale():
            logger.info("MCP cache is stale, resetting for re-initialization...")
            _reset_cache_internal()

        if not _cache_initialized:
            logger.info("MCP tools not initialized, performing lazy initialization...")
            try:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop is not None and loop.is_running():
                    import concurrent.futures

                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(asyncio.run, initialize_mcp_tools())
                        future.result()
                else:
                    asyncio.run(initialize_mcp_tools())
            except Exception as e:
                logger.error("Failed to lazy-initialize MCP tools: %s", e)
                return []

    return _mcp_tools_cache or []


def _reset_cache_internal() -> None:
    """Reset cache state (caller must hold _initialization_lock)."""
    global _mcp_tools_cache, _cache_initialized, _config_fingerprint
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_fingerprint = None


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    """
    with _initialization_lock:
        _reset_cache_internal()
    logger.info("MCP tools cache reset")
