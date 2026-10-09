"""Cache for MCP tools to avoid repeated loading."""

import asyncio
import json
import logging
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.tools import BaseTool

from deerflow.config.file_signature import ConfigSignature as _ConfigSignature
from deerflow.config.file_signature import get_config_signature as _get_config_signature
from deerflow.config.shared_reset_marker import SharedResetMarker
from deerflow.mcp.config_normalization import normalize_mcp_interceptor_paths, normalize_mcp_server_config

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _AppliedMcpRevision:
    """Effective MCP revision whose stdio binding epochs have been applied.

    ``effective_snapshot`` is the same string
    ``_effective_mcp_config_snapshot`` produces, so it is directly comparable
    with the published baseline. ``interceptors`` isolates the global
    ``mcpInterceptors`` chain, because an interceptor change is allowed to fall
    back to the conservative full reset instead of a selective one.

    ``stdio_connections`` maps every enabled stdio server to
    ``normalized_connection_fingerprint(build_server_params(...))`` — the exact
    digest ``ensure_binding``/``reconcile_bindings`` consume. Those values
    are one-way digests, so resolved ``$VAR`` credentials never appear there.

    ``effective_snapshot`` is *not* secret-safe (it is the fully resolved MCP
    slice), so it is excluded from ``repr`` — the same contract
    ``_mcp_config_snapshot`` documents. Never log or persist this object's
    snapshot field.
    """

    effective_snapshot: str = field(repr=False)
    interceptors: str
    stdio_connections: Mapping[str, str]


# Reconciliation kinds produced by ``_plan_mcp_reconciliation_locked``. The
# "effective MCP configuration unchanged" case has no plan at all: it only
# adopts the new path/signature, matching the long-standing ``_is_cache_stale``
# contract for skills-only edits and equivalent path switches.
_RECONCILE_SELECTIVE = "selective"
_RECONCILE_FULL = "full"


@dataclass(frozen=True, slots=True)
class _McpReconciliation:
    """How one observed configuration state should be applied.

    ``selective`` carries the observed revision; ``_apply_mcp_reconciliation_locked``
    derives the changed/removed server set by diffing it against the applied
    baseline, so the classification and the epoch installation always see the
    same revision.
    """

    kind: str
    revision: _AppliedMcpRevision | None = None
    path: Path | None = None
    signature: _ConfigSignature | None = None


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

# Process-local reconciliation baseline: the effective MCP revision whose stdio
# bindings this process has already installed into the *current* pool singleton.
# It is deliberately separate from ``_mcp_config_snapshot`` (which records the
# revision the *published* tools were built from). The tool cache can be empty
# or have an in-flight discovery while the binding epoch is already advanced:
#
#   A(v1) tools published, applied = v1
#     -> A(v2) observed: install the v2 epoch, drop the v1 tools
#     -> A(v2) discovery still running
#     -> A(v3) observed: reconciliation must continue from *applied v2*, not
#        from the now-empty published baseline, or the second change is lost.
#
# A claim *installs* the revision it records (see
# ``_install_claimed_revision_locked``) rather than merely recording one handed
# to discovery, so this baseline means "these deployment epochs are in place".
# It is recorded when discovery starts, so a discovery that fails after seeding
# a binding still leaves a baseline that can retire the residual server.
_applied_mcp_revision: _AppliedMcpRevision | None = None

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


def _interceptors_snapshot(config) -> str:
    """Serialize the normalized global interceptor chain for classification.

    Mirrors what ``_effective_mcp_config_snapshot`` embeds so a bare string and
    its single-element list stay equivalent, while an order/identity change
    still compares unequal.
    """
    return json.dumps(
        normalize_mcp_interceptor_paths((config.model_extra or {}).get("mcpInterceptors")),
        sort_keys=True,
        ensure_ascii=False,
    )


def _mcp_revision_from_config(config) -> _AppliedMcpRevision:
    """Build the applied-reconciliation revision for a parsed config.

    Connection identity is derived through ``build_server_params`` +
    ``normalized_connection_fingerprint`` — never a ``model_dump()`` of the whole
    server — so presentation-only fields (``description``/``routing``/``tools``/
    ``tool_name_prefix``) cannot masquerade as a connection change.
    """
    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    stdio_connections: dict[str, str] = {}
    for server_name, server in config.get_enabled_mcp_servers().items():
        try:
            connection = build_server_params(server_name, server)
        except Exception:
            # ``build_servers_config`` drops a server whose parameters cannot be
            # built, so it is absent from discovery too. Omitting it here keeps
            # the connection-identity baseline aligned with what discovery can
            # actually install instead of raising into the hot staleness check.
            logger.debug(
                "MCP server '%s' has unusable parameters; omitting it from the connection-identity baseline",
                server_name,
            )
            continue
        if connection.get("transport", "stdio") == "stdio":
            stdio_connections[server_name] = normalized_connection_fingerprint(connection)
    return _AppliedMcpRevision(
        effective_snapshot=_effective_mcp_config_snapshot(config),
        interceptors=_interceptors_snapshot(config),
        stdio_connections=stdio_connections,
    )


def _derived_applied_revision(config) -> _AppliedMcpRevision | None:
    """Best-effort baseline for a config discovery is about to run against."""
    try:
        return _mcp_revision_from_config(config)
    except Exception:
        logger.warning(
            "Could not derive the MCP connection-identity baseline for the current revision; a later change will fall back to a conservative reset",
        )
        return None


def _signature_is_verifiable(signature: _ConfigSignature | None) -> bool:
    """True when a config signature carries a content digest.

    ``get_config_signature`` returns ``(mtime, size, None)`` when the file could
    be stat-ed but not read. Such a signature cannot prove the content is
    unchanged, so the MCP cache must neither publish nor adopt it.
    """
    return signature is not None and signature[2] is not None


def _load_stable_mcp_config(config_path: Path, expected_signature: _ConfigSignature):
    """Parse the config only if it is attributable to a single stable revision.

    ``expected_signature`` is the signature observed by the caller. A signature
    without a content digest is treated as unverifiable, and the file is
    re-hashed after parsing: a mismatch means the config changed while it was
    being read, so no state can be attributed to a single revision and the
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

    return config


def _read_stable_mcp_snapshot(config_path: Path, expected_signature: _ConfigSignature) -> str | None:
    """Return the effective MCP snapshot of a stable, verifiable revision."""
    config = _load_stable_mcp_config(config_path, expected_signature)
    if config is None:
        return None
    return _effective_mcp_config_snapshot(config)


def _read_stable_mcp_revision(
    config_path: Path,
    expected_signature: _ConfigSignature,
) -> tuple[object, _AppliedMcpRevision] | None:
    """Return the parsed config and reconciliation revision of a stable revision.

    The caller needs the parsed instance (not just the derived fingerprint map)
    to ask the frozen durable-task snapshot whether this revision may be applied.
    """
    config = _load_stable_mcp_config(config_path, expected_signature)
    if config is None:
        return None
    return config, _mcp_revision_from_config(config)


def _frozen_task_snapshot_rejects(config):
    """Return the rejection a frozen durable-task snapshot raises for ``config``.

    Durable background calls resolve their connection from the configuration
    frozen at Gateway startup, so installing a newer revision's binding epoch
    fences every status/cancel call with ``StaleMCPBindingError`` even though hot
    reload of that server is correctly rejected. Both decisions that install an
    epoch must therefore consult this first — the reconciliation planner falls
    back to the conservative full reset, and a discovery claim fails exactly as
    ``get_mcp_tools()`` would, without touching the pool.
    """
    from deerflow.mcp.tasks.runtime import McpTaskConfigurationError, validate_mcp_task_config_snapshot

    try:
        validate_mcp_task_config_snapshot(config)
    except McpTaskConfigurationError as rejection:
        return rejection
    return None


def _deployment_binding_delta(
    previous: _AppliedMcpRevision | None,
    revision: _AppliedMcpRevision,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Return ``(active, removed)`` deployment bindings for ``revision``.

    ``removed`` comes from the previously applied revision, so a server that
    disappeared since then gets a tombstone while every server still present with
    the same fingerprint keeps its epoch and session. With no applied baseline —
    the first claim in a process, or a revision whose baseline could not be
    derived — the reconciliation additionally retires every server the pool still
    holds deployment state for that this revision does not declare; that
    enumeration happens inside the pool's own lock (``retire_unlisted``) so a
    concurrent durable-task binding cannot slip past it. Both the classified
    transition and the discovery claim use this one computation, so their notion
    of "what changed" cannot drift.
    """
    active = dict(revision.stdio_connections)
    previous_connections = previous.stdio_connections if previous is not None else {}
    removed = set(previous_connections) - set(active)
    return active, tuple(sorted(removed))


def _install_claimed_revision_locked(pool, revision: _AppliedMcpRevision, *, previous: _AppliedMcpRevision | None) -> None:
    """Install ``revision``'s deployment epochs before discovery runs.

    Recording an applied baseline must mean the epochs are actually in place, not
    merely that discovery was handed this revision. A durable-task caller or an
    earlier failed discovery can already hold an older binding for the same
    server, and ``ensure_binding()`` fails closed on a fingerprint mismatch, so a
    claim that only *recorded* the revision would leave the cache permanently
    unable to publish. Reconciling here is idempotent for unchanged servers
    (their sessions survive) and is scoped to the deployment domain, so a
    deployment revision never retires a personal binding or session. Without a
    previous baseline the pool itself reports which unlisted deployment servers
    the claim must tombstone, under the same lock that installs the epochs.
    """
    active, removed = _deployment_binding_delta(previous, revision)
    pool.reconcile_bindings(
        active,
        removed,
        domain="deployment",
        retire_unlisted=previous is None,
    )


def _shared_reset_has_local_state_locked(pool) -> bool:
    """True when an unapplied shared reset generation still has state to retire.

    Published tools and an applied baseline both count. So does deployment state
    the pool still holds: a durable-task caller can bind a server and run a
    persistent session before this process ever publishes a cache, and such a
    session must not survive an explicit shared reset. Personal-domain state alone
    is deliberately not a reason — a deployment-side reset must not retire it.
    Caller must hold ``_init_condition``.
    """
    return _cache_initialized or _applied_mcp_revision is not None or bool(pool.retained_server_names(domain="deployment"))


def _has_mcp_reconciliation_state() -> bool:
    """True when this process holds state a config observation could affect.

    Published tools, a recorded applied revision and an in-flight discovery are
    all reasons to keep watching the config. A process that never initialized
    MCP pays no config-read cost (``refresh_mcp_cache_if_active`` contract).
    """
    return _cache_initialized or _applied_mcp_revision is not None or _initializing_generation is not None


def _plan_mcp_reconciliation_locked() -> _McpReconciliation | None:
    """Classify the currently observed MCP configuration against applied state.

    Returns ``None`` when there is nothing to apply, a ``selective`` plan when
    the effective MCP slice changed without touching the global interceptor
    chain, and a ``full`` plan for the conservative cases (shared reset marker
    change, interceptor change, unreadable/unverifiable config, or no applied
    baseline to diff against).

    The "effective MCP configuration did not change" case also returns ``None``
    but first adopts the new path/signature, preserving the long-standing
    ``_is_cache_stale`` contract for skills-only edits and equivalent path
    switches. Caller must hold ``_init_condition`` (which serialises
    classification and application, so two readers can never apply revisions
    out of order).
    """
    global _config_path, _config_signature

    if not _has_mcp_reconciliation_state():
        return None

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
            return _McpReconciliation(_RECONCILE_FULL)

    # Fail-soft: a config that disappears after a successful load keeps serving
    # its last-known-good MCP tools instead of tearing MCP down into an
    # unconfigured state (matching the pre-fix mtime-only contract). This is a
    # deliberate choice — a future change that wants "config deleted" to tear
    # down MCP servers needs its own explicit signal. A config that *appears*
    # after an unconfigured initialization has a readable signature, so it
    # skips this branch and is still picked up by the comparison below.
    if current_signature is None or current_path is None:
        return None

    if not _signature_is_verifiable(current_signature):
        logger.info("Extensions config signature has no content digest; treating the MCP cache as stale")
        return _McpReconciliation(_RECONCILE_FULL)

    if current_path == _config_path and current_signature == _config_signature:
        return None

    # The resolved path and/or the file content changed. Both are only signals
    # to re-read the effective MCP slice: the file also carries skills and
    # middleware settings, and a path switch can land on a file with the same
    # MCP configuration, so neither is an invalidation reason on its own.
    if current_path != _config_path:
        logger.info("MCP config path changed (%s -> %s); re-checking the effective MCP configuration", _config_path, current_path)

    loaded = _read_stable_mcp_revision(current_path, current_signature)
    if loaded is None:
        logger.info("Extensions config could not be read as a stable MCP revision; treating the MCP cache as stale")
        return _McpReconciliation(_RECONCILE_FULL)
    candidate_config, revision = loaded

    applied = _applied_mcp_revision
    if applied is not None and revision.effective_snapshot == applied.effective_snapshot:
        logger.info("Extensions config changed but the effective MCP configuration did not; keeping cached MCP tools and sessions")
        _config_path, _config_signature = current_path, current_signature
        return None

    if applied is not None and revision.interceptors == applied.interceptors:
        rejection = _frozen_task_snapshot_rejects(candidate_config)
        if rejection is not None:
            # Installing this revision's epochs would strand the durable callers
            # that still run against the frozen startup configuration, so keep
            # the conservative fallback: replace the pool (where those callers
            # rebind from the configuration they were started with) and never
            # install the rejected epoch.
            logger.info(
                "MCP configuration revision is rejected by the frozen durable-task snapshot (%s); resetting instead of installing binding epochs",
                type(rejection).__name__,
            )
            return _McpReconciliation(_RECONCILE_FULL)
        return _McpReconciliation(
            _RECONCILE_SELECTIVE,
            revision=revision,
            path=current_path,
            signature=current_signature,
        )

    # Either there is no applied baseline to diff against, or the global
    # interceptor chain changed. Both keep the pre-PR-C conservative behavior:
    # replace the pool instead of guessing which sessions may be reused.
    logger.info(
        "MCP configuration changed without an applicable selective baseline (interceptors %s); cache is stale",
        "changed" if applied is not None else "unknown",
    )
    return _McpReconciliation(_RECONCILE_FULL)


def _invalidate_published_tools_locked() -> None:
    """Drop the published tool cache and supersede in-flight discovery.

    Keeps the session-pool singleton and every binding epoch that
    ``_apply_mcp_reconciliation_locked`` did not change, so unchanged stdio
    sessions keep serving. Caller must hold ``_init_condition``.
    """
    global _mcp_tools_cache, _cache_initialized, _mcp_config_snapshot, _cache_generation

    _mcp_tools_cache = None
    _cache_initialized = False
    _mcp_config_snapshot = None
    _cache_generation += 1
    _init_condition.notify_all()


def _apply_mcp_reconciliation_locked(plan: _McpReconciliation):
    """Apply ``plan`` under ``_init_condition``; return a retired pool, if any.

    The whole transition is synchronous, so classification, epoch installation
    and cache-generation invalidation cannot interleave with another in-process
    reconciliation. Blocking owner teardown is never performed here: a selective
    transition only detaches and signals owners (the pool's detached-owner reaper
    owns the ``__aexit__``), and a full transition closes the retired pool after
    the caller leaves the lock.
    """
    global _applied_mcp_revision, _config_path, _config_signature, _initialized_without_config

    if plan.kind == _RECONCILE_SELECTIVE:
        from deerflow.mcp.session_pool import get_session_pool

        revision = plan.revision
        assert revision is not None
        pool = get_session_pool()
        active, removed = _deployment_binding_delta(_applied_mcp_revision, revision)
        previous_connections = _applied_mcp_revision.stdio_connections
        re_epoching = sorted(name for name, fingerprint in active.items() if previous_connections.get(name) != fingerprint)
        logger.info(
            "MCP selective reconciliation: %d active stdio server(s), re-epoching %s, retiring %s",
            len(active),
            re_epoching or "none",
            sorted(removed) or "none",
        )
        pool.reconcile_bindings(active, removed, domain="deployment")

        _applied_mcp_revision = revision
        _config_path, _config_signature = plan.path, plan.signature
        _initialized_without_config = plan.path is None
        _invalidate_published_tools_locked()
        return None

    assert plan.kind == _RECONCILE_FULL
    logger.info("MCP conservative reconciliation: retiring the whole session pool and tool cache")
    return _reset_mcp_tools_cache_state_and_retire_pool_locked()


def _is_cache_stale() -> bool:
    """Return True when the observed MCP configuration must be re-applied.

    This is the classification entry point used by the cache's own hot paths.
    A ``None`` plan means "nothing to do" (including the fail-soft "config
    deleted after a successful load" contract), and the "effective MCP
    configuration unchanged" case adopts the new path/signature before
    returning False, exactly as the pre-PR-C predicate did. Callers that need to
    apply a non-``None`` plan use ``_plan_mcp_reconciliation_locked`` directly so
    classification and application happen under one critical section.
    """
    return _plan_mcp_reconciliation_locked() is not None


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
    global _cache_reset_marker_signature, _applied_mcp_revision

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
        retired_before_claim = None
        # The retired pool is always torn down, even when the validation further
        # down fails: reset_session_pool() only fences and unlinks the singleton,
        # so skipping close_all_sync() would leave that pool's owners running
        # without ever receiving a close signal. The teardown itself stays
        # outside every lock.
        try:
            with _init_condition:
                if _cache_generation != claim_generation:
                    logger.info("MCP cache was reset before tool discovery; discarding superseded initialization")
                    return []

                claimed_pool = get_session_pool()
                if loaded_reset_signature != _cache_reset_marker_signature and _shared_reset_has_local_state_locked(claimed_pool):
                    # A shared reset published after the last staleness check but
                    # before this claim must retire local MCP state: adopting its
                    # marker here would swallow the reset and keep serving pooled
                    # sessions created before it. Retire first, then re-own this
                    # claim under the new generation on the replacement pool. A
                    # process with no local MCP state — not even a durable-task
                    # caller's deployment binding — has nothing to retire, so it
                    # adopts the current generation instead: that is how a restart
                    # picks up an existing marker without a needless reset, and why
                    # personal-domain-only state keeps its domain boundary.
                    logger.info("Shared MCP cache reset generation changed before this claim; retiring local MCP state")
                    retired_before_claim = _reset_mcp_tools_cache_state_and_retire_pool_locked()
                    claim_generation = _cache_generation
                    _initializing_generation = claim_generation
                    claimed_pool = get_session_pool()
                # Claim the revision by *installing* it, not merely recording it, and
                # do so before discovery runs: the applied baseline then really means
                # "these deployment epochs are in place". A later observation must be
                # classifiable against this revision even when nothing was ever
                # published (failed/cancelled discovery), so a residual stdio binding
                # from this revision can still be retired. An unbuildable revision
                # clears the baseline instead, keeping the next change conservative
                # rather than diffing against state we cannot trust.
                # Record the marker this claim observed before anything can fail
                # below: if it differed, the reset above already retired the state
                # that generation required, so it must not be re-applied on retry.
                _cache_reset_marker_signature = loaded_reset_signature
                previous_revision = _applied_mcp_revision
                loaded_revision = _derived_applied_revision(loaded_config)
                if loaded_revision is None:
                    _applied_mcp_revision = None
                else:
                    rejection = _frozen_task_snapshot_rejects(loaded_config)
                    if rejection is not None:
                        # Fail exactly as get_mcp_tools() would, but before any epoch
                        # is installed, so the durable callers that still use the
                        # frozen startup configuration keep working.
                        logger.warning(
                            "MCP configuration revision is rejected by the frozen durable-task snapshot (%s); no binding epoch installed",
                            type(rejection).__name__,
                        )
                        raise rejection
                    _install_claimed_revision_locked(claimed_pool, loaded_revision, previous=previous_revision)
                    _applied_mcp_revision = loaded_revision
        finally:
            if retired_before_claim is not None:
                retired_before_claim.close_all_sync()

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
                # Reconcile against the revision observed now instead of forcing
                # a whole-pool replacement: only servers whose connection
                # identity changed (or that disappeared) lose their session.
                plan = _plan_mcp_reconciliation_locked()
                if plan is None:
                    _invalidate_published_tools_locked()
                else:
                    retired_pool = _apply_mcp_reconciliation_locked(plan)
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
        waiting_generation = None
        with _init_condition:
            plan = _plan_mcp_reconciliation_locked()
            if plan is not None:
                if plan.kind == _RECONCILE_SELECTIVE:
                    logger.info("MCP cache is stale, selectively reconciling affected stdio servers...")
                else:
                    logger.info("MCP cache is stale, resetting for re-initialization...")
                retired_pool = _apply_mcp_reconciliation_locked(plan)

            # Applying a plan always clears the published cache, so this return
            # cannot skip a retirement produced above.
            if _cache_initialized:
                return _mcp_tools_cache or []

            if _initializing_generation is not None:
                waiting_generation = _initializing_generation

        # Deliver the retirement before every wait/retry path. `reset_session_pool()`
        # only fences and unlinks the pool, so waiting for another initializer here
        # would otherwise strand the retired pool's owners without a close signal.
        if retired_pool is not None:
            retired_pool.close_all_sync()

        if waiting_generation is not None:
            # Re-acquire the condition before waiting so the predicate cannot miss
            # a wakeup, and wait on the exact generation that was observed.
            with _init_condition:
                _init_condition.wait_for(lambda: _cache_initialized or _initializing_generation != waiting_generation)
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

    * it returns immediately when no MCP state was ever initialized, applied
      or in flight, so a process that never initialized MCP tools pays no
      config-hashing cost. A process that did publish a cache (including an
      empty one) — or already installed a binding epoch — still pays one
      stat+sha256 of the config file per call to check for staleness;
    * it invalidates an in-flight initialization (bumping the cache generation)
      when the observed revision no longer matches what discovery was handed, so
      tools discovered under a superseded config cannot publish;
    * it applies a selective transition in place, or retires the pool outside
      the lock for the conservative fallback, matching
      ``get_cached_mcp_tools``.

    Returns:
        True when existing cache state or an in-flight initialization was
        retired or selectively reconciled.
    """
    retired_pool = None
    retired = False
    with _init_condition:
        plan = _plan_mcp_reconciliation_locked()
        if plan is not None:
            retired_pool = _apply_mcp_reconciliation_locked(plan)
            retired = True
    if retired_pool is not None:
        retired_pool.close_all_sync()
    return retired


def _reset_mcp_tools_cache_state() -> None:
    """Reset cache state under ``_init_condition`` / ``_init_lock``."""
    global _mcp_tools_cache, _cache_initialized, _config_path, _config_signature
    global _cache_generation, _mcp_config_snapshot, _initialized_without_config
    global _cache_reset_marker_signature, _applied_mcp_revision

    _mcp_tools_cache = None
    _cache_initialized = False
    _config_path = None
    _config_signature = None
    _mcp_config_snapshot = None
    _initialized_without_config = False
    _cache_reset_marker_signature = None
    # The replacement pool starts with no bindings, so there is no applied
    # reconciliation baseline to diff against until the next discovery runs.
    _applied_mcp_revision = None
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
