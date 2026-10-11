"""Shared per-server MCP lifecycle generations (``mcpLifecycle`` v1).

A Gateway worker installs binding epochs only for configuration transitions it
personally observes.  A second worker sharing the same ``extensions_config.json``
can therefore miss a ``delete(A) -> identical re-add(A)`` when the final effective
MCP slice equals the revision it already applied.  This module maintains the small
shared ledger that records a per-server *connection lifecycle* generation so a peer
can detect that history even when the fingerprint is unchanged.

The ledger stores only opaque tokens.  It never contains connection configuration
or resolved credentials, and it is deliberately invisible to
``_effective_mcp_config_snapshot`` so the token difference is observable on its own.

Schema (top level of ``extensions_config.json``):

    "mcpLifecycle": {"version": 1, "servers": {"A": "<32 lowercase hex>"}}

Tri-state parsing: the key is either absent (legacy, supported), valid, or
invalid.  Invalid means unverifiable, and callers must fail closed (full reset for
readers, conservative migration for writers) rather than treat it as unchanged.
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from collections.abc import Collection, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

logger = logging.getLogger(__name__)

LIFECYCLE_KEY = "mcpLifecycle"
LIFECYCLE_VERSION = 1

_TOKEN_RE = re.compile(r"[0-9a-f]{32}")
_LEGACY_PREFIX = "mcp-lifecycle-legacy:v1:"


class InvalidMcpLifecycle(ValueError):
    """Raised when ``mcpLifecycle`` is present but cannot be trusted."""


class McpLifecycleLedger(BaseModel):
    """Strict model for one ``mcpLifecycle`` block.

    Pydantic's default coercion would accept ``version=True`` for an ``int`` field,
    so the version and every token are validated with explicit ``type(...)`` checks.
    """

    model_config = ConfigDict(extra="forbid")

    version: int
    servers: dict[str, str]

    @field_validator("version", mode="before")
    @classmethod
    def _strict_version(cls, value: Any) -> Any:
        if type(value) is not int or value != LIFECYCLE_VERSION:
            raise ValueError("unsupported mcpLifecycle version")
        return value

    @field_validator("servers", mode="before")
    @classmethod
    def _strict_servers(cls, value: Any) -> Any:
        if type(value) is not dict:
            raise ValueError("mcpLifecycle.servers must be an object")
        for name, token in value.items():
            if type(name) is not str or not name:
                raise ValueError("mcpLifecycle server name must be a non-empty string")
            if type(token) is not str or _TOKEN_RE.fullmatch(token) is None:
                raise ValueError("mcpLifecycle token must be 32 lowercase hex characters")
        return value


def new_token() -> str:
    """Return a fresh opaque lifecycle token (128 random bits, lowercase hex)."""
    return secrets.token_hex(16)


def legacy_token(server_name: str, fingerprint: str) -> str:
    """Derive the stable in-memory token for a server with no ledger entry.

    Depends only on the server name and the secret-safe connection fingerprint, so
    every worker derives the same value before the first controlled write and no
    unchanged legacy server is retired.
    """
    material = f"{_LEGACY_PREFIX}{server_name}:{fingerprint}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def parse_mcp_lifecycle(raw_config: Mapping[str, Any] | None) -> McpLifecycleLedger | None:
    """Return the ledger, ``None`` when absent, or raise ``InvalidMcpLifecycle``.

    Absent (legacy) is a supported state.  Present-but-invalid is not.
    """
    if raw_config is None or LIFECYCLE_KEY not in raw_config:
        return None
    try:
        return McpLifecycleLedger.model_validate(raw_config[LIFECYCLE_KEY])
    except Exception as exc:  # noqa: BLE001 - any parse failure is unverifiable
        raise InvalidMcpLifecycle("mcpLifecycle is present but invalid") from exc


def _stdio_fingerprints(config) -> dict[str, str]:
    """Return the enabled stdio server names mapped to connection fingerprints."""
    from deerflow.mcp.client import build_server_params
    from deerflow.mcp.session_pool import normalized_connection_fingerprint

    fingerprints: dict[str, str] = {}
    for server_name, server in config.get_enabled_mcp_servers().items():
        try:
            connection = build_server_params(server_name, server)
        except Exception:  # noqa: BLE001 - unusable servers are absent from discovery too
            # ``build_servers_config`` drops a server whose parameters cannot be
            # built, so it is absent from discovery too. Omitting it keeps the
            # connection-identity baseline aligned with what discovery installs.
            logger.debug(
                "MCP server '%s' has unusable parameters; omitting it from the connection-identity baseline",
                server_name,
            )
            continue
        if connection.get("transport", "stdio") != "stdio":
            continue
        fingerprints[server_name] = normalized_connection_fingerprint(connection)
    return fingerprints


def effective_tokens(config, ledger: McpLifecycleLedger | None) -> dict[str, str]:
    """Return the effective per-server token map for one parsed config.

    Includes explicit ledger entries (tombstones included) plus legacy-derived
    tokens for active stdio servers that have no ledger entry yet.
    """
    tokens: dict[str, str] = dict(ledger.servers) if ledger is not None else {}
    for server_name, fingerprint in _stdio_fingerprints(config).items():
        tokens.setdefault(server_name, legacy_token(server_name, fingerprint))
    return tokens


def lifecycle_delta(
    previous_tokens: Mapping[str, str],
    candidate_tokens: Mapping[str, str],
    active_names: Collection[str],
) -> frozenset[str]:
    """Return active servers whose effective lifecycle token changed.

    These are the servers that must be force-rebound even when their connection
    fingerprint is unchanged.  A name absent from ``previous_tokens`` counts as
    changed so a newly tracked server is installed conservatively.
    """
    return frozenset(name for name in active_names if candidate_tokens.get(name) != previous_tokens.get(name))


def plan_mcp_lifecycle(
    previous_raw: Mapping[str, Any] | None,
    candidate_raw: Mapping[str, Any],
    *,
    candidate_config=None,
) -> dict[str, Any]:
    """Return the full ``mcpLifecycle`` block to embed in ``candidate_raw``.

    The slot of a server is its enabled stdio fingerprint, so any identity change,
    delete, re-add or brand-new name is one lifecycle transition.  ``previous_raw``
    must be the raw config read *before* the mutation being committed, and must not
    alias ``candidate_raw``.

    A previous config whose server schema cannot be parsed is a conservative
    migration: every candidate stdio server gets a fresh token, and tombstones are
    kept only when the old ledger itself is valid.  Unreadable JSON is the caller's
    responsibility to abort before reaching this function.
    """
    from deerflow.config.extensions_config import validate_raw_extensions_config

    if candidate_config is None:
        candidate_config = validate_raw_extensions_config(dict(candidate_raw))
    new_fingerprints = _stdio_fingerprints(candidate_config)

    previous_provable = previous_raw is not None
    previous_fingerprints: dict[str, str] = {}
    previous_ledger: McpLifecycleLedger | None = None
    if previous_raw is not None:
        try:
            previous_fingerprints = _stdio_fingerprints(validate_raw_extensions_config(dict(previous_raw)))
        except Exception:  # noqa: BLE001 - schema-invalid previous config
            previous_provable = False
        try:
            previous_ledger = parse_mcp_lifecycle(previous_raw)
        except InvalidMcpLifecycle:
            previous_provable = False
            previous_ledger = None

    ledger = dict(previous_ledger.servers) if previous_ledger is not None else {}

    if not previous_provable:
        for server_name in new_fingerprints:
            ledger[server_name] = new_token()
        return {"version": LIFECYCLE_VERSION, "servers": ledger}

    for server_name in set(previous_fingerprints) | set(new_fingerprints) | set(ledger):
        if previous_fingerprints.get(server_name) != new_fingerprints.get(server_name):
            # identity change, delete or re-add: always a fresh generation
            ledger[server_name] = new_token()
    return {"version": LIFECYCLE_VERSION, "servers": ledger}
