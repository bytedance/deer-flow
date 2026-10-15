"""Content-addressed blob store (issue #4189, item 2).

See ``contract.py`` for the interface and ``AGENTS.md`` for how to add a
backend. Nothing in deer-flow writes here until ``blob_storage.enabled`` is
True and a producer has been migrated to the store.
"""

from deerflow.storage.contract import (
    BlobNotConfiguredError,
    BlobNotFoundError,
    BlobReadError,
    BlobRef,
    BlobStore,
    BlobStoreError,
    BlobWriteError,
    is_valid_blob_kind,
    validate_blob_kind,
)
from deerflow.storage.manager import get_blob_store, get_blob_store_if_enabled, reset_blob_store

__all__ = [
    "BlobNotFoundError",
    "BlobNotConfiguredError",
    "BlobReadError",
    "BlobRef",
    "BlobStore",
    "BlobStoreError",
    "BlobWriteError",
    "get_blob_store",
    "get_blob_store_if_enabled",
    "is_valid_blob_kind",
    "reset_blob_store",
    "validate_blob_kind",
]
