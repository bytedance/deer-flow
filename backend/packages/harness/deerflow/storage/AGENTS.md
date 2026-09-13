### Blob Store (`packages/harness/deerflow/storage/`)

**What it owns**: a content-addressed store for bytes that must resolve on every
instance, not just the one that wrote them (issue #4189, item 2). The address is
the SHA-256 of the content, so writes are idempotent, deduplication is free, and
a reader can verify what it got back. Contract: `storage/contract.py`
(`BlobRef`, `BlobStore`, the `BlobStoreError` family, `validate_blob_kind`).
Operator-facing behaviour and the producer migration plan: `docs/blob-storage.md`.
Factory: `storage/manager.py`.

**Disabled by default**: `blob_storage.enabled` is `false`, and no producer has
been migrated, so an untouched deployment behaves exactly as before. Producers
call `get_blob_store_if_enabled()` and keep their existing local-path code for the
`None` case; only a caller that genuinely requires the store uses
`get_blob_store()`, which raises `BlobNotConfiguredError` when it is disabled.
Both accessors are exported from this package — prefer
`from deerflow.storage import ...` over reaching into submodules.

**Layout** (local_fs, the default)::

    <root>/<kind>/<sha256[:2]>/<sha256>          the bytes
    <root>/<kind>/<sha256[:2]>/<sha256>.json     sidecar metadata

The sidecar holds what the bytes cannot say (`content_type`,
`writer_thread_id`, `created_at`). It is **not** a reference count and reads must
not depend on it: losing it cannot make content unreadable.

**Adding a backend** — the memory backends' drop-in contract, folder name ==
backend name == `blob_storage.backend` value:

1. Create `storage/backends/<name>/` with an `__init__.py` that exposes
   `STORE_CLASS = <YourStore>`; the factory discovers backends by scanning that
   folder, so no registry edit is needed.
2. Subclass `BlobStore` and implement `from_config`, `put_bytes`, `get_bytes`;
   `exists` / `delete` / `close` have working defaults (`delete` raises so a
   backend that cannot delete says so). Verify the digest on read — a store that
   silently returns wrong bytes is indistinguishable from a corrupt checkpoint.
3. Keep the portability rule: a backend talks to the host through the method
   arguments and its `backend_config` dict only. The single `deerflow` import a
   backend folder needs is the contract line importing `BlobStore`, so a
   third-party backend can live outside this tree and be selected with a dotted
   path (`pkg.mod.Class` or `pkg.mod:Class`).
4. Reject an unusable config by raising; a store that silently starts on a
   different root or backend strands previously written content.
5. Add the backend's semantics tests to `backend/tests/test_blob_store.py`; the
   suite runs every backend-agnostic scenario against a temporary root.

**Durability rules that reviewers have enforced**, worth keeping intact:

- Validate the `kind` through `validate_blob_kind` instead of re-implementing the
  grammar; it is also a path segment in `local_fs`, so traversal and separator
  surprises are ruled out once, at the contract level.
- Publish atomically and tolerate a concurrent writer: two gateway instances may
  put the same content at the same time (see `LocalFsBlobStore._publish`, which
  handles the Windows `os.replace`/`WinError 5` case by recognising that the
  destination already holds this content).
- Fail fast on an unresolvable backend: `_resolve_store_class` raises rather than
  substituting a default, because blobs are persistent state.

**Garbage collection is not this module's job.** A blob row may be referenced by
several threads once identical content dedupes, so a sweep must establish
liveness from the durable references (the checkpoint rows that name the blob) and
never from the sidecar's `writer_thread_id`. The exact rule, and how it composes
with the checkpoint retention contract (#5255), is stated in
`docs/blob-storage.md`.

**Entry points**: `packages/harness/deerflow/storage/contract.py`,
`storage/manager.py`, `storage/backends/local_fs/local_fs_store.py`,
`config/blob_storage_config.py`; tests in `backend/tests/test_blob_store.py`.
