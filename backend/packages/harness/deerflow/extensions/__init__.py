"""DeerFlow's extension mechanism (host side).

The public contracts live in the separate `deerflow-extension-api` package;
this module implements loading, registration, middleware injection and the
hook-site plumbing.
"""

from __future__ import annotations

import threading

from deerflow.extensions.loader import (
    Diagnostic,
    ExtensionLoadError,
    ExtensionSpec,
    load_extensions,
)
from deerflow.extensions.registry import EMPTY_EXTENSIONS, ExtensionRegistry, LoadedExtensions

_loaded: LoadedExtensions = EMPTY_EXTENSIONS


def get_loaded_extensions() -> LoadedExtensions:
    """Return the process-wide loaded extensions.

    Mirrors the existing `get_app_config()` convention so call sites can take
    an explicit override parameter and fall back to this.
    """
    return _loaded


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


def initialize_runtime_diagnostics(diagnostics: list[Diagnostic]) -> list[Diagnostic]:
    """Install and return the live diagnostic list for the current host."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.clear()
        _runtime_diagnostics.extend(diagnostics)
        return _runtime_diagnostics


def record_runtime_diagnostic(diagnostic: Diagnostic) -> None:
    """Collect one diagnostic in the canonical process sink."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.append(diagnostic)


def record_runtime_diagnostics(diagnostics: list[Diagnostic]) -> None:
    """Collect a diagnostic batch in the canonical process sink."""
    with _runtime_diagnostics_lock:
        _runtime_diagnostics.extend(diagnostics)


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
