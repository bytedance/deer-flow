# Blob store (`deerflow/storage/`)

A content-addressed store for bytes that every instance must be able to read, not
only the instance that wrote them. The address is the SHA-256 of the content.
Operator behavior, the producer migration plan and the garbage-collection rule:
[blob storage](../../../../docs/blob-storage.md).

## Verify

```bash
cd backend
python -m pytest tests/test_blob_store.py -q
make test-blocking-io
```

A new backend adds its tests to `tests/test_blob_store.py`, which runs the
backend-independent scenarios against a temporary root.

## Using the store

- **The store is disabled by default.** A producer calls
  `get_blob_store_if_enabled()` and keeps its local-path code for `None`. Only a
  caller that cannot work without the store calls `get_blob_store()`.
- **A store failure is a failed operation, not a silent downgrade.** A producer
  that could not write does not claim that the content is readable on another
  instance. A reader tries the blob first and keeps the local path as a
  fallback.
- **Validate a checkpointed ref before you read or write with it.** Its kind,
  digest, size and content type must agree with the metadata that was recorded
  separately.
- **A fallback read through an HTTP route stays inside the authorized thread and
  the exact virtual path**, and verifies the bytes before it serves them.
- **Changing the root needs a plan.** Existing refs must stay readable, and every
  instance must change together.

## Backends

- **The folder name, the backend name and the `blob_storage.backend` value are
  the same string.** The factory finds a backend by scanning
  `storage/backends/`, through `STORE_CLASS` in its `__init__.py`.
- **A backend imports one thing from `deerflow`: the `BlobStore` contract.** It
  talks to the host through method arguments and its `backend_config` only, so a
  third-party backend can live outside this tree.
- **Verify the digest on read.** A store that returns wrong bytes cannot be told
  from a corrupt checkpoint.
- **Reject an unusable config, and fail on an unresolvable backend.** A store that
  starts on a different root or a default backend strands the content that was
  already written.
- **Validate `kind` through `validate_blob_kind`.** The kind is a path segment in
  `local_fs`, so the traversal check lives in one place.
- **Publish atomically, and accept a concurrent writer.** Two Gateways can put the
  same content at the same time.
- **The size limit belongs to the backend, not to the contract.** A producer of
  large payloads streams or splits them before `put_bytes`.

## Sidecar and garbage collection

- **The sidecar is metadata only.** It is not a reference count, and a read must
  not depend on it.
- **This module does not collect garbage.** Identical content is shared by several
  threads, so liveness comes from the checkpoint rows that name the blob, never
  from the sidecar's `writer_thread_id`.
