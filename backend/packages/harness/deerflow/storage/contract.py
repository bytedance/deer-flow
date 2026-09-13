"""Content-addressed blob store contract.

A :class:`BlobRef` addresses **content**, not a location. That is the whole
point of the abstraction: on a multi-gateway deployment a server-local
filesystem path is only meaningful on the instance that wrote the file,
whereas a content digest is meaningful everywhere -- every instance that can
reach the backing store resolves the same bytes.

Producers (issue #4189, item 2):

* ``ViewedImageData.actual_path`` -- written by ``view_image_tool``, read by
  ``ViewImageMiddleware``, the gateway artifact routes and the IM channels.
* Oversized tool results externalized by ``ToolOutputBudgetMiddleware``.

Both keep their existing local path when the store is disabled, so the seam is
purely additive.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Blob kinds are also filesystem path segments in the local_fs backend, so the
# grammar is deliberately narrow: lowercase, digits and hyphens, no leading or
# trailing hyphen, 1-64 chars. That rules out traversal (".."), separators and
# case-sensitivity surprises on NTFS/APFS at the contract level instead of
# leaving every backend to re-check it.
_KIND_PATTERN = re.compile(r"^(?=.{1,64}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
# The grammar as a caller sees it. One text, one place: this message is the only
# thing a producer gets when a kind is rejected, and a second copy of the
# pattern (the local_fs backend had one) drifts from the enforced one.
_KIND_GRAMMAR = "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ (1-64 chars, no leading or trailing hyphen)"


def is_valid_blob_kind(kind: str) -> bool:
    """Return whether *kind* is a safe blob-kind identifier."""
    return isinstance(kind, str) and bool(_KIND_PATTERN.match(kind))


def validate_blob_kind(kind: str) -> str:
    """Return *kind* unchanged, or raise ``ValueError`` quoting the real grammar.

    Backends must not re-implement the pattern: a store that rejects a kind the
    contract accepts -- or accepts one it rejects -- makes content addressable
    on one backend and not another.
    """
    if not is_valid_blob_kind(kind):
        raise ValueError(f"kind must match {_KIND_GRAMMAR} (it is used as a path segment)")
    return kind


class BlobStoreError(RuntimeError):
    """Backend-neutral base error exposed at the blob store boundary."""


class BlobNotConfiguredError(BlobStoreError):
    """A caller required a blob store but ``blob_storage.enabled`` is False."""


class BlobWriteError(BlobStoreError):
    """A write failed after retries; the content was not persisted."""


class BlobReadError(BlobStoreError):
    """A read failed for a reason other than the blob being absent."""


class BlobNotFoundError(BlobReadError):
    """The referenced content is not present in the backing store."""


class BlobRef(BaseModel):
    """A content-addressed reference to blob bytes.

    ``sha256`` is the address: writes are idempotent (putting the same bytes
    twice yields the same ref) and deduplication is free. ``size`` is carried
    so a reader can sanity-check what it got back without trusting the
    backend, and ``kind`` scopes garbage collection -- retention sweeps can
    reason about a kind ("externalized tool outputs for thread X") without
    parsing paths.
    """

    model_config = ConfigDict(frozen=True)

    sha256: str = Field(description="Lowercase hex SHA-256 of the blob content (64 chars).")
    size: int = Field(ge=0, description="Content length in bytes.")
    kind: str = Field(description="Content class, e.g. 'viewed-image' or 'tool-output'.")
    content_type: str | None = Field(default=None, description="MIME type when the producer knows it.")

    @field_validator("sha256")
    @classmethod
    def _sha256_is_hex64(cls, value: str) -> str:
        value = (value or "").strip().lower()
        if len(value) != 64 or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value

    @field_validator("kind")
    @classmethod
    def _kind_is_safe(cls, value: str) -> str:
        return validate_blob_kind(value)

    def matches(self, data: bytes) -> bool:
        """Return whether *data* really is this blob's content."""
        import hashlib

        return len(data) == self.size and hashlib.sha256(data).hexdigest() == self.sha256


class BlobStore(ABC):
    """Backend-neutral blob store contract.

    A plain ABC (like ``MemoryStorage``, not the pydantic ``MemoryManager``):
    the contract carries no config fields, so there is nothing for pydantic to
    validate and no ``PrivateAttr`` ceremony. Backends are constructed by the
    factory through :meth:`from_config`.

    Portability rule (mirrors the memory backends' golden rule): a backend
    talks to the host through exactly two channels -- the method arguments and
    the ``backend_config`` dict. The only ``deerflow`` import a backend folder
    needs is the contract line importing :class:`BlobStore`.
    """

    #: Sentinel attribute each backend package's ``__init__`` exposes so the
    #: folder-scan factory can find it (mirrors memory's ``MANAGER_CLASS``).
    STORE_CLASS_ATTR: ClassVar[str] = "STORE_CLASS"

    @classmethod
    @abstractmethod
    def from_config(cls, backend_config: dict[str, Any]) -> BlobStore:
        """Build a store from backend-private config.

        ``backend_config`` is the dict from ``blob_storage.backend_config``,
        with ``root`` injected by the factory when the host did not set one.
        Must raise on an unusable config -- a blob store that silently starts
        on the wrong root is worse than one that refuses to start.
        """

    @abstractmethod
    def put_bytes(
        self,
        data: bytes,
        *,
        kind: str,
        content_type: str | None = None,
        thread_id: str | None = None,
    ) -> BlobRef:
        """Persist *data* and return its :class:`BlobRef`.

        Idempotent: putting identical bytes twice returns the same ref and must
        not duplicate storage.

        ``thread_id`` is **advisory provenance, never a reference count.**
        Content addressing means identical bytes collapse to one object, so two
        threads that externalize the same content share it, and a backend can
        only record whichever writer reached it first -- on a multi-instance
        deployment it cannot even do that reliably, since two gateway instances
        appending to one sidecar is a read-modify-write race that loses entries.
        Garbage collection must therefore establish liveness from the durable
        references (the checkpoint rows that name the blob), not from this
        field; see ``docs/blob-storage.md`` for the exact rule.
        """

    @abstractmethod
    def get_bytes(self, ref: BlobRef) -> bytes:
        """Return the content addressed by *ref*.

        Raises :class:`BlobNotFoundError` when the content is absent and
        :class:`BlobReadError` when it is present but unreadable. Backends
        SHOULD verify the digest on read: a content-addressed store that
        silently returns wrong bytes is indistinguishable from a corrupt
        checkpoint.
        """

    def exists(self, ref: BlobRef) -> bool:
        """Return whether *ref* is present. Default probes via :meth:`get_bytes`."""
        try:
            self.get_bytes(ref)
        except BlobNotFoundError:
            return False
        return True

    def delete(self, ref: BlobRef) -> None:
        """Remove the content addressed by *ref*.

        Default raises so a backend that cannot delete says so instead of
        leaving a caller to assume a sweep succeeded. Deleting an absent blob
        is not an error (idempotent), matching how the retention contract
        treats orphans.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support delete")

    def close(self) -> None:  # noqa: B027 - intentional no-op default
        """Release backend resources. Default: nothing to release."""
