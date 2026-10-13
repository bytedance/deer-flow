"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import json
import logging
import threading
from pathlib import Path

from langchain_core.tools import BaseTool

from deerflow.config.file_signature import ConfigSignature as _ConfigSignature
from deerflow.config.file_signature import get_config_signature as _get_config_signature
from deerflow.config.shared_reset_marker import SharedResetMarker
from deerflow.mcp.config_normalization import normalize_mcp_interceptor_paths, normalize_mcp_server_config

logger = logging.getLogger(__name__)

_mcp_tools_cache: list[BaseTool] | None = None
_cache_initialized = False
_init_lock = threading.RLock()  # Guards cache state transitions.
_init_condition = threading.Condition(_init_lock)
_initializing_generation: int | None = None
_cache_generation = 0

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

# JSON snapshot of the effective MCP slice (enabled servers in declaration
# order + mcpInterceptors) that the currently published tools were built from.
# May contain resolved credentials: never log or persist it.
_mcp_config_snapshot: str | None = None

# True when the published cache came from an initialization with no resolvable
# extensions config. Distinguishes "never configured" (a later config must be
# picked up) from "config deleted after a successful load" (fail-soft: keep
# serving the last-known-good tools).
_initialized_without_config = False

# Signature of the shared-config reset marker observed by the published
# cache.  ``POST /api/mcp/cache/reset`` advances this marker even when
# ``extensions_config.json`` itself is unchanged (the important case is a
# remote MCP server changing its ``tools/list`` response).  Every worker reads
# the marker from the same writable config directory before returning cached
# tools, so a reset initiated in one process retires sessions in the others on
# their next lookup.
_cache_reset_marker_signature: _ConfigSignature | None = None

#: ``.<extensions config name>.mcp-cache-reset.json`` beside the resolved config.
#: The generic marker/tracker contract lives in ``deerflow.config.shared_reset_marker``
#: and is shared with the skills prompt-cache reset.
MCP_CACHE_RESET_MARKER = SharedResetMarker("mcp-cache-reset")


def _cache_reset_marker_path(config_path: Path) -> Path:
    """Return the shared reset marker colocated with the extensions config."""
    return MCP_CACHE_RESET_MARKER.path_for(config_path)


def _current_cache_reset_marker_signature(config_path: Path | None) -> _ConfigSignature | None:
    """Return the current shared-reset marker signature, if one exists."""
    return MCP_CACHE_RESET_MARKER.current_signature(config_path)


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


def _effective_mcp_config_snapshot(config) -> str:
    """Serialize the MCP-only slice of an extensions config.

    ``extensions_config.json`` also carries skills and middleware settings, so
    the whole-file signature cannot distinguish an MCP change from a skill
    toggle. The enabled-server list preserves declaration order (it can affect
    tool ordering) while ``sort_keys`` only normalizes each server's field
    order. Parsed models are compared through
    ``config_normalization.normalize_mcp_server_config`` (equivalent
    ``type``/``transport`` spellings) and the custom interceptor list through
    ``config_normalization.normalize_mcp_interceptor_paths`` (a bare string and
    its single-element list, or a missing key and an empty list), so equivalent
    spellings do not cause a needless rebuild.

    The result may embed resolved credentials. It stays in process memory and
    is never logged or written back to disk.
    """
    relevant = {
        "enabled_servers": [(name, normalize_mcp_server_config(server)) for name, server in config.get_enabled_mcp_servers().items()],
        "mcpInterceptors": normalize_mcp_interceptor_paths((config.model_extra or {}).get("mcpInterceptors")),
    }
    return json.dumps(relevant, sort_keys=True, ensure_ascii=False)


def _signature_is_verifiable(signature: _ConfigSignature | None) -> bool:
    """True when a config signature carries a content digest.

    ``get_config_signature`` returns ``(mtime, size, None)`` when the file could
    be stat-ed but not read. Such a signature cannot prove the content is
    unchanged, so the MCP cache must neither publish nor adopt it.
    """
    return signature is not None and signature[2] is not None


def _read_stable_mcp_snapshot(config_path: Path, expected_signature: _ConfigSignature) -> str | None:
    """Parse the config and return its MCP snapshot only if the file was stable.

    ``expected_signature`` is the signature observed by the caller. A signature
    without a content digest is treated as unverifiable, and the file is
    re-hashed after parsing: a mismatch means the config changed while it was
    being read, so no snapshot can be attributed to a single revision and the
    caller must treat the cache as stale. Parse failures also return ``None``
    (conservative: never reuse tools on an unreadable config).
    """
    if not _signature_is_verifiable(expected_signature):
        logger.info("Extensions config signature has no content digest; treating the MCP cache as stale")
        return None

    from deerflow.config.extensions_config import ExtensionsConfig

    try:
        config = ExtensionsConfig.from_file(str(config_path))
    except Exception as exc:
        # Do NOT pass exc_info/message: ExtensionsConfig.from_file resolves
        # ``$VAR`` values before validation, so a ValidationError can embed
        # resolved credentials in its input. Only the exception type is safe.
        logger.warning(
            "Could not parse extensions config while checking MCP cache staleness (%s); treating the cache as stale",
            type(exc).__name__,
        )
        return None

    current_signature = _get_config_signature(config_path)
    if not _signature_is_verifiable(current_signature) or current_signature != expected_signature:
        logger.info("Extensions config changed while it was being read; treating the MCP cache as stale")
        return None

    return _effective_mcp_config_snapshot(config)


def _is_cache_stale() -> bool:
    """Check if the cache is stale due to config file changes.

    The cache is stale when the effective MCP slice of the resolved config
    differs from the one recorded at initialization. The resolved path and the
    ``(mtime, size, sha256)`` content signature are the change signals that
    trigger that comparison, not invalidation reasons on their own. Using
    content equality (``!=``) instead of a strict mtime ``>`` comparison detects
    same-second edits and backward mtime moves. A path switch to a file with the
    same MCP configuration, or an edit that only touches skills or middleware
    settings, therefore keeps the cached tools and sessions and adopts the new
    path and signature.

    When the file signature changes but the effective MCP configuration does
    not, this function adopts the new signature into ``_config_signature`` and
    returns False. It is therefore not a read-only predicate; production callers
    invoke it under ``_init_condition``, the same lock the mutating paths use.

    Returns:
        True if the cache should be invalidated, False otherwise.
    """
    global _config_path, _config_signature

    if not _cache_initialized:
        return False  # Not initialized yet, not stale

    current_path, current_signature = _current_config_state()

    # A reset marker is independent of configuration bytes.  It exists so an
    # administrator can refresh a remote server's changed ``tools/list`` in
    # every Gateway worker without fabricating a config edit.  Missing current
    # config keeps the existing last-known-good behavior below: there is no
    # reliable shared directory to consult in that state.
    if current_path is not None:
        current_reset_signature = _current_cache_reset_marker_signature(current_path)
        if current_reset_signature != _cache_reset_marker_signature:
            logger.info("Shared MCP cache reset generation changed; cache is stale")
            return True

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
    if _config_signature is None:
        # A config that appears after an unconfigured initialization must be
        # picked up; a config deleted after a successful load keeps the
        # last-known-good fail-soft contract below.
        if _initialized_without_config and current_signature is not None:
            logger.info("Extensions config appeared after an unconfigured MCP cache; cache is stale")
            return True
        return False

    if current_signature is None:
        return False

    if current_path == _config_path and current_signature == _config_signature and _signature_is_verifiable(current_signature):
        return False

    # The resolved path and/or the file content changed. Both are only signals to
    # re-read the effective MCP slice: the file also carries skills and middleware
    # settings, and a path switch can land on a file with the same MCP
    # configuration, so neither is an invalidation reason on its own.
    if current_path != _config_path:
        logger.info("MCP config path changed (%s -> %s); re-checking the effective MCP configuration", _config_path, current_path)

    if current_path is not None and _mcp_config_snapshot is not None:
        current_snapshot = _read_stable_mcp_snapshot(current_path, current_signature)
        if current_snapshot is not None and current_snapshot == _mcp_config_snapshot:
            logger.info("Extensions config changed but the effective MCP configuration did not; keeping cached MCP tools and sessions")
            _config_path = current_path
            _config_signature = current_signature
            return False

    logger.info("MCP config content changed (signature %s -> %s), cache is stale", _config_signature, current_signature)
    return True


def _wait_for_initialization(generation: int | None) -> None:
    """Wait for an in-flight initialization without binding to any event loop."""
    with _init_condition:
        _init_condition.wait_for(lambda: _cache_initialized or _initializing_generation != generation)


async def initialize_mcp_tools() -> list[BaseTool]:
    """Initialize and cache MCP tools.

    This should be called once at application startup.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    global _initializing_generation, _cache_generation, _mcp_config_snapshot, _initialized_without_config
    global _cache_reset_marker_signature

    while True:
        with _init_condition:
            if _cache_initialized:
                logger.info("MCP tools already initialized")
                return _mcp_tools_cache or []

            if _initializing_generation is None:
                claim_generation = _cache_generation
                _initializing_generation = claim_generation
                break

            waiting_generation = _initializing_generation

        await asyncio.to_thread(_wait_for_initialization, waiting_generation)

    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp.session_pool import StaleMCPBindingError, get_session_pool
    from deerflow.mcp.tools import get_mcp_tools

    loaded_tools = None
    loaded_snapshot = None
    post_path = None
    post_sig = None
    post_snapshot = None
    loaded_reset_signature = None
    post_reset_signature = None
    init_succeeded = False
    try:
        logger.info("Initializing MCP tools...")
        # Read the exact revision we hand to discovery. Comparing pre/post file
        # snapshots alone cannot prove which revision produced the tools, because
        # get_mcp_tools() would otherwise read the file itself.
        try:
            loaded_config = ExtensionsConfig.from_file()
        except Exception as exc:
            # Never let a resolved-credential ValidationError reach a caller's
            # logger: from_file() resolves $VAR values before validation, so the
            # exception message can embed secrets. Re-raise a sanitized error;
            # other MCP failures keep their original traceback.
            logger.warning(
                "Could not load extensions config before MCP tool discovery (%s); aborting initialization",
                type(exc).__name__,
            )
            raise RuntimeError("Extensions config could not be loaded for MCP tool discovery") from None
        loaded_snapshot = _effective_mcp_config_snapshot(loaded_config)
        loaded_reset_signature = _current_cache_reset_marker_signature(_resolve_config_path())
        # Claim the exact pool this generation owns under the same lock the
        # reset path takes, so verify-generation + capture-pool is one atomic
        # ownership handoff. A superseded initializer must never resolve the
        # singleton after the reset: that would install its stale fingerprint
        # into the replacement pool the successor initializer runs on.
        with _init_condition:
            if _cache_generation != claim_generation:
                logger.info("MCP cache was reset before tool discovery; discarding superseded initialization")
                return []

            claimed_pool = get_session_pool()

        try:
            loaded_tools = await get_mcp_tools(
                extensions_config=loaded_config,
                session_pool=claimed_pool,
            )
        except StaleMCPBindingError:
            # The pool this claim owns was retired while discovery was running.
            # That is the same cache race as a generation change, so keep the
            # existing "discard stale initialization" semantics; a stale binding
            # on a pool this claim still owns stays a real error.
            with _init_condition:
                superseded = _cache_generation != claim_generation

            if superseded:
                logger.info("MCP cache was reset during binding installation; discarding superseded initialization")
                return []
            raise
        post_path, post_sig = _current_config_state()
        post_reset_signature = _current_cache_reset_marker_signature(post_path)
        if post_path is not None and post_sig is not None:
            post_snapshot = _read_stable_mcp_snapshot(post_path, post_sig)
        elif post_path is not None:
            # The path resolved but its signature could not be read. Publishing
            # here would record an unpinned cache that later checks could never
            # invalidate, so discard instead.
            post_snapshot = None
        else:
            # No resolvable config now. Re-resolve after the fallback read so a
            # config that appeared mid-flight is not published as an unpinned
            # cache; the snapshot comparison still rejects a different revision.
            try:
                fallback_snapshot = _effective_mcp_config_snapshot(ExtensionsConfig.from_file())
            except Exception as exc:
                logger.warning(
                    "Could not load extensions config after MCP tool discovery (%s); discarding result",
                    type(exc).__name__,
                )
                fallback_snapshot = None
            recheck_path, recheck_sig = _current_config_state()
            post_snapshot = fallback_snapshot if recheck_path is None and recheck_sig is None else None
        init_succeeded = True
    finally:
        if not init_succeeded:
            with _init_condition:
                if _initializing_generation == claim_generation:
                    _initializing_generation = None
                _init_condition.notify_all()

    retired_pool = None
    with _init_condition:
        try:
            if _cache_generation != claim_generation:
                logger.info("MCP cache was reset during initialization; discarding stale result")
                return []

            publish = loaded_snapshot is not None and post_snapshot is not None and loaded_snapshot == post_snapshot and loaded_reset_signature == post_reset_signature
            if not publish:
                logger.warning("MCP config or shared reset generation changed during initialization; discarding stale result")
                retired_pool = _reset_mcp_tools_cache_state_and_retire_pool_locked()
            else:
                _mcp_tools_cache = loaded_tools
                _cache_initialized = True
                _config_path, _config_signature = post_path, post_sig
                _mcp_config_snapshot = post_snapshot
                _initialized_without_config = post_path is None
                _cache_reset_marker_signature = post_reset_signature
                logger.info("MCP tools initialized: %d tool(s) loaded (config path: %s)", len(_mcp_tools_cache), _config_path)
                return _mcp_tools_cache
        finally:
            if _initializing_generation == claim_generation:
                _initializing_generation = None
            _init_condition.notify_all()

    if retired_pool is not None:
        retired_pool.close_all_sync()
    return []


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
    while True:
        retired_pool = None
        with _init_lock:
            if _is_cache_stale():
                logger.info("MCP cache is stale, resetting for re-initialization...")
                retired_pool = _reset_mcp_tools_cache_state_and_retire_pool_locked()

            if _cache_initialized:
                return _mcp_tools_cache or []

            if _initializing_generation is not None:
                _init_condition.wait_for(lambda: _initializing_generation is None or _cache_initialized)
                continue

        if retired_pool is not None:
            retired_pool.close_all_sync()

        logger.info("MCP tools not initialized, performing lazy initialization...")
        # Only ``get_event_loop()`` may fall back to ``asyncio.run``: a
        # ``RuntimeError`` raised *by* ``initialize_mcp_tools()`` (for example
        # ``McpTaskConfigurationError``) must not trigger a second discovery
        # pass that respawns every stdio server and re-fetches OAuth tokens.
        try:
            loop: asyncio.AbstractEventLoop | None = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        try:
            if loop is None or loop.is_closed():
                asyncio.run(initialize_mcp_tools())
            elif loop.is_running():
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, initialize_mcp_tools())
                    future.result()
            else:
                loop.run_until_complete(initialize_mcp_tools())
        except Exception:
            logger.exception("Failed to lazy-initialize MCP tools")
            return []

        with _init_lock:
            if _cache_initialized:
                return _mcp_tools_cache or []


def refresh_mcp_cache_if_active() -> bool:
    """Retire stale MCP cache state without lazily initializing tools.

    Tool assembly skips ``get_cached_mcp_tools()`` when no MCP server is
    enabled, so a config change that disables the last server would otherwise
    leave the previous pool and its persistent sessions alive. This entry point
    performs only the staleness check:

    * it returns immediately when no MCP state was ever initialized and no
      initialization is in flight, so a process that never initialized MCP
      tools pays no config-hashing cost. A process that did publish a cache
      (including an empty one) still pays one stat+sha256 of the config file
      per call to check that cache for staleness;
    * it invalidates an in-flight initialization (bumping the cache generation)
      so tools discovered under the superseded config cannot publish;
    * it retires the pool outside the lock, matching ``get_cached_mcp_tools``.

    Returns:
        True when existing cache state or an in-flight initialization was
        retired.
    """
    retired_pool = None
    retired = False
    with _init_condition:
        if not _cache_initialized and _initializing_generation is None:
            return False
        if _initializing_generation is not None or _is_cache_stale():
            retired_pool = _reset_mcp_tools_cache_state_and_retire_pool_locked()
            retired = True
    if retired_pool is not None:
        retired_pool.close_all_sync()
    return retired


def _reset_mcp_tools_cache_state() -> None:
    """Reset cache state under ``_init_condition`` / ``_init_lock``."""
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    global _cache_generation, _mcp_config_snapshot, _initialized_without_config
    global _cache_reset_marker_signature

    _mcp_tools_cache = None
    _cache_initialized = False
    _config_path = None
    _config_signature = None
    _mcp_config_snapshot = None
    _initialized_without_config = False
    _cache_reset_marker_signature = None
    _cache_generation += 1
    _init_condition.notify_all()


def _reset_mcp_tools_cache_state_and_retire_pool_locked():
    """Retire the MCP session pool and reset cache state under one lock.

    Tool wrappers close over the module-level session-pool singleton when they
    are built. Any path that invalidates the tool cache must therefore swap the
    singleton before waiters/fresh initializers can rebuild wrappers, including
    automatic config-signature invalidation in ``get_cached_mcp_tools()``.
    """
    from deerflow.mcp.session_pool import reset_session_pool

    retired_pool = reset_session_pool()
    _reset_mcp_tools_cache_state()
    return retired_pool


def reset_mcp_tools_cache() -> None:
    """Reset the MCP tools cache.

    This is useful for testing or when you want to reload MCP tools.
    Also closes all persistent MCP sessions so they are recreated on
    the next tool load.
    """
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
        from deerflow.mcp.session_pool import reset_session_pool

        with _init_condition:
            # Retire the session-pool singleton before cache waiters can start a
            # fresh initialization. Otherwise a concurrent initializer can build
            # tool wrappers against the soon-to-be-detached pool and publish
            # them after this reset replaces the singleton.
            retired_pool = reset_session_pool()
            _reset_mcp_tools_cache_state()

        if retired_pool is not None:
            retired_pool.close_all_sync()
    except Exception:
        logger.debug("Could not close MCP session pool on cache reset", exc_info=True)

    logger.info("MCP tools cache reset")


def publish_mcp_tools_cache_reset() -> str | None:
    """Publish a shared-config reset generation, then retire local MCP state.

    The marker is written next to ``extensions_config.json`` because that file
    is already the runtime-editable directory shared by workers that consume
    the same config. A random generation avoids read-modify-write counters and
    cannot lose two concurrent reset requests: the final atomic write still
    differs from every worker's previously observed signature.

    Returns:
        The published generation, or ``None`` when no shared config path can be
        resolved and the operation therefore falls back to a process-local
        reset.
    """
    config_path = _resolve_config_path()
    if config_path is None:
        reset_mcp_tools_cache()
        return None

    # The marker is replaced atomically under ``extensions_config_write_lock``
    # and the cross-process ``extensions_config_file_lock``, the same discipline
    # every ``extensions_config.json`` writer follows.
    generation = MCP_CACHE_RESET_MARKER.publish(config_path)

    # Publish-before-retire is intentional.  A successful API response must
    # never mean only the handling worker was refreshed; if publication fails,
    # the exception propagates and the local cache remains intact for a safe,
    # idempotent retry.
    reset_mcp_tools_cache()
    return generation
