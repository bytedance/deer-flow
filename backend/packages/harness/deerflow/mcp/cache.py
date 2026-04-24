"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import logging
import os
from typing import Any

from langchain_core.tools import BaseTool

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()
_config_mtime: float | None = None  # Track config file modification time
_enabled_server_count = 0
_active_tools_by_server: dict[str, list[str]] = {}


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


def _is_cache_stale(*, log_change: bool = True) -> bool:
    """Check if the cache is stale due to config file changes.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    global _config_mtime

    if not _cache_initialized:
        return False  # Not initialized yet, not stale

    current_mtime = _get_config_mtime()

    # If we couldn't get mtime before or now, assume not stale
    if _config_mtime is None or current_mtime is None:
        return False

    # If the config file has been modified since we cached, it's stale
    if current_mtime > _config_mtime:
        if log_change:
            logger.info(f"MCP config file has been modified (mtime: {_config_mtime} -> {current_mtime}), cache is stale")
        return True

    return False


def get_mcp_cache_status() -> dict[str, Any]:
    """Return the current MCP cache status for runtime feedback surfaces.

    The values describe the state observed by the current Python process. In
    split gateway/runtime deployments, other processes may refresh on their own
    next MCP tool load after the config file mtime changes.
    """
    cache_stale = _is_cache_stale(log_change=False)
    active_tool_count = len(_mcp_tools_cache or []) if _cache_initialized else 0
    status = (
        "not_initialized"
        if not _cache_initialized
        else "pending_reload"
        if cache_stale
        else "in_sync"
    )

    return {
        "status": status,
        "reload_mode": "next_tool_load",
        "restart_required": False,
        "will_apply_on_next_load": (not _cache_initialized) or cache_stale,
        "cache_initialized": _cache_initialized,
        "cache_stale": cache_stale,
        "config_last_modified_at": _get_config_mtime(),
        "runtime_config_last_loaded_at": _config_mtime,
        "active_server_count": _enabled_server_count if _cache_initialized else 0,
        "active_tool_count": active_tool_count,
        "active_tools_by_server": _active_tools_by_server if _cache_initialized else {},
    }


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime, _enabled_server_count, _active_tools_by_server

    async with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from deerflow.config.extensions_config import ExtensionsConfig
        from deerflow.mcp.tools import get_mcp_tools_for_config

        logger.info("Initializing MCP tools...")
        extensions_config = ExtensionsConfig.from_file()
        _mcp_tools_cache = await get_mcp_tools_for_config(extensions_config)
        _cache_initialized = True
        _enabled_server_count = len(extensions_config.get_enabled_mcp_servers())
        _active_tools_by_server = _group_active_tools_by_server(
            _mcp_tools_cache,
            list(extensions_config.get_enabled_mcp_servers().keys()),
        )
        _config_mtime = _get_config_mtime()  # Record config file mtime
        logger.info(
            "MCP tools initialized: %s tool(s) loaded across %s enabled server(s) (config mtime: %s)",
            len(_mcp_tools_cache),
            _enabled_server_count,
            _config_mtime,
        )

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

    # Check if cache is stale due to config file changes
    if _is_cache_stale():
        logger.info("MCP cache is stale, resetting for re-initialization...")
        reset_mcp_tools_cache()

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
            try:
                asyncio.run(initialize_mcp_tools())
            except Exception:
                logger.exception("Failed to lazy-initialize MCP tools")
                return []
        except Exception:
            logger.exception("Failed to lazy-initialize MCP tools")
            return []

    return _mcp_tools_cache or []


def _group_active_tools_by_server(
    tools: list[BaseTool] | None,
    server_names: list[str],
) -> dict[str, list[str]]:
    """Group active MCP tool names by server using the persisted name prefix."""
    from deerflow.mcp.tools import split_prefixed_mcp_tool_name

    grouped = {server_name: [] for server_name in server_names}

    for tool in tools or []:
        split_name = split_prefixed_mcp_tool_name(tool.name, server_names)
        if split_name is None:
            continue

        server_name, raw_tool_name = split_name
        grouped.setdefault(server_name, []).append(raw_tool_name)

    return {
        server_name: sorted(tool_names)
        for server_name, tool_names in grouped.items()
        if tool_names
    }


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    """
    global _mcp_tools_cache, _cache_initialized, _config_mtime, _enabled_server_count, _active_tools_by_server
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_mtime = None
    _enabled_server_count = 0
    _active_tools_by_server = {}
    logger.info("MCP tools cache reset")
