"""Blob store factory: folder-scan backend resolution + process singleton.

Mirrors ``deerflow/agents/memory/manager.py`` (the pattern maintainers pointed
at for issue #4189 item 2): backends live in ``storage/backends/<name>/``, each
package's ``__init__`` exposes ``STORE_CLASS``, and ``blob_storage.backend``
names one of them -- or a dotted import path for a backend that lives elsewhere.

Two accessors, so call sites cannot drift:

* :func:`get_blob_store_if_enabled` -- the one producers should use. Returns
  ``None`` when ``blob_storage.enabled`` is False, which is the default, so an
  unmigrated call site is a no-op rather than an accident.
* :func:`get_blob_store` -- for callers that require a store; raises
  :class:`BlobNotConfiguredError` when the store is disabled.

Both fail fast on an unresolvable backend. A blob store that silently starts on
a different backend than the operator configured would strand previously
written content, which is worse than refusing to start.
"""

from __future__ import annotations

import importlib
import logging
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

from deerflow.config.blob_storage_config import BlobStorageConfig, get_blob_storage_config
from deerflow.storage.contract import BlobNotConfiguredError, BlobStore, BlobStoreError

logger = logging.getLogger(__name__)

# Backend packages live in <this dir>/backends/<name>/.
_BACKENDS_DIR = Path(__file__).parent / "backends"
# Sentinel attribute each backend's __init__ exposes (a BlobStore subclass).
_STORE_CLASS_ATTR = "STORE_CLASS"

# Singleton instance + backend-registry cache (reset together by reset_blob_store).
_blob_store: BlobStore | None = None
_backends_cache: dict[str, type[BlobStore]] | None = None
_store_lock = threading.Lock()


def _import_backend_module(name: str) -> ModuleType:
    """Import ``backends/<name>`` and return its package module."""
    package_dir = _BACKENDS_DIR / name
    if not package_dir.is_dir() or not (package_dir / "__init__.py").is_file():
        raise ValueError(f"Unknown blob store backend {name!r}: no storage/backends/{name}/ package")
    return importlib.import_module(f"{__package__}.backends.{name}")


def _resolve_store_class(backend: str) -> type[BlobStore]:
    """Resolve ``blob_storage.backend`` to a :class:`BlobStore` subclass.

    Two forms are accepted, matching the memory backends' contract:

    * a registered backend name -- a folder under ``storage/backends/`` whose
      ``__init__`` exposes ``STORE_CLASS``;
    * a dotted import path -- ``pkg.mod.Class`` for a backend that lives
      outside this package (an extension or a deployment-local backend).
    """
    global _backends_cache

    if "." not in backend:
        if _backends_cache is None:
            _backends_cache = _scan_backends()
        cls = _backends_cache.get(backend)
        if cls is None:
            available = ", ".join(sorted(_backends_cache)) or "(none)"
            raise ValueError(f"Unknown blob store backend {backend!r}. Registered backends: {available}. Alternatively pass a dotted import path to a BlobStore subclass.")
        return cls

    module_path, _, class_name = backend.partition(":") if ":" in backend else backend.rpartition(".")
    if not module_path or not class_name:
        raise ValueError(f"Invalid blob storage backend {backend!r}: needs 'pkg.mod.Class' or 'pkg.mod:Class'")
    try:
        module = importlib.import_module(module_path)
        candidate = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise ValueError(f"Cannot import blob storage backend {backend!r}: {exc}") from exc
    if not (isinstance(candidate, type) and issubclass(candidate, BlobStore)):
        raise ValueError(f"Blob storage backend {backend!r} is not a BlobStore subclass")
    return candidate


def _scan_backends() -> dict[str, type[BlobStore]]:
    """Return ``{name: BlobStore subclass}`` for every backend folder.

    Imports through :func:`_import_backend_module` so the "is this a backend
    package?" check lives in exactly one place -- a folder that survives the
    scan is a folder the factory can resolve by name.
    """
    registry: dict[str, type[BlobStore]] = {}
    if not _BACKENDS_DIR.is_dir():
        return registry
    for entry in sorted(_BACKENDS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_"):
            continue
        try:
            module = _import_backend_module(entry.name)
        except ValueError as exc:
            # Not a backend package (no __init__.py); nothing to register.
            logger.debug("Skipping %s: %s", entry.name, exc)
            continue
        except Exception:
            # A broken optional backend must not take the whole store down:
            # log it and leave it out of the registry so the factory can still
            # resolve the default.
            logger.exception("Skipping blob store backend %r: import failed", entry.name)
            continue
        cls = getattr(module, _STORE_CLASS_ATTR, None)
        if isinstance(cls, type) and issubclass(cls, BlobStore):
            registry[entry.name] = cls
        else:
            logger.warning(
                "Blob store backend folder %r exposes no %s; skipping",
                entry.name,
                _STORE_CLASS_ATTR,
            )
    return registry


def _default_backend_config() -> dict[str, Any]:
    """Zero-config UX: default the backend root to deer-flow's state dir.

    Absolute and CWD-independent, so every gateway instance in a deployment
    that has not configured a shared root still lands in the same logical
    place on its own node -- which is exactly the single-host behaviour we
    must not change.
    """
    from deerflow.config.runtime_paths import runtime_home

    return {"root": str((Path(runtime_home()) / "blobs").resolve())}


def _resolve_backend_config(cfg: BlobStorageConfig) -> dict[str, Any]:
    backend_config = dict(cfg.backend_config or {})
    root = backend_config.get("root")
    if not root:
        backend_config.update(_default_backend_config())
    elif not Path(str(root)).is_absolute():
        # A relative root is resolved against runtime_home() (base_dir-relative,
        # CWD-independent) in host code, so backends stay free of any
        # runtime_home dependency -- same reason the memory factory does it.
        from deerflow.config.runtime_paths import runtime_home

        backend_config["root"] = str((Path(runtime_home()) / str(root)).resolve())
    return backend_config


def get_blob_store_if_enabled() -> BlobStore | None:
    """Return the singleton store, or ``None`` when the store is disabled.

    This is the accessor producers should call: ``None`` is an explicit,
    checkable signal that the deployment did not opt in, and the producer then
    keeps its existing server-local path.
    """
    if not get_blob_storage_config().enabled:
        return None
    return get_blob_store()


def get_blob_store() -> BlobStore:
    """Return the singleton :class:`BlobStore` for the active config.

    Raises :class:`BlobNotConfiguredError` when ``blob_storage.enabled`` is
    False, and ``ValueError`` when the configured backend cannot be resolved.
    """
    global _blob_store
    if _blob_store is not None:
        return _blob_store

    with _store_lock:
        if _blob_store is not None:
            return _blob_store

        cfg = get_blob_storage_config()
        if not cfg.enabled:
            raise BlobNotConfiguredError("blob_storage.enabled is False; no blob store is available. Use get_blob_store_if_enabled() at optional call sites.")

        cls = _resolve_store_class(cfg.backend)
        backend_config = _resolve_backend_config(cfg)
        _blob_store = cls.from_config(backend_config)
        logger.info("Blob store resolved: %s (backend=%r)", type(_blob_store).__name__, cfg.backend)
        return _blob_store


def reset_blob_store() -> None:
    """Drop the singleton and the backend registry (tests / config reload)."""
    global _blob_store, _backends_cache
    with _store_lock:
        if _blob_store is not None:
            try:
                _blob_store.close()
            except Exception:
                logger.warning("Blob store close() raised during reset", exc_info=True)
        _blob_store = None
        _backends_cache = None


__all__ = [
    "BlobStoreError",
    "get_blob_store",
    "get_blob_store_if_enabled",
    "reset_blob_store",
]
