"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import concurrent.futures
import logging
import os
import threading

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
# threading.Lock instead of asyncio.Lock — initialization runs in ThreadPoolExecutor
# (each call creates its own event loop), so asyncio.Lock across loops causes deadlocks.
_initialization_lock = threading.Lock()
_config_mtime: float | None = None  # Track config file modification time
_init_future: concurrent.futures.Future | None = None  # Shared in-flight future for initialization

# Maximum time (seconds) to wait for ALL enabled MCP servers to load their tools.
MCP_INIT_TIMEOUT = 30

# Shared executor for MCP initialization to avoid blocking timeout behavior
# and prevent thread leakage if multiple initializations are triggered.
_mcp_init_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcp-init-")


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
    """Check if the cache is stale due to config file changes."""
    global _config_mtime

    if not _cache_initialized:
        return False

    current_mtime = _get_config_mtime()
    if _config_mtime is None or current_mtime is None:
        return False

    if current_mtime > _config_mtime:
        logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime

    # No asyncio.Lock here — the caller holds a threading.Lock already.
    from deerflow.mcp.tools import get_mcp_tools

    logger.info("Initializing MCP tools...")
    _mcp_tools_cache = await get_mcp_tools()
    _cache_initialized = True
    _config_mtime = _get_config_mtime()
    logger.info(f"MCP tools initialized: {len(_mcp_tools_cache)} tool(s) loaded (config mtime: {_config_mtime})")

    return _mcp_tools_cache


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    Thread-safe. If another thread is already initializing, this call blocks
    until initialization completes (up to MCP_INIT_TIMEOUT seconds).

    Returns:
        List of cached MCP tools, or empty list if initialization failed/timed out.
    """
    global _cache_initialized

    # Fast path — already initialized and config hasn't changed.
    if _cache_initialized and not _is_cache_stale():
        return _mcp_tools_cache or []

    # Slow path — acquire threading.Lock so only one thread initializes.
    with _initialization_lock:
        # Double-check after acquiring the lock.
        if _cache_initialized and not _is_cache_stale():
            return _mcp_tools_cache or []

        if _is_cache_stale():
            logger.info("MCP cache is stale, resetting for re-initialization...")
            reset_mcp_tools_cache()

        logger.info("MCP tools not initialized, performing lazy initialization...")
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Already inside a running event loop (e.g. LangGraph server).
                # Reuse a shared in-flight future so that concurrent callers
                # and post-timeout retries don't submit redundant jobs.
                global _init_future
                if _init_future is None or _init_future.done():
                    _init_future = _mcp_init_executor.submit(asyncio.run, initialize_mcp_tools())
                future = _init_future
                try:
                    future.result(timeout=MCP_INIT_TIMEOUT)
                except concurrent.futures.TimeoutError:
                    logger.error(f"MCP tools initialization timed out after {MCP_INIT_TIMEOUT}s. Check that all configured MCP servers are reachable.")
                    # The worker thread will continue in the background and eventually
                    # update the cache when it finishes.
                    return []
            else:
                loop.run_until_complete(initialize_mcp_tools())
        except RuntimeError:
            # No event loop exists, create one.
            try:
                asyncio.run(initialize_mcp_tools())
            except Exception as e:
                logger.error(f"Failed to initialize MCP tools: {e}")
                return []
        except Exception as e:
            logger.error(f"Failed to lazy-initialize MCP tools: {e}")
            return []

    return _mcp_tools_cache or []


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    Does NOT acquire _initialization_lock — callers that need atomicity
    must hold the lock themselves.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime, _init_future
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
    _init_future = None
    logger.info("MCP tools cache reset")
