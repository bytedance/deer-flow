"""Local filesystem blob store -- the default backend.

Layout (content-addressed, sharded)::

    <root>/<kind>/<sha256[:2]>/<sha256>          the bytes
    <root>/<kind>/<sha256[:2]>/<sha256>.json     sidecar metadata

The address is the SHA-256 of the content, so:

* writes are idempotent -- putting the same bytes again finds the file already
  present and does nothing;
* deduplication is free -- two producers that externalize the same output share
  one file;
* a reader can verify what it got back against the address, which is what makes
  "which content" a safe replacement for "where on this machine".

The sidecar carries what cannot be derived from the bytes alone
(``content_type``, ``writer_thread_id``, creation time). Reads do not depend on
it: a lost or truncated sidecar must not make blob content unreadable. It is also
**not a reference count** -- ``writer_thread_id`` records whichever writer landed
first, and identical bytes collapse to one file, so a sweep must confirm that no
surviving reference needs the content before unlinking it (the rule in
``docs/blob-storage.md``).

Concurrency: two gateway instances may put the same blob at the same time.
Both write to a unique temp file in the destination directory and
``os.replace`` it into place, so the last writer wins with identical content
and no reader ever observes a partial file. On Windows ``os.replace`` is
atomic within a volume, which is why the temp file is created in the
destination directory rather than a global temp dir.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from deerflow.storage.contract import (
    BlobNotFoundError,
    BlobReadError,
    BlobRef,
    BlobStore,
    BlobStoreError,
    BlobWriteError,
    validate_blob_kind,
)

logger = logging.getLogger(__name__)

_META_SUFFIX = ".json"
_MAX_BLOB_BYTES = 64 * 1024 * 1024  # defense-in-depth cap on a single put
# os.replace retry budget for the concurrent-writer race (see _publish).
_REPLACE_ATTEMPTS = 3
_REPLACE_BACKOFF_SECONDS = 0.02


class LocalFsBlobStore(BlobStore):
    """Content-addressed store on the local filesystem.

    This is the default and the migration bridge: when ``root`` points at a
    shared volume (NFS, EFS, a PVC in ``ReadWriteMany``) the store already
    gives multi-instance resolution with no object storage dependency. The S3
    backend is a later, optional extra -- it implements the same contract.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).expanduser()
        try:
            self._root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise BlobWriteError(f"Cannot create blob store root {self._root}: {exc}") from exc
        if not os.access(self._root, os.W_OK):
            raise BlobWriteError(f"Blob store root is not writable: {self._root}")

    @classmethod
    def from_config(cls, backend_config: dict[str, Any]) -> LocalFsBlobStore:
        root = backend_config.get("root")
        if not root:
            raise ValueError("local_fs blob store requires backend_config.root (the factory injects a default)")
        return cls(root=str(root))

    # -- layout -----------------------------------------------------------

    def _paths_for(self, ref: BlobRef) -> tuple[Path, Path]:
        shard_dir = self._root / ref.kind / ref.sha256[:2]
        return shard_dir / ref.sha256, shard_dir / f"{ref.sha256}{_META_SUFFIX}"

    # -- contract ---------------------------------------------------------

    def put_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        content_type: str | None = None,
        thread_id: str | None = None,
    ) -> BlobRef:
        validate_blob_kind(kind)
        if len(data) > _MAX_BLOB_BYTES:
            raise BlobWriteError(f"Refusing to store {len(data)} bytes (cap is {_MAX_BLOB_BYTES})")

        digest = hashlib.sha256(data).hexdigest()
        ref = BlobRef(sha256=digest, size=len(data), kind=kind, content_type=content_type)
        data_path, meta_path = self._paths_for(ref)
        shard_dir = data_path.parent

        if data_path.is_file():
            # Idempotent re-put: content already present. Ensure the sidecar
            # exists (an earlier put may have crashed between the two writes).
            if not meta_path.is_file():
                self._write_meta(ref, meta_path, thread_id)
            return ref

        try:
            shard_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".put-", suffix=".tmp", dir=shard_dir)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._publish(tmp_name, data_path, data)
            except BaseException:
                # Best effort: a stranded temp file must not accumulate.
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            self._write_meta(ref, meta_path, thread_id)
        except BlobWriteError:
            raise
        except OSError as exc:
            raise BlobWriteError(f"Failed to persist blob {ref.sha256[:12]}: {exc}") from exc
        return ref

    def get_bytes(self, ref: BlobRef) -> bytes:
        data_path, _ = self._paths_for(ref)
        try:
            data = data_path.read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFoundError(f"Blob {ref.sha256[:12]} not found under kind {ref.kind!r}") from exc
        except OSError as exc:
            raise BlobReadError(f"Failed to read blob {ref.sha256[:12]}: {exc}") from exc

        # Verify against the address. A content-addressed store that returns
        # the wrong bytes silently is indistinguishable from a corrupt
        # checkpoint, so fail loudly instead — naming WHICH check failed:
        # a size delta points at truncation/partial writes, a digest mismatch
        # at same-size corruption (bit rot), and conflating the two sends the
        # debugger in the wrong direction ("got 1024 bytes, expected 1024").
        if len(data) != ref.size:
            raise BlobReadError(f"Blob {ref.sha256[:12]} size mismatch on read (got {len(data)} bytes, expected {ref.size}); the store may be truncated or corrupted")
        digest = hashlib.sha256(data).hexdigest()
        if digest != ref.sha256:
            raise BlobReadError(f"Blob {ref.sha256[:12]} content digest mismatch on read (content hashes to {digest[:12]}, ref names {ref.sha256[:12]}); the store may be corrupted")
        return data

    def exists(self, ref: BlobRef) -> bool:
        data_path, _ = self._paths_for(ref)
        return data_path.is_file()

    def delete(self, ref: BlobRef) -> None:
        data_path, meta_path = self._paths_for(ref)
        removed = False
        for path in (data_path, meta_path):
            try:
                path.unlink()
                removed = True
            except FileNotFoundError:
                continue
            except OSError as exc:
                # The neutral base, not BlobReadError: this error family is
                # public API from day one, and a caller matching on a read
                # failure must not be handed a failed unlink it cannot read as
                # one.
                raise BlobStoreError(f"Failed to delete blob {ref.sha256[:12]}: {exc}") from exc
        if not removed:
            logger.debug("delete on absent blob %s (kind=%s): already gone", ref.sha256[:12], ref.kind)

    def close(self) -> None:  # noqa: B027 - nothing to release
        """No handles to close; the store is stateless beyond the root path."""

    # -- internals --------------------------------------------------------

    def _publish(self, tmp_path: str, data_path: Path, data: bytes) -> None:
        """Move the temp file into place, tolerating a concurrent writer.

        ``os.replace`` raises ``PermissionError`` (WinError 5) on Windows when
        another handle still holds the destination open -- which is exactly
        what happens when two gateway instances put the same blob while a
        reader is already serving it. If the destination already holds this
        exact content, another writer won the race and the put is complete;
        otherwise retry briefly, then surface the error.
        """
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, data_path)
                return
            except PermissionError:
                if self._content_matches(data_path, data):
                    self._discard(tmp_path)
                    return
                if attempt + 1 == _REPLACE_ATTEMPTS:
                    raise
                time.sleep(_REPLACE_BACKOFF_SECONDS * (attempt + 1))

    @staticmethod
    def _content_matches(path: Path, data: bytes) -> bool:
        try:
            return path.read_bytes() == data
        except OSError:
            return False

    @staticmethod
    def _discard(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass

    def _write_meta(self, ref: BlobRef, meta_path: Path, thread_id: str | None) -> None:
        payload = {
            "sha256": ref.sha256,
            "size": ref.size,
            "kind": ref.kind,
            "content_type": ref.content_type,
            # Advisory provenance only: the first writer of this content. It is
            # deliberately not a "threads that reference this" list -- identical
            # bytes dedupe to one file, and appending to a sidecar from two
            # gateway instances is a lost-update race, so such a list could not
            # be trusted as a reference count anyway.
            "writer_thread_id": thread_id,
            "created_at": time.time(),
        }
        fd, tmp_name = tempfile.mkstemp(prefix=".meta-", suffix=".tmp", dir=meta_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            os.replace(tmp_name, meta_path)
        except OSError:
            # The sidecar is an optimization for later GC, not a read
            # dependency: losing it must not fail a put that already
            # succeeded.
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            logger.warning("Could not write blob sidecar %s", meta_path, exc_info=True)


__all__ = ["LocalFsBlobStore"]
