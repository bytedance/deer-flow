# Blob storage (content-addressed, cross-instance)

Resolves the multi-instance half of [#4189](https://github.com/bytedance/deer-flow/issues/4189) item 2: two producers persist blob-shaped data outside the checkpoint payload and address it with a **server-local filesystem path**, which only resolves on the instance that wrote it.

| Producer | Write | Reads |
|---|---|---|
| Viewed images | `view_image_tool` → `ViewedImageData.actual_path` (`deerflow/agents/thread_state.py:52`) | `ViewImageMiddleware._read_image_as_data_url`, gateway artifact routes, IM channels, `present_file_tool` |
| Externalized tool results | `ToolOutputBudgetMiddleware._externalize` → virtual path under the thread `outputs` tree | model `read_file` via the thread-data mount |

On a single gateway both are correct. Behind a load balancer, the instance handling the read is frequently not the instance that wrote the file. The blob store replaces **"where on this machine"** with **"which content"**, so every instance that can reach the backing store resolves the same bytes.

## Contract

`deerflow/storage/contract.py`

- `BlobRef` — `{sha256, size, kind, content_type}`. The digest is the address, so writes are idempotent and dedup is free.
- `BlobStore` — plain ABC, tiered like `MemoryStorage`:
  - **abstract** — `put_bytes(data, *, kind, content_type=None, thread_id=None) -> BlobRef` (`thread_id` is advisory provenance, see the deletion rule below), `get_bytes(ref) -> bytes`
  - **default** — `exists` (probes via `get_bytes`), `delete` (raises; deleting an absent blob is not an error), `close`
- Errors — `BlobStoreError` → `BlobNotConfiguredError` / `BlobWriteError` / `BlobReadError` → `BlobNotFoundError`. A failed `delete` raises the neutral base `BlobStoreError`, not a read error.

Reads **verify the digest**. A content-addressed store that silently returns wrong bytes is indistinguishable from a corrupt checkpoint, so it fails loudly instead.

`kind` is validated by `validate_blob_kind` against `^[a-z0-9]([a-z0-9-]*[a-z0-9])?$` (1-64 chars, no leading or trailing hyphen) at the contract level because it is also a path segment in the `local_fs` backend — traversal and separator surprises are ruled out once, not per backend, and the single validator is what a rejected producer sees.

## Backend

`deerflow/storage/backends/local_fs/` (default)

```
<root>/<kind>/<sha256[:2]>/<sha256>          the bytes
<root>/<kind>/<sha256[:2]>/<sha256>.json     sidecar: content_type, writer_thread_id, created_at
```

- Writes go to a unique temp file in the destination directory then `os.replace` — atomic within a volume, so a concurrent reader never sees a partial file and two instances racing the same blob converge on identical content.
- The sidecar is GC metadata, **not a read dependency and not a reference count**: losing it must not make content unreadable, and `writer_thread_id` is advisory provenance that cannot stand in for liveness (see the deletion rule above).

This backend already delivers multi-instance resolution when `root` points at a shared volume (NFS / EFS / a `ReadWriteMany` PVC). The S3/MinIO backend is a later, optional extra implementing the same contract — it is deliberately not part of this change, because it needs a dependency decision (`[tool.uv.sources]`, optional extra) that belongs in its own PR.

## Configuration

```yaml
blob_storage:
  enabled: true                # default false
  backend: local_fs            # folder name under storage/backends/, or a dotted import path
  backend_config:
    root: /mnt/shared/deerflow-blobs   # default: {runtime_home}/blobs, absolute
```

Fail-fast on an unresolvable backend (`ValueError`), mirroring `MemoryConfig.manager_class`: blobs are persistent state, so silently substituting a different backend would strand previously written content.

## What this PR deliberately does not do

**No producer is migrated.** `blob_storage.enabled` defaults to `false`, no existing call site changed, and the diff is purely additive — a deployment that never sets the key behaves exactly as before.

Migration happens in two follow-up PRs, each independently revertible:

1. **Viewed images.** `ViewedImageData` gains an optional `blob_ref` (`actual_path` is kept); `view_image_tool` writes the blob when the store is enabled; `ViewImageMiddleware._read_image_as_data_url` resolves blob-first, path-second. The gateway artifact routes and IM channels keep their local-path reads until they can be exercised against a multi-instance deployment.
2. **Externalized tool results.** `ToolOutputBudgetMiddleware._externalize` records a ref alongside the virtual path; the sandbox variant (`_externalize_to_sandbox`, issue #3416) stays as-is — sandbox-resident content is a different failure mode one layer down.

## Interaction with checkpoint retention (#5255)

Blobs are content-addressed, and `kind` plus the sidecar's `writer_thread_id`
make a sweep *addressable* by kind and thread. That is the whole claim this seam
supports — it is **not** that retention can stop reasoning about references:

> **Deletion rule.** A blob may be unlinked only after confirming that no
> surviving durable reference names it. `kind` / `writer_thread_id` narrow the
> candidate set; on their own they are never sufficient.

The narrower rule is the honest one, because identical content collapses to one
object. Two threads that externalize the same bytes share a single file, and the
sidecar can only record whichever writer landed first (`writer_thread_id` is set
by the first write; the idempotent path does not rewrite it). Concretely: thread
A and thread B both view the same uploaded image — same bytes, same sha256, one
file under `viewed-image/`. A sweep for A that trusted the sidecar would delete
bytes B still references, and B's own sweep would never see the blob at all,
because the sidecar names A.

Recording *every* writer thread id would not repair that. Appending to one
sidecar from two gateway instances is a read-modify-write race with lost
updates, so the list could be missing precisely the writer that still needs the
content — and a reference count that is wrong under concurrency is worse than
none. Hence the contract states the liveness rule instead of a refcount.

What this means for the two migration PRs:

- **Viewed images** — an image is shareable by construction (any two threads can
  upload the same bytes), so the sweep must check liveness against the
  checkpoint references before unlinking; `kind` and `writer_thread_id` bound
  the search.
- **Externalized tool results** — per-thread by construction, so a thread-scoped
  sweep is safe while that remains true; `kind` is what makes the "while"
  checkable.

This is also the seam [#5188](https://github.com/bytedance/deer-flow/issues/5188) needs: a thread-scoped blob sweep keyed by thread incarnation, rather than by the reusable thread id.

## Adding a backend

`packages/harness/deerflow/storage/AGENTS.md` owns the depth — the drop-in
folder contract, the portability rule and the durability rules a new backend has
to keep. In short:

1. Copy `backends/local_fs/` to `backends/<name>/`.
2. Implement `from_config` + `put_bytes` + `get_bytes`; override `delete` if you can support it.
3. Export `STORE_CLASS = <YourStore>` from `backends/<name>/__init__.py`.
4. Set `blob_storage.backend: <name>`; backend knobs go under `blob_storage.backend_config`.

If the backend needs external libs (boto3, minio), declare them in `packages/harness/pyproject.toml` with `[tool.uv.sources]` — otherwise `uv sync` purges them.
