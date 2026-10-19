"""Configuration for the blob store (host-shared fields only).

Backend-private fields live in each backend's own config (parsed from
``backend_config``, a dict the factory passes verbatim to the backend). This
module holds ONLY the host-shared fields every backend / call site / factory
reads: ``enabled`` / ``backend`` / ``backend_config``. Keeping the shared
schema slim is what makes backends swappable and portable (a backend's knobs
do not leak onto the shared contract). Mirrors ``memory_config``: blobs are
persistent state, so the factory fails fast on an unresolvable ``backend``
instead of silently substituting a different storage backend.
"""

import logging
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Host-shared BlobStorageConfig fields (read by every backend / call site / factory).
_SHARED_FIELDS = frozenset({"enabled", "backend", "backend_config"})


class BlobStorageConfig(BaseModel):
    """Host-shared blob store configuration (backend-agnostic)."""

    enabled: bool = Field(
        default=False,
        description=("Whether to enable the content-addressed blob store. Default False: no producer is migrated yet, so a deployment that never sets this key behaves exactly as it does today (see docs/blob-storage.md)."),
    )
    backend: str = Field(
        default="local_fs",
        description=(
            "Blob store backend selector. Either a registered backend name "
            "(matching a `storage/backends/<name>/` folder that exposes "
            "`STORE_CLASS`, e.g. `local_fs`) or a dotted import path to a "
            "`BlobStore` subclass. The factory resolves this at "
            "`get_blob_store()` time and raises `ValueError` on failure "
            "(fail-fast: blobs are persistent state, so an unresolved backend "
            "must not be silently substituted with a different one)."
        ),
    )
    backend_config: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Backend-private config (a dict), passed verbatim to the backend by "
            "the factory. Each backend self-interprets it (local_fs reads "
            "`root`; an empty root defaults to `{runtime_home}/blobs`). Values "
            "live in the host config file (`config.yaml` "
            "`blob_storage.backend_config`); they do not belong on the shared "
            "schema."
        ),
    )


# Global configuration instance
_blob_storage_config: BlobStorageConfig = BlobStorageConfig()


def get_blob_storage_config() -> BlobStorageConfig:
    """Get the current blob store configuration.

    ``_blob_storage_config`` is only refreshed as a side effect of
    ``get_app_config()`` reloading (via ``_apply_singleton_configs`` ->
    ``load_blob_storage_config_from_dict``). A reader that reaches blob config
    without going through ``get_app_config()`` first -- e.g. a middleware
    deciding whether to externalize a tool result -- would otherwise see a
    stale ``blob_storage.enabled`` after a ``config.yaml`` edit, even though
    ``blob_storage.*`` is documented as hot-reloadable. Trigger the same
    signature-checked reload here so the singleton follows the config file.

    If ``get_app_config()`` has never been called (``_app_config`` is
    ``None``), there is no stale config to refresh, so we keep the
    pre-existing behaviour of returning the in-memory singleton. This avoids
    picking up a config file as a side effect of the first access to
    ``get_blob_storage_config()``, which would break callers that expect
    module-level defaults (e.g. unit tests).
    """
    # Lazy import: app_config imports this module, so a top-level import cycles.
    from .app_config import _app_config, get_app_config

    if _app_config is not None:
        try:
            get_app_config()
        except Exception:
            # If the config file is transiently broken (invalid YAML, schema
            # violation, missing env var, etc.), keep the last-good singleton
            # so an in-flight turn completes normally instead of crashing.
            logger.warning(
                "Failed to reload app config from get_blob_storage_config(); falling back to cached blob storage config.",
                exc_info=True,
            )
    return _blob_storage_config


def set_blob_storage_config(config: BlobStorageConfig) -> None:
    """Set the blob store configuration (tests / programmatic setup)."""
    global _blob_storage_config
    _blob_storage_config = config


def load_blob_storage_config_from_dict(config_dict: dict) -> None:
    """Load blob store configuration from a dictionary.

    Host-shared fields (``enabled`` / ``backend`` / ``backend_config``) are
    read directly. Unknown top-level keys (likely typos) are warned and
    ignored -- there are no legacy pre-abstraction fields to migrate (the
    blob store is new in this contract).
    """
    global _blob_storage_config
    config_dict = dict(config_dict or {})
    unknown = sorted(key for key in config_dict if key not in _SHARED_FIELDS)
    if unknown:
        logger.warning(
            "Unknown blob_storage config key(s) %r at top level (shared fields: %s); ignored.",
            unknown,
            sorted(_SHARED_FIELDS),
        )
        config_dict = {key: value for key, value in config_dict.items() if key in _SHARED_FIELDS}
    _blob_storage_config = BlobStorageConfig(**config_dict)
