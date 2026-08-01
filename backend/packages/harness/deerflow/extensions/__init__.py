"""DeerFlow's extension mechanism (host side).

The public contracts live in the separate `deerflow-extension-api` package;
this module implements loading, registration, middleware injection and the
hook-site plumbing.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from deerflow.extensions.loader import (
    Diagnostic,
    ExtensionLoadError,
    ExtensionSpec,
    load_extensions,
)
from deerflow.extensions.registry import EMPTY_EXTENSIONS, ExtensionRegistry, LoadedExtensions

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
    "set_loaded_extensions",
]
