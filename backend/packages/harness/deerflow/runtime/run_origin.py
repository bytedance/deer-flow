"""Server-owned origin of a run or a thread (``deerflow_origin``).

A run started by the server on a user's behalf (a schedule, an IM channel, a
GitHub agent, an extension, an MCP notification) carries
``metadata["deerflow_origin"] = {"kind": ..., "provider"?: ..., "namespace"?: ...}``.
Run admission derives ``runs.origin_kind`` from it, which drives the activity
feed and the per-user unread state. A thread the server creates for such a run
keeps the same marker in its metadata.

The value is never accepted from a browser, PAT or API client: the Gateway
drops client copies and only stamps what a server-side launcher set (see
``app.gateway.run_origin``). It is a different key from the message-level
``deerflow_scheduled_origin`` that marks the scheduled prompt message inside a
run; code must never read one for the other.

Pinned by ``contracts/thread_origin_contract.json``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

DEERFLOW_ORIGIN_KEY = "deerflow_origin"
ORIGIN_KINDS: frozenset[str] = frozenset({"schedule", "im_channel", "github", "extension", "mcp_notification"})

_PROVIDER_RE = re.compile(r"[a-z0-9_-]{1,32}")
_MAX_NAMESPACE_CHARS = 96
_ALLOWED_KEYS = frozenset({"kind", "provider", "namespace"})


def admit_origin(value: object) -> dict[str, str] | None:
    """Return a clean copy of a well-formed origin, else ``None``.

    Shape: a mapping with ``kind`` in :data:`ORIGIN_KINDS`, an optional
    ``provider`` (at most 32 chars of ``[a-z0-9_-]``) and an optional
    ``namespace`` (1-96 chars, no ``:``). Anything else, including extra keys,
    is rejected as a whole rather than partially kept.
    """
    if not isinstance(value, Mapping) or not set(value).issubset(_ALLOWED_KEYS):
        return None
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in ORIGIN_KINDS:
        return None
    origin = {"kind": kind}
    provider = value.get("provider")
    if provider is not None:
        if not isinstance(provider, str) or not _PROVIDER_RE.fullmatch(provider):
            return None
        origin["provider"] = provider
    namespace = value.get("namespace")
    if namespace is not None:
        if not isinstance(namespace, str) or not namespace or len(namespace) > _MAX_NAMESPACE_CHARS or ":" in namespace:
            return None
        origin["namespace"] = namespace
    return origin


def make_origin(kind: str, *, provider: str | None = None, namespace: str | None = None) -> dict[str, str]:
    """Build an origin for a server-side launcher; raises ``ValueError`` when malformed."""
    value: dict[str, str] = {"kind": kind}
    if provider is not None:
        value["provider"] = provider
    if namespace is not None:
        value["namespace"] = namespace
    origin = admit_origin(value)
    if origin is None:
        raise ValueError(f"invalid run origin: {value!r}")
    return origin


def origin_kind_of(metadata: Mapping | None) -> str | None:
    """``metadata["deerflow_origin"]["kind"]`` when well-formed, else ``None`` (interactive or legacy)."""
    if not isinstance(metadata, Mapping):
        return None
    origin = admit_origin(metadata.get(DEERFLOW_ORIGIN_KEY))
    return origin["kind"] if origin is not None else None


__all__ = ["DEERFLOW_ORIGIN_KEY", "ORIGIN_KINDS", "admit_origin", "make_origin", "origin_kind_of"]
