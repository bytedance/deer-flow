"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import logging
from pathlib import Path

from langchain_core.tools import BaseTool

from deerflow.config.file_signature import ConfigSignature as _ConfigSignature
from deerflow.config.file_signature import get_config_signature as _get_config_signature

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_initialization_lock = asyncio.Lock()

# Cache-invalidation key for the resolved extensions config file. We track the
# resolved path *and* a ``(mtime, size, sha256)`` content signature — via the
# shared ``deerflow.config.file_signature`` helper also used by
# ``deerflow.config.app_config`` for the sibling runtime-editable config file —
# rather than only the mtime. A strict mtime ``>`` comparison misses same-second
# edits and mtime that stays put or moves backward (object-store / network
# mounts, ``git checkout``, ``cp -p`` / backup restore, ``tar`` / ``rsync`` that
# preserve timestamps), and tracking no path at all makes a switch to a
# different config file with an equal-or-older mtime structurally invisible.
_config_path: Path | None = None  # Resolved extensions config path at init time
_config_signature: _ConfigSignature | None = None  # (mtime, size, sha256) at init time


def _resolve_config_path() -> Path | None:
    """Resolve the extensions config file path, or ``None`` when unconfigured.

    ``ExtensionsConfig.resolve_config_path()`` raises ``FileNotFoundError``
    when an explicit `config_path` or `DEER_FLOW_EXTENSIONS_CONFIG_PATH`
    points at a file that does not exist. That is deliberate for callers that
    load the config for actual use (e.g. ``ExtensionsConfig.from_file()`` via
    ``get_mcp_tools()``): an operator-asserted explicit path going missing is
    a real misconfiguration and must be surfaced loudly.

    This helper is not one of those callers — it only backs the cache's own
    staleness check (``_is_cache_stale``, via ``_current_config_state``),
    which runs on every ``get_cached_mcp_tools()`` call and just wants to know
    whether the previously loaded config is still current. If the file behind
    a previously-valid explicit/env-var path becomes unreadable later
    (deleted mid-run, a Docker mount hiccup, ...), raising here would crash
    every subsequent call to that hot per-request path instead of leaving the
    cache serving its last-known-good MCP tools. So this wrapper catches that
    specific failure and treats it the same as "unconfigured", matching
    ``_is_cache_stale()``'s existing fail-soft handling of a ``None`` config
    state (see its docstring). Scoping the catch here — rather than making
    ``resolve_config_path()`` itself return ``None`` for every caller — keeps
    the loud failure intact for callers that actually need the file.
    """
    from deerflow.config.extensions_config import ExtensionsConfig

    try:
        return ExtensionsConfig.resolve_config_path()
    except FileNotFoundError:
        logger.debug(
            "Extensions config path could not be resolved while checking MCP cache staleness; treating as unconfigured for this check.",
            exc_info=True,
        )
        return None


def _current_config_state() -> tuple[Path | None, _ConfigSignature | None]:
    """Return the currently resolved extensions config path and its signature."""
    config_path = _resolve_config_path()
    if config_path is None:
        return None, None
    return config_path, _get_config_signature(config_path)


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    The cache is stale when the resolved extensions config path changed, or when
    the ``(mtime, size, sha256)`` content signature differs from the one recorded
    at initialization. Using content equality (``!=``) instead of a strict mtime
    ``>`` comparison detects same-second edits and backward mtime moves, and
    tracking the resolved path detects a switch to a different config file.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    if not _cache_initialized:
        return False  # Not initialized yet, not stale

    current_path, current_signature = _current_config_state()

    # Preserve the original "config missing / not yet recorded" behavior: if
    # there was no readable config when the cache was populated, or there is
    # none now, do not invalidate. This also covers the config being deleted
    # entirely after a successful init (current_signature flips to None): the
    # cache intentionally keeps serving its last-known-good MCP tools rather
    # than invalidating into an unconfigured state, matching the pre-fix
    # mtime-only contract (which also returned False once the file could no
    # longer be stat-ed). Treat this as a deliberate fail-soft choice, not an
    # oversight — a future change that wants "config deleted" to tear down
    # MCP tools needs its own explicit signal here, not an inferred one.
    if _config_signature is None or current_signature is None:
        return False

    if current_path != _config_path:
        logger.info("MCP config path changed (%s -> %s), cache is stale", _config_path, current_path)
        return True

    if current_signature != _config_signature:
        logger.info("MCP config content changed (signature %s -> %s), cache is stale", _config_signature, current_signature)
        return True

    return False


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature

    async with _initialization_lock:
        if _cache_initialized:
            logger.info("MCP tools already initialized")
            return _mcp_tools_cache or []

        from deerflow.mcp.tools import get_mcp_tools

        logger.info("Initializing MCP tools...")
        _mcp_tools_cache = await get_mcp_tools()
        _cache_initialized = True
        _config_path, _config_signature = _current_config_state()  # Record config path + content signature
        logger.info("MCP tools initialized: %d tool(s) loaded (config path: %s)", len(_mcp_tools_cache), _config_path)

        return _mcp_tools_cache


def get_cached_mcp_tools() -> list[BaseTool]:
    """Get cached MCP tools with lazy initialization.

    If tools are not initialized, automatically initializes them.
    This ensures MCP tools work in both FastAPI and LangGraph Studio contexts.

    Also checks if the config file has been modified since last initialization,
    and re-initializes if needed. This ensures that changes made through the
    Gateway API are reflected in the Gateway-embedded LangGraph runtime.

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


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    Also closes all persistent MCP sessions so they are recreated on
    the next tool load.
    """
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    _mcp_tools_cache = None
    _cache_initialized = False
    _config_path = None
    _config_signature = None

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
