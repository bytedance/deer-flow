"""Cache for MCP tools to avoid repeated loading."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from deerflow.config.file_signature import ConfigSignature as _ConfigSignature
from deerflow.config.file_signature import get_config_signature as _get_config_signature
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

# ---------------------------------------------------------------------------
# Applied MCP revision
#
# The *pool-applied* effective MCP revision: the revision the session pool has
# been reconciled to and the tools were built from. Unlike the published tool
# cache, it deliberately survives ``_reset_mcp_tools_cache_state()``. A config
# change clears the tool cache and starts rediscovery; a second change landing
# while that rediscovery is still pending must diff against the revision the pool
# was last reconciled to, never against an erased snapshot.
#
# These values may embed resolved credentials: they are never logged or
# persisted.
# ---------------------------------------------------------------------------
_mcp_applied_servers: dict[str, str] | None = None  # canonical per-server config JSON, declaration order
_mcp_applied_order: tuple[str, ...] | None = None
_mcp_applied_connections: dict[str, str] | None = None  # stdio base-connection fingerprints
_mcp_applied_interceptors: str | None = None
_mcp_applied_path: Path | None = None
_mcp_applied_signature: _ConfigSignature | None = None


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


def effective_server_config(server) -> dict:
    """Share the server-config normalization used by the merged MCP runtime."""
    return normalize_mcp_server_config(server)


def _effective_mcp_config_snapshot(config) -> str:
    """Serialize the MCP-only slice of an extensions config.

    ``extensions_config.json`` also carries skills and middleware settings, so
    the whole-file signature cannot distinguish an MCP change from a skill
    toggle. The enabled-server list preserves declaration order (it can affect
    tool ordering) while ``sort_keys`` only normalizes each server's field
    order. Parsed models are compared, so equivalent ``type``/``transport``
    spellings do not cause a needless rebuild.

    The result may embed resolved credentials. It stays in process memory and
    is never logged or written back to disk.
    """
    relevant = {
        "enabled_servers": [(name, effective_server_config(server)) for name, server in config.get_enabled_mcp_servers().items()],
        "mcpInterceptors": normalize_mcp_interceptor_paths((config.model_extra or {}).get("mcpInterceptors")),
    }
    return json.dumps(relevant, sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class _McpCacheTransition:
    """Per-server classification of an effective MCP-config change.

    ``retire_servers is None`` is the conservative whole-pool reset (a config
    path switch with a changed MCP slice, ``mcpInterceptors`` change,
    unreadable/unstable config, or a missing applied baseline). Otherwise
    ``retire_servers`` names exactly the servers
    whose pooled sessions must be torn down, and ``rebuild_servers`` names every
    server whose tools must be rediscovered.
    """

    rebuild_servers: frozenset[str]
    retire_servers: frozenset[str] | None


@dataclass(frozen=True)
class _McpIncomingRevision:
    """One parsed, signature-verified effective MCP revision read from disk."""

    config: Any
    path: Path | None
    signature: _ConfigSignature | None
    snapshot: str
    servers: dict[str, str]
    order: tuple[str, ...]
    connections: dict[str, str]
    interceptors: str


@dataclass(frozen=True)
class _McpReconciliationPlan:
    """A classified transition plus the pool operations it requires."""

    transition: _McpCacheTransition
    incoming: _McpIncomingRevision | None
    active: dict[str, str]
    removed: frozenset[str]


@dataclass(frozen=True)
class _PendingTeardown:
    """Detached-owner teardown to run *outside* every cache/pool lock."""

    pool: Any
    prepared: Any


def _canonical_server_snapshot(server) -> str:
    """Canonical per-server effective config JSON (declaration order kept outside)."""
    return json.dumps(effective_server_config(server), sort_keys=True, ensure_ascii=False)


def _stdio_connection_fingerprint(server_name: str, server) -> str | None:
    """Normalized base stdio connection fingerprint, or ``None`` when unpooled.

    Only stdio servers are pooled, and only the base connection identity is
    compared: per-call workspace ``cwd``/``TMPDIR`` additions are applied to a
    copy at call time and never reach this fingerprint. A server whose params
    cannot be built (an invalid stdio config) is treated as unpooled, exactly as
    ``build_servers_config`` drops it during discovery.
    """
    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    try:
        params = build_server_params(server_name, server)
    except Exception:
        return None
    if params.get("transport") != "stdio":
        return None
    return normalized_connection_fingerprint(params)


def _revision_from_config(config, *, path: Path | None, signature: _ConfigSignature | None) -> _McpIncomingRevision:
    """Build the revision view for an already-parsed extensions config."""
    enabled = config.get_enabled_mcp_servers()
    connections: dict[str, str] = {}
    for name, server in enabled.items():
        fingerprint = _stdio_connection_fingerprint(name, server)
        if fingerprint is not None:
            connections[name] = fingerprint
    return _McpIncomingRevision(
        config=config,
        path=path,
        signature=signature,
        snapshot=_effective_mcp_config_snapshot(config),
        servers={name: _canonical_server_snapshot(server) for name, server in enabled.items()},
        order=tuple(enabled.keys()),
        connections=connections,
        interceptors=json.dumps(normalize_mcp_interceptor_paths((config.model_extra or {}).get("mcpInterceptors")), sort_keys=True, ensure_ascii=False),
    )


def _signature_is_verifiable(signature: _ConfigSignature | None) -> bool:
    """A stat-only signature cannot prove that a config revision is unchanged."""
    return signature is not None and signature[2] is not None


def _read_stable_mcp_revision(config_path: Path, expected_signature: _ConfigSignature) -> _McpIncomingRevision | None:
    """Parse the config and return its MCP revision only if the file was stable.

    ``expected_signature`` is the signature observed by the caller. A signature
    without a content digest is unverifiable; the file is re-hashed after
    parsing: a mismatch means the config changed while it was
    being read, so no revision can be attributed to a single state and the caller
    must treat the cache as stale. Parse failures also return ``None``
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

    return _revision_from_config(config, path=config_path, signature=expected_signature)


def _record_applied_revision(revision: _McpIncomingRevision) -> None:
    """Publish *revision* as the applied baseline (call under ``_init_condition``)."""
    global _mcp_applied_servers, _mcp_applied_order, _mcp_applied_connections
    global _mcp_applied_interceptors, _mcp_applied_path, _mcp_applied_signature

    _mcp_applied_servers = dict(revision.servers)
    _mcp_applied_order = tuple(revision.order)
    _mcp_applied_connections = dict(revision.connections)
    _mcp_applied_interceptors = revision.interceptors
    _mcp_applied_path = revision.path
    _mcp_applied_signature = revision.signature


def _clear_applied_revision() -> None:
    """Drop the applied baseline (whole-pool resets only, not cache clears)."""
    global _mcp_applied_servers, _mcp_applied_order, _mcp_applied_connections
    global _mcp_applied_interceptors, _mcp_applied_path, _mcp_applied_signature

    _mcp_applied_servers = None
    _mcp_applied_order = None
    _mcp_applied_connections = None
    _mcp_applied_interceptors = None
    _mcp_applied_path = None
    _mcp_applied_signature = None


def _revision_matches_applied_baseline(revision: _McpIncomingRevision) -> bool:
    """True when *revision* describes the same effective MCP slice as the baseline.

    The applied baseline survives ``_reset_mcp_tools_cache_state()`` while the
    published ``_mcp_config_snapshot`` does not, so equivalence must be decided
    against the baseline: a selective reconcile can leave rediscovery pending
    when the config path switches.
    """
    return revision.servers == (_mcp_applied_servers or {}) and revision.order == (_mcp_applied_order or ()) and revision.interceptors == _mcp_applied_interceptors


def _full_reset_plan() -> _McpReconciliationPlan:
    """The conservative whole-pool reset plan."""
    return _McpReconciliationPlan(
        transition=_McpCacheTransition(frozenset(), None),
        incoming=None,
        active={},
        removed=frozenset(),
    )


def _classify_against_applied(incoming: _McpIncomingRevision) -> _McpReconciliationPlan | None:
    """Diff *incoming* against the applied baseline.

    This classifier does not mutate cache state. When only non-MCP fields
    change, it returns ``None``; the lazy caller ``_plan_cache_transition()``
    then adopts the new file signature under ``_init_condition``.

    Returns:
        ``None`` when the effective MCP slice is unchanged (PR1's
        skills/middleware-only no-op), otherwise the transition plus the exact
        pool operations it requires.
    """
    applied_servers = _mcp_applied_servers or {}
    applied_order = _mcp_applied_order or ()
    applied_connections = _mcp_applied_connections or {}
    incoming_servers = incoming.servers
    incoming_order = incoming.order
    incoming_connections = incoming.connections

    if incoming.interceptors != _mcp_applied_interceptors:
        logger.info("MCP interceptors changed; the whole MCP session pool must be reset")
        return _McpReconciliationPlan(
            transition=_McpCacheTransition(frozenset(), None),
            incoming=incoming,
            active={},
            removed=frozenset(),
        )

    removed = {name for name in applied_servers if name not in incoming_servers}
    rebuild = {name for name, snapshot in incoming_servers.items() if applied_servers.get(name) != snapshot}
    rebuild |= removed

    # Declaration order feeds tool ordering, so a pure reorder must rebuild every
    # server's tools. It must NOT retire anything: the connections are unchanged.
    if incoming_order != applied_order and set(incoming_order) == set(applied_order):
        rebuild = set(incoming_servers)

    if not rebuild:
        return None

    connection_changed = {name for name, fingerprint in incoming_connections.items() if name in applied_connections and applied_connections[name] != fingerprint}
    removed_connections = {name for name in applied_connections if name not in incoming_connections}
    active = {name: fingerprint for name, fingerprint in incoming_connections.items() if applied_connections.get(name) != fingerprint}
    return _McpReconciliationPlan(
        transition=_McpCacheTransition(frozenset(rebuild), frozenset(removed | connection_changed | removed_connections)),
        incoming=incoming,
        active=active,
        removed=frozenset(removed | removed_connections),
    )


def _plan_cache_transition(*, fence_in_flight_initialization: bool = False) -> _McpReconciliationPlan | None:
    """Classify the on-disk effective MCP config against the applied baseline.

    ``fence_in_flight_initialization`` distinguishes an explicit config-change
    path from an ordinary read. An explicit change must void a first
    initialization that has no applied baseline yet, because that discovery may
    have been started against the superseded config. A concurrent read must
    instead wait for and share that initialization.

    Returns:
        ``None`` when nothing MCP-relevant changed, otherwise the plan to apply.
    """
    global _config_path, _config_signature, _mcp_applied_path, _mcp_applied_signature

    # Nothing has been published or reconciled yet: never stale (PR1 contract),
    # and deployments without MCP pay no config-hashing cost.
    if not _cache_initialized and _mcp_applied_servers is None:
        if fence_in_flight_initialization and _initializing_generation is not None:
            logger.info("MCP initialization is in flight with no applied baseline; voiding the superseded initialization")
            return _full_reset_plan()
        return None

    if _mcp_applied_servers is None or _mcp_applied_order is None or _mcp_applied_connections is None:
        # The tool cache claims to be published but no trustworthy applied
        # baseline survives: only a whole-pool reset is safe.
        return _full_reset_plan()

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
    if _mcp_applied_signature is None:
        # A config that appears after an unconfigured initialization must be
        # picked up; a config deleted after a successful load keeps the
        # last-known-good fail-soft contract.
        if _initialized_without_config and current_signature is not None:
            logger.info("Extensions config appeared after an unconfigured MCP cache; cache is stale")
            return _full_reset_plan()
        return None

    if current_signature is None:
        return None

    path_changed = current_path != _mcp_applied_path
    if not path_changed and current_signature == _mcp_applied_signature and _signature_is_verifiable(current_signature):
        return None  # Unchanged, verified content-signature fast path.

    # A path switch is a recheck signal, not itself a reason to discard pooled
    # sessions. An equivalent MCP slice at a new path keeps the current pool.
    if path_changed:
        logger.info("MCP config path changed (%s -> %s); re-checking the effective MCP configuration", _mcp_applied_path, current_path)

    if current_path is None:
        return None

    incoming = _read_stable_mcp_revision(current_path, current_signature)
    if incoming is None:
        # Unreadable config, or one that changed while it was being read: no
        # revision can be trusted, so the whole pool is reset.
        logger.info("MCP config could not be read as a single stable revision; resetting the whole MCP cache")
        return _full_reset_plan()

    if path_changed and not _revision_matches_applied_baseline(incoming):
        return _full_reset_plan()

    plan = _classify_against_applied(incoming)
    if plan is None:
        # The file changed, but the effective MCP slice did not. Adopt its
        # verified location/signature without interrupting existing sessions.
        logger.info("Extensions config changed but the effective MCP configuration did not; keeping cached MCP tools and sessions")
        _config_path = current_path
        _config_signature = current_signature
        _mcp_applied_path = current_path
        _mcp_applied_signature = current_signature
        return None
    return plan


def _plan_explicit_reconciliation(names: frozenset[str]) -> _McpReconciliationPlan | None:
    """Plan a reconciliation for an explicitly reported change set.

    Used by the Gateway's config-mutation endpoints, which have already committed
    the write to disk. Names the config does not know about are a no-op unless
    the full on-disk diff reveals a missed change; a changed MCP slice at a
    new path or a changed ``mcpInterceptors`` list still takes the conservative
    whole-pool reset.
    """
    global _config_path, _config_signature, _mcp_applied_path, _mcp_applied_signature

    if _mcp_applied_servers is None or _mcp_applied_order is None or _mcp_applied_connections is None:
        if _initializing_generation is not None:
            logger.info("MCP initialization is in flight with no applied baseline; voiding the superseded initialization")
            return _full_reset_plan()
        return None  # Nothing has been reconciled yet: nothing to reconcile.

    current_path, current_signature = _current_config_state()
    if current_path is None or current_signature is None:
        return None  # Fail-soft: keep serving the last-known-good state.
    incoming = _read_stable_mcp_revision(current_path, current_signature)
    if incoming is None:
        return _full_reset_plan()
    if current_path != _mcp_applied_path:
        if not _revision_matches_applied_baseline(incoming):
            return _full_reset_plan()
        # The new path names an equivalent MCP slice. Adopt its verified
        # revision and keep the current pool, as in the lazy detection path.
        _config_path = current_path
        _config_signature = current_signature
        _mcp_applied_path = current_path
        _mcp_applied_signature = current_signature
        return None
    if incoming.interceptors != _mcp_applied_interceptors:
        return _McpReconciliationPlan(
            transition=_McpCacheTransition(frozenset(), None),
            incoming=incoming,
            active={},
            removed=frozenset(),
        )

    applied_servers = _mcp_applied_servers
    applied_connections = _mcp_applied_connections
    incoming_servers = incoming.servers
    incoming_connections = incoming.connections

    known = set(applied_servers) | set(incoming_servers) | set(applied_connections) | set(incoming_connections)
    # Defense in depth: the caller's reported set is a hint, not the source of
    # truth. A writer can miss a removal/change (or another process can land one
    # between the write and this read), and trusting only the reported names
    # would strand that server's old epoch/session in the pool while dropping it
    # from the applied baseline. Union in the complete effective diff so every
    # missed server is still classified.
    diff_names = {name for name in known if applied_servers.get(name) != incoming_servers.get(name) or applied_connections.get(name) != incoming_connections.get(name)}
    relevant = {name for name in names if name in known} | diff_names
    if not relevant:
        return None  # Unknown names: no-op.

    removed = {name for name in relevant if name not in incoming_servers}
    removed |= {name for name in relevant if name in applied_connections and name not in incoming_connections}
    if not removed and all(applied_servers.get(name) == incoming_servers.get(name) for name in relevant):
        return None  # The reported names are byte-identical: no-op.

    connection_changed = {name for name in relevant if name in applied_connections and name in incoming_connections and applied_connections[name] != incoming_connections[name]}
    active = {name: incoming_connections[name] for name in relevant if name in incoming_connections and applied_connections.get(name) != incoming_connections[name]}
    return _McpReconciliationPlan(
        transition=_McpCacheTransition(frozenset(relevant), frozenset(removed | connection_changed)),
        incoming=incoming,
        active=active,
        removed=frozenset(removed),
    )


def _apply_reconciliation_locked(plan: _McpReconciliationPlan) -> _PendingTeardown:
    """Apply *plan*; caller MUST hold ``_init_condition``.

    This never awaits and never runs owner teardown: the blocking teardown is
    returned to the caller so it happens outside ``_init_condition`` and outside
    ``pool._lock`` (and off the event loop when one is running).
    """
    from deerflow.mcp.session_pool import get_session_pool, reset_session_pool

    incoming = plan.incoming
    if incoming is not None:
        # A frozen durable-task configuration must reject the change BEFORE any
        # session is retired, so a rejected update leaves the pool untouched.
        from deerflow.mcp.tasks.runtime import validate_mcp_task_config_snapshot

        validate_mcp_task_config_snapshot(incoming.config)

    if plan.transition.retire_servers is None:
        retired_pool = reset_session_pool()
        prepared = retired_pool.prepare_retire_all() if retired_pool is not None else None
        _reset_mcp_tools_cache_state()
        _clear_applied_revision()
        return _PendingTeardown(pool=retired_pool, prepared=prepared)

    pool = get_session_pool()
    prepared = pool.reconcile_bindings(plan.active, plan.removed)
    # Retain the just-applied revision across the tool-cache clear so a
    # back-to-back edit diffs against it rather than an erased snapshot.
    _reset_mcp_tools_cache_state()
    if incoming is not None:
        _record_applied_revision(incoming)
    return _PendingTeardown(pool=pool, prepared=prepared)


_pending_teardowns: set[asyncio.Task[Any]] = set()


def _pending_teardown_work(pending: _PendingTeardown) -> Callable[[], None] | None:
    """The blocking teardown callable, or ``None`` when there is nothing to do."""
    if pending.pool is None:
        return None
    prepared = pending.prepared
    if prepared is None or (not prepared.entries and not prepared.inflight):
        return None  # Nothing was detached: never schedule an empty teardown.
    return lambda: pending.pool.close_prepared_owners_sync(prepared)


def _run_pending_teardown(pending: _PendingTeardown | None) -> None:
    """Run detached-owner teardown outside every lock and off the event loop.

    Blocking here is deliberate for synchronous callers: an owner on a foreign
    loop is waited on with the pool's bounded timeout. The cache entry points are
    also called from async contexts, so when a running loop exists the blocking
    wait is handed to a worker thread instead of stalling the loop. Owners are
    already signalled inside the pool-lock critical section, so a cancellation
    here cannot strand them.
    """
    if pending is None:
        return
    work = _pending_teardown_work(pending)
    if work is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        work()
        return
    task = loop.create_task(asyncio.to_thread(work))
    _pending_teardowns.add(task)
    task.add_done_callback(_pending_teardowns.discard)


def _classify_cache_transition() -> _McpCacheTransition | None:
    """Classify the current effective MCP config against the applied baseline.

    The cache is stale when the resolved extensions config path changed, when
    ``mcpInterceptors`` changed, when the effective per-server configuration
    changed, or when no trustworthy applied baseline exists. Using content
    equality (``!=``) instead of a strict mtime ``>`` comparison detects
    same-second edits and backward mtime moves, and tracking the resolved path
    detects a switch to a different config file. A content change alone is not
    sufficient: the file also carries skills and middleware settings, so the
    effective MCP slice is compared before any MCP state is retired.

    Returns:
        ``None`` when nothing MCP-relevant changed, otherwise the per-server
        transition to apply. ``retire_servers is None`` means the whole pool must
        be reset.
    """
    plan = _plan_cache_transition()
    return None if plan is None else plan.transition


def _is_cache_stale() -> bool:
    """Compatibility wrapper over :func:`_classify_cache_transition`.

    Not a read-only predicate: the planner adopts the new file signature when
    the effective MCP configuration is unchanged, and production callers run it
    under ``_init_condition``, the same lock the mutating paths use.
    """
    return _classify_cache_transition() is not None


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
    from deerflow.mcp.tools import get_mcp_tools

    loaded_tools = None
    loaded_snapshot = None
    post_path = None
    post_sig = None
    post_snapshot = None
    post_revision = None
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
        loaded_tools = await get_mcp_tools(extensions_config=loaded_config)
        post_path, post_sig = _current_config_state()
        if post_path is not None and post_sig is not None:
            post_revision = _read_stable_mcp_revision(post_path, post_sig)
            post_snapshot = post_revision.snapshot if post_revision is not None else None
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
                fallback_revision = _revision_from_config(ExtensionsConfig.from_file(), path=None, signature=None)
            except Exception as exc:
                logger.warning(
                    "Could not load extensions config after MCP tool discovery (%s); discarding result",
                    type(exc).__name__,
                )
                fallback_revision = None
            recheck_path, recheck_sig = _current_config_state()
            if recheck_path is None and recheck_sig is None:
                post_revision = fallback_revision
                post_snapshot = fallback_revision.snapshot if fallback_revision is not None else None
            else:
                post_revision = None
                post_snapshot = None
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

            publish = loaded_snapshot is not None and post_snapshot is not None and loaded_snapshot == post_snapshot
            if not publish:
                logger.warning("MCP config changed during initialization; discarding stale result")
                retired_pool = _reset_mcp_tools_cache_state_and_retire_pool_locked()
            else:
                _mcp_tools_cache = loaded_tools
                _cache_initialized = True
                _config_path, _config_signature = post_path, post_sig
                _mcp_config_snapshot = post_snapshot
                _initialized_without_config = post_path is None
                # Publishing a fresh revision also makes it the pool-applied
                # baseline: discovery seeded/validated every stdio binding
                # against exactly this revision.
                if post_revision is not None:
                    _record_applied_revision(post_revision)
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
        pending_teardown = None
        result: list[BaseTool] | None = None
        wait_for_initialization = False
        with _init_condition:
            plan = _plan_cache_transition()
            if plan is not None:
                logger.info("MCP cache is stale, reconciling the session pool for re-initialization...")
                pending_teardown = _apply_reconciliation_locked(plan)

            if _cache_initialized:
                result = _mcp_tools_cache or []
            elif _initializing_generation is not None:
                _init_condition.wait_for(lambda: _initializing_generation is None or _cache_initialized)
                wait_for_initialization = True

        # Teardown always runs outside every lock, and never on the event loop.
        _run_pending_teardown(pending_teardown)

        if result is not None:
            return result

        if wait_for_initialization:
            continue

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
      initialization is in flight, so deployments without MCP servers pay no
      config-hashing cost;
    * it invalidates an in-flight initialization (bumping the cache generation)
      so tools discovered under the superseded config cannot publish;
    * it reconciles the pool per server — a change that retires only the changed
      servers leaves every unrelated live session attached;
    * it runs owner teardown outside every lock, matching
      ``get_cached_mcp_tools``.

    Returns:
        True when existing cache state or an in-flight initialization was
        retired.
    """
    pending_teardown = None
    retired = False
    with _init_condition:
        if not _cache_initialized and _initializing_generation is None and _mcp_applied_servers is None:
            return False
        plan = _plan_cache_transition(fence_in_flight_initialization=True)
        if plan is not None:
            pending_teardown = _apply_reconciliation_locked(plan)
            retired = True
    _run_pending_teardown(pending_teardown)
    return retired


def reconcile_mcp_servers(changed: Collection[str] | None = None) -> bool:
    """Reconcile pooled MCP sessions and the tool cache with the on-disk config.

    This is the shared entry point for the Gateway's configuration-mutation
    endpoints and for cross-process lazy detection, so both paths make the same
    session-ownership decisions (I8).

    Args:
        changed: The server names whose effective configuration the caller just
            changed. ``None`` reads and classifies the whole on-disk effective
            MCP config against the applied baseline instead.

    Returns:
        True when MCP state was reconciled (tools cleared and/or servers
        retired), False for a no-op.
    """
    pending_teardown = None
    with _init_condition:
        if changed is None:
            plan = _plan_cache_transition(fence_in_flight_initialization=True)
        else:
            plan = _plan_explicit_reconciliation(frozenset(str(name) for name in changed))
        if plan is None:
            return False
        pending_teardown = _apply_reconciliation_locked(plan)
    _run_pending_teardown(pending_teardown)
    return True


def _reset_mcp_tools_cache_state() -> None:
    """Reset cache state under ``_init_condition`` / ``_init_lock``."""
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    global _cache_generation, _mcp_config_snapshot, _initialized_without_config

    _mcp_tools_cache = None
    _cache_initialized = False
    _config_path = None
    _config_signature = None
    _mcp_config_snapshot = None
    _initialized_without_config = False
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
    _clear_applied_revision()
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
            _clear_applied_revision()

        if retired_pool is not None:
            retired_pool.close_all_sync()
    except Exception:
        logger.debug("Could not close MCP session pool on cache reset", exc_info=True)

    logger.info("MCP tools cache reset")
