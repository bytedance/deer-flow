"""Pluggable blob store backends.

Each subpackage is a self-contained backend that exposes
``STORE_CLASS`` (a :class:`~deerflow.storage.contract.BlobStore`
subclass) in its ``__init__``. The drop-in contract: folder name ==
backend name == ``BlobStorageConfig.backend`` value.

Add a new backend by dropping a new folder here and setting
``blob_storage.backend: <name>`` -- no other deer-flow code changes.
The depth (layout, publish rules, portability, dotted-path escape hatch)
is owned by ``../AGENTS.md``; the retention/GC interaction lives in
``docs/blob-storage.md``.
"""
