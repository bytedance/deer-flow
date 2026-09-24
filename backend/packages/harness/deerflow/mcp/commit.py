"""Shared commit path for every writer of ``extensions_config.json``.

A writer that mutates the extensions config must persist the change and the
``mcpLifecycle`` counters in one atomic write, and must derive its local
reconciliation from the same validated candidate instead of re-reading the file
(see ``docs/superpowers/specs/2026-09-25-mcp-shared-lifecycle-generation.md``,
sections 3 and 12). This module owns that single join point:

1. read the *previous* lifecycle counters out of the caller's raw on-disk
   document (:func:`commit_extensions_config`),
2. compute the next counters from the real pre-mutation and post-mutation
   validated configs (the interceptor signal is derived, never caller-supplied),
3. overwrite the block in the raw document and write it atomically,
4. return an immutable :class:`CommittedMcpRevision` built from the validated
   candidate and the new counters.

When the atomic write itself raises, the outcome is *indeterminate*: the Docker
``EBUSY`` fallback overwrites in place, so the destination may already be
truncated or fully written. This module raises
:class:`MCPCommitOutcomeUnknownError` -- never "write failed, state unchanged"
(section 12 D4) -- and deliberately does **not** invalidate local MCP state
itself: this function runs inside the config critical section, while the
conservative invalidation waits for the retired pool's teardown. The writer
performs that invalidation after releasing the locks.

Locking is the caller's responsibility: ``commit_extensions_config`` must run
while the caller holds both ``extensions_config_write_lock`` (in-process) and
``extensions_config_file_lock`` (cross-process sidecar advisory lock), inside the
same critical section that read the raw document. This module performs no
locking of its own so the commit stays part of that one critical section rather
than acquiring the config locks again underneath it.
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.config.extensions_config import (
    ExtensionsConfig,
    atomic_write_extensions_config,
    validate_raw_extensions_config,
)
from deerflow.config.mcp_lifecycle import McpLifecycle, McpLifecycleError, parse_mcp_lifecycle
from deerflow.mcp.config_normalization import normalize_mcp_interceptor_paths
from deerflow.mcp.lifecycle_rules import compute_next_lifecycle

logger = logging.getLogger(__name__)


class MCPConfigWriteError(RuntimeError):
    """Base class for a config write whose outcome or follow-up is not clean.

    These errors exist so a writer never collapses a *committed* or
    *indeterminate* write into the pre-existing "write failed, state unchanged"
    story (see ``docs/superpowers/specs/2026-09-25-mcp-shared-lifecycle-generation.md``,
    section 12 D4).
    """


class MCPCommitOutcomeUnknownError(MCPConfigWriteError):
    """``atomic_write_extensions_config()`` raised mid-write.

    The Docker ``EBUSY`` path falls back to an in-place overwrite, so a raised
    exception can leave the destination partially or fully written. Local MCP
    state has **not** been invalidated yet: the writer must call
    :func:`deerflow.mcp.cache.force_local_mcp_invalidation` after releasing the
    config locks and before serving any existing binding.
    """


class MCPCommittedNotReconciledError(MCPConfigWriteError):
    """The config was committed but the local reconciliation fence raised.

    The write is durable; the process-local pool may not reflect it. Local MCP
    state has **not** been invalidated yet: the writer must call
    :func:`deerflow.mcp.cache.force_local_mcp_invalidation` after releasing the
    config locks.
    """


class MCPCommittedReloadFailedError(MCPConfigWriteError):
    """The config and fence were committed but the in-process reload raised.

    The change is on disk and the local fence is installed; only the cached
    in-process config failed to reload, so a caller must not treat this as
    "nothing changed".
    """


def enabled_stdio_fingerprints(config: ExtensionsConfig) -> dict[str, str]:
    """Map each enabled, buildable stdio server to its base connection fingerprint.

    The inputs are exactly what the lifecycle rules compare, so this is the
    canonical "which pooled resources exist and how are they addressed" view of
    one validated config. A server whose parameters cannot be built is skipped
    exactly as :func:`deerflow.mcp.client.build_servers_config` drops it during
    discovery, and non-stdio servers (never pooled) are skipped as well.

    Pure and synchronous: it only reads the in-memory config.
    """
    # Imported lazily so ``deerflow.mcp.commit`` (imported by writers) does not
    # pull the MCP session/transport stack in at import time.
    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    fingerprints: dict[str, str] = {}
    for server_name, server in config.get_enabled_mcp_servers().items():
        try:
            params = build_server_params(server_name, server)
        except Exception:
            continue
        if params.get("transport") != "stdio":
            continue
        fingerprints[server_name] = normalized_connection_fingerprint(params)
    return fingerprints


def _interceptor_identity(config: ExtensionsConfig) -> str:
    """Canonical identity of a config's custom ``mcpInterceptors`` selection.

    Matches the snapshot the MCP cache compares against its applied baseline, so
    a committed revision can be diffed without re-reading the file.
    """
    return json.dumps(normalize_mcp_interceptor_paths((config.model_extra or {}).get("mcpInterceptors")), sort_keys=True, ensure_ascii=False)


@dataclass(frozen=True)
class CommittedMcpRevision:
    """One committed, validated extensions config revision.

    Built from the validated candidate and the counters written in the same
    atomic write, so a writer can fence from it without re-reading the file.
    Treat ``servers`` as immutable: it is the committed stdio fingerprint map and
    callers must not mutate it in place.
    """

    config: ExtensionsConfig
    lifecycle: McpLifecycle
    servers: Mapping[str, str]
    interceptors: object


def validate_previous_config_lenient(raw_data: Mapping[str, Any]) -> ExtensionsConfig | None:
    """Validate a pre-mutation raw document, or ``None`` when it is unverifiable.

    D7-R3: the lifecycle protocol must not turn a repair into a dead end. A
    stored server (or any other stored value) that no longer validates must not
    make the *previous* snapshot derivation raise; the caller proceeds with
    ``previous_config = None`` so the shared commit treats every enabled server
    as newly generation-advanced (conservative, fail-closed).
    """
    try:
        return validate_raw_extensions_config(copy.deepcopy(dict(raw_data)))
    except Exception as exc:
        logger.warning(
            "Stored extensions config could not be validated; treating the previous effective state as unverifiable for this write: %s",
            exc,
        )
        return None


def commit_extensions_config(
    *,
    config_path: Path,
    raw_data: dict[str, Any],
    previous_config: ExtensionsConfig | None,
    new_config: ExtensionsConfig,
) -> CommittedMcpRevision:
    """Persist *raw_data* with recomputed ``mcpLifecycle`` counters and return the revision.

    Caller contract: this function must be called while holding both
    ``extensions_config_write_lock`` and ``extensions_config_file_lock``, inside
    the same critical section that read ``raw_data`` and validated
    ``previous_config``/``new_config``. It acquires no locks of its own.

    ``previous_config`` is the real pre-mutation validated config when the
    caller could read it, and ``None`` when the previous effective state is
    unverifiable (D7-R3: a stored server that no longer validates must not turn
    a repair into a dead end). ``None`` makes every enabled server in
    ``new_config`` look newly added, so each is bumped exactly once -- the
    conservative, fail-closed answer. A first migration write over a legacy file
    must still pass the real config so pre-existing servers are not counted as
    lifecycle events (D7-R1).

    The persisted block is derived as follows:

    * key absent (legacy file) -> D7-R1 migration grace: ``previous = None``
      with the *real* ``old_servers``, so a legacy file adopts a fresh baseline
      without inventing a lifecycle event;
    * present and valid -> continue the existing history;
    * present but malformed/unsupported -- including an explicit ``null`` --
      -> D7-R2: log a warning, reset ``previous = None`` and
      ``old_servers = {}`` so every enabled server bumps by one, and still write
      a fresh valid block. A writer must never refuse the write: it is the only
      API path that can repair the file.

    ``globalGeneration`` advances by one for every *unverifiable* baseline -- a
    previous config that would not validate (R3) or a malformed persisted block
    (R2) -- because the interceptor identity cannot be proven unchanged. The
    ordinary migration case (absent block, valid previous config) is not
    unverifiable and therefore does not advance it.

    The new block always overwrites whatever the raw document carried -- API
    clients can never set or merge lifecycle counters.
    """
    old_servers = enabled_stdio_fingerprints(previous_config) if previous_config is not None else {}
    # A baseline is *unverifiable* when the previous effective document could not
    # be validated (D7-R3), or when the persisted block itself is malformed
    # (D7-R2). Either way "equal content" cannot prove identity, so the whole pool
    # must be retired for this commit -- not only the per-server generations.
    unverifiable_baseline = previous_config is None
    previous: McpLifecycle | None = None
    # Presence, not truthiness: an explicit ``"mcpLifecycle": null`` is a
    # *malformed* block (R2), not the legacy "no block yet" case (R1). Stage 2
    # readers must use the same present-versus-absent boundary.
    if "mcpLifecycle" in raw_data:
        try:
            parsed = parse_mcp_lifecycle(raw_data["mcpLifecycle"])
            if parsed is None:
                raise McpLifecycleError("mcpLifecycle must be an object, got null")
        except McpLifecycleError as exc:
            logger.warning(
                "Replacing an invalid mcpLifecycle block with a fresh baseline; every enabled MCP server is treated as newly generation-advanced: %s",
                exc,
            )
            old_servers = {}
            unverifiable_baseline = True
        else:
            previous = parsed

    new_servers = enabled_stdio_fingerprints(new_config)
    # Derive the whole-pool signal here, from the two validated configs, so no
    # writer can pass a wrong (or stale) flag. This is the same normalized
    # identity the MCP cache compares against its applied baseline. An
    # unverifiable baseline cannot prove the interceptor identity was unchanged
    # ("never treat an unverifiable version as safe"), so it forces the
    # whole-pool generation forward in addition to the per-server bumps. The
    # ordinary migration case -- absent block with a *valid* previous config --
    # keeps comparing the two configs and therefore does not invent an edge.
    if unverifiable_baseline:
        interceptors_changed = True
    else:
        interceptors_changed = _interceptor_identity(previous_config) != _interceptor_identity(new_config)
    lifecycle = compute_next_lifecycle(previous, old_servers, new_servers, interceptors_changed=interceptors_changed)

    raw_data["mcpLifecycle"] = lifecycle.model_dump(by_alias=True)
    try:
        atomic_write_extensions_config(config_path, raw_data)
    except BaseException as exc:
        # D4: the ``EBUSY`` in-place fallback may already have overwritten the
        # destination before raising, so the outcome is indeterminate. Do NOT
        # invalidate here (this runs under the config locks, and the
        # conservative invalidation waits for session teardown); the caller
        # performs it after releasing them.
        raise MCPCommitOutcomeUnknownError(
            f"MCP lifecycle commit to {config_path} raised mid-write: the commit outcome is unknown (the file may be partially or fully written). The caller must conservatively invalidate local MCP state before relying on any binding.",
        ) from exc

    return CommittedMcpRevision(
        config=new_config,
        lifecycle=lifecycle,
        servers=dict(new_servers),
        interceptors=_interceptor_identity(new_config),
    )
