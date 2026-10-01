"""Canonical encoding for composite plugin authorization targets.

One module owns every ``target`` string a plugin decision is asked about, so the
producers (the registered-action dispatcher, the page projection, the management
guards, the resource catalog) and the readers (providers, enterprise policy)
cannot disagree about encoding or validation.

A target is ``"{namespace}/{part}"``: the left side is always a host-validated
plugin namespace, the right side is the kind-specific component validated
against the charset of the layer that already owns it. The namespace charset
excludes ``/``, so the composite is unambiguous, and **no call site may build a
target by string concatenation** — every producer calls one of the three
constructors below, each of which raises :class:`PluginTargetError` instead of
returning a best-effort string.

Actions are carried for protocol fidelity only: the built-in RBAC provider
ignores ``AuthzRequest.action``, so read/write authority is separated by
*different targets*, never by different actions on one policy.
"""

from __future__ import annotations

import re
from typing import Literal

# Mirrors deerflow.config.plugin_settings (host registration rule) byte for byte.
_NAMESPACE_PATTERN = r"[a-z][a-z0-9_.-]{0,95}"
# Mirrors deerflow.extensions.registry's registered-backend-action rule.
_ACTION_PATTERN = r"[a-z][a-z0-9_-]{0,63}"
# Mirrors the browser module's surface-id rule (frontend/src/core/extensions/registry.ts).
_SURFACE_PATTERN = r"[a-z][a-z0-9-]{0,63}"

MANAGEMENT_READ_PART = "permissions.read"
MANAGEMENT_WRITE_PART = "permissions.write"

#: The only accepted management parts. Read and write are different targets so
#: the built-in provider can distinguish them (it ignores ``action``).
ManagementPart = Literal["permissions.read", "permissions.write"]

_NAMESPACE_RE = re.compile(_NAMESPACE_PATTERN)
_ACTION_RE = re.compile(_ACTION_PATTERN)
_SURFACE_RE = re.compile(_SURFACE_PATTERN)
_MANAGEMENT_RE = re.compile(f"(?:{re.escape(MANAGEMENT_READ_PART)}|{re.escape(MANAGEMENT_WRITE_PART)})")


class PluginTargetError(ValueError):
    """A plugin resource target could not be composed from host-validated components."""


def _join(namespace: object, part: object, *, field: str, pattern: re.Pattern[str]) -> str:
    """Compose ``namespace/part`` after validating both halves, or raise."""
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise PluginTargetError(f"invalid plugin namespace {namespace!r}; expected {_NAMESPACE_PATTERN}")
    if not isinstance(part, str) or not pattern.fullmatch(part):
        raise PluginTargetError(f"invalid plugin {field} {part!r}; expected {pattern.pattern}")
    return f"{namespace}/{part}"


def plugin_action_target(namespace: str, action_name: str) -> str:
    """Target for a registered plugin backend action (``resource="plugin_action"``)."""
    return _join(namespace, action_name, field="action name", pattern=_ACTION_RE)


def plugin_page_target(namespace: str, surface_id: str) -> str:
    """Target for a declared plugin page (``resource="plugin_page"``).

    ``plugin_action_target(ns, "reports")`` and ``plugin_page_target(ns, "reports")``
    are deliberately byte-identical: the resource differs, the target does not.
    Readers therefore look resources up by ``(resource, target)``, never by
    target alone.
    """
    return _join(namespace, surface_id, field="surface id", pattern=_SURFACE_RE)


def plugin_management_target(namespace: str, part: ManagementPart) -> str:
    """Target for a management read/write check (``resource="plugin_management"``)."""
    return _join(namespace, part, field="management part", pattern=_MANAGEMENT_RE)
