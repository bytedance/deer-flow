"""DeerFlow's extension mechanism (host side).

The public contracts live in the separate `deerflow-extension-api` package;
this module implements loading, registration, middleware injection and the
hook-site plumbing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from deerflow.extensions.loader import (
    Diagnostic,
    ExtensionLoadError,
    ExtensionSpec,
    load_extensions,
)
from deerflow.extensions.registry import EMPTY_EXTENSIONS, ExtensionRegistry, LoadedExtensions

#: Runtime-context key carrying the run's immutable extension snapshot.
#:
#: The graph-build binding below is a ContextVar scoped to synchronous agent
#: construction, so it is long gone by the time a tool delegates work. Runtime
#: context is how the run reaches that later code. The double-underscore prefix
#: marks it as host-internal: the Gateway strips caller-supplied ``__`` keys,
#: and this snapshot is never part of the public extension contract.
EXTENSION_SNAPSHOT_CONTEXT_KEY = "__deerflow_extension_snapshot"

_loaded: LoadedExtensions = EMPTY_EXTENSIONS
_agent_build_extensions: ContextVar[LoadedExtensions | None] = ContextVar(
    "deerflow_agent_build_extensions",
    default=None,
)


def get_loaded_extensions() -> LoadedExtensions:
    """Return the process-wide loaded extensions.

    Mirrors the existing `get_app_config()` convention so call sites can take
    an explicit override parameter and fall back to this.
    """
    return _loaded


def get_agent_build_extensions() -> LoadedExtensions:
    """Return the run-bound snapshot while an agent graph is being built."""
    return _agent_build_extensions.get() or get_loaded_extensions()


@contextmanager
def bind_agent_build_extensions(loaded: LoadedExtensions) -> Iterator[None]:
    """Bind one immutable extension snapshot to synchronous graph assembly."""
    token = _agent_build_extensions.set(loaded)
    try:
        yield
    finally:
        _agent_build_extensions.reset(token)


def resolve_run_extensions(context: Any | None) -> LoadedExtensions | None:
    """Return the run's extension snapshot from *context*, or ``None``.

    Runtime context is caller-mergeable, so the value is type-checked rather
    than trusted. ``None`` means "this caller installed no snapshot" (embedded
    client, standalone LangGraph Server) and leaves consumers on their existing
    ``get_loaded_extensions()`` fallback.
    """
    if not isinstance(context, Mapping):
        return None
    snapshot = context.get(EXTENSION_SNAPSHOT_CONTEXT_KEY)
    return snapshot if isinstance(snapshot, LoadedExtensions) else None


def set_loaded_extensions(loaded: LoadedExtensions) -> None:
    global _loaded
    _loaded = loaded


def reset_loaded_extensions() -> None:
    """Reset to a FRESH empty set. Used by tests to prevent singleton leaks.

    Builds a new instance rather than reusing EMPTY_EXTENSIONS: that singleton
    owns a mutable ExtensionData app_store, so resetting to it would carry any
    write made while "empty" across every later reset and across the process.
    """
    global _loaded
    _loaded = ExtensionRegistry().build()


_runtime_diagnostics: list[Diagnostic] = []
_runtime_diagnostics_lock = threading.RLock()
_MAX_RUNTIME_DIAGNOSTICS = 1000


def _trim_runtime_diagnostics() -> None:
    overflow = len(_runtime_diagnostics) - _MAX_RUNTIME_DIAGNOSTICS
    if overflow > 0:
        del _runtime_diagnostics[:overflow]


def initialize_runtime_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Install and return the live diagnostic list for the current host."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.clear()
        _runtime_diagnostics.extend(diagnostics)
        _trim_runtime_diagnostics()
        return _runtime_diagnostics


def record_runtime_diagnostic(diagnostic: Diagnostic) -> None:
    """Collect one diagnostic in the canonical process sink."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.append(diagnostic)
        _trim_runtime_diagnostics()


def record_runtime_diagnostics(diagnostics: list[Diagnostic]) -> None:
    """Collect a diagnostic batch in the canonical process sink."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.extend(diagnostics)
        _trim_runtime_diagnostics()


def get_runtime_diagnostics() -> list[Diagnostic]:
    with _runtime_diagnostics_lock:
        return list(_runtime_diagnostics)


def reset_runtime_diagnostics() -> None:
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.clear()


__all__ = [
    "EMPTY_EXTENSIONS",
    "EXTENSION_SNAPSHOT_CONTEXT_KEY",
    "Diagnostic",
    "ExtensionLoadError",
    "ExtensionRegistry",
    "ExtensionSpec",
    "LoadedExtensions",
    "bind_agent_build_extensions",
    "get_agent_build_extensions",
    "get_loaded_extensions",
    "get_runtime_diagnostics",
    "initialize_runtime_diagnostics",
    "load_extensions",
    "record_runtime_diagnostic",
    "record_runtime_diagnostics",
    "reset_loaded_extensions",
    "reset_runtime_diagnostics",
    "resolve_run_extensions",
    "set_loaded_extensions",
]
