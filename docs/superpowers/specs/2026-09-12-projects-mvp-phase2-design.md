# DeerFlow Projects MVP — Phase 2 Design (Instructions, Documents, Promotion, Trash)

**Date**: 2026-09-12
**Status**: Draft for review (RFC v2, [issue #5160](https://github.com/bytedance/deer-flow/issues/5160))
**Phase**: Phase 2 of the Projects MVP. Phase 1 (organization) landed as #5265 (`cfda885c`..`e2f2afde`, merged 2026-09-08).
**Source of truth**: **This spec governs Phase 2 in full**, including where it differs from RFC v2 (`docs/plans/2026-09-06-projects-mvp-rfc-v2.md` / `.zh.md`) or the predecessor spec. The RFC is historical context; §10 explains significant departures and is not a prerequisite for this spec to take precedence. An omission is an open implementation detail to resolve against this spec, not an implicit import of an RFC requirement. Requirement tracker: [#5129](https://github.com/bytedance/deer-flow/issues/5129).
**Predecessor**: `docs/superpowers/specs/2026-09-06-projects-mvp-design.md` (§"Runtime Design (Phase 2)", §"Delete, Trash, and Archive Semantics" are **superseded** by §7/§8 here; the Phase-1 sections of that spec remain accurate).
**Pin**: every current-system claim below was re-verified against `main @ 0464502a` (2026-09-12) in this checkout.

---

## Problem Statement

Phase 1 gave a project three things it can hold: threads, a name, and a `status`. It gave it nothing it can *tell the agent* and nothing it can *hold as material*. Verified against `main @ 0464502a`:

- `projects.instructions` is stored, PATCHable and returned — and has **zero consumers**: `persistence/projects/model.py:6` says "Phase 1 stores and PATCHes it, Phase 2 injects it", and no read of `ProjectRow.instructions` exists outside `ProjectRepository`. A user who writes project background today is writing into a void.
- There is **no project document entity**: no `project_documents` table, no `users/{user_id}/projects/` filesystem layout, no `Paths` helper, no `trash_retention_days` config key, no `/api/trash/*`, no documents/from-thread/attach-to-thread/thread-files routes. The only textual trace of the design is a forward-looking comment at `persistence/projects/sql.py:6-9`.
- There is **no project awareness at run time**: exhaustive search for `project_id|deerflow_project_id|ProjectRow|ProjectRepository` under `deerflow/runtime/**` and `deerflow/agents/**` returns no matches; `runtime_ctx` is `{"thread_id", "run_id"}` plus caller keys (`runtime/runs/worker.py:542`). A run cannot learn which project it belongs to, so it cannot receive instructions or document access.
- Run admission **strips** the reserved `deerflow_project_id` key and never writes membership (`app/gateway/services.py:207-218`, pinned by `tests/test_thread_meta_repo.py:598-623`). Membership is written only by `POST /api/threads`, branch creation, and `POST /api/threads/{id}/move` (`app/gateway/AGENTS.md:13-19`).

The user-visible consequence: a project is a folder with a nice name. Member threads still re-acquire background by hand, and "the documents for this topic" still has no residence — the project page's Documents and Instructions sections do not exist (`frontend/src/app/workspace/projects/[id]/page.tsx:86-93` renders header + Chats + Settings only).

The project page, the sidebar, the move menu, and the reserved-key wire contract from Phase 1 have no Phase-2 gap: this spec consumes them rather than changing them.

## Solution Summary

Five deliverables, merged in the dependency order in §16:

1. **Bounded instructions injection.** Each model request receives only the current run's pinned project instructions in a user-role `<project>` block, never in the system prompt or persisted message history. Enforce the hard UTF-8 byte cap at write time (reject, never truncate).
2. **Latest project context on every run.** Resolve the current project once at admission, then render its identity/instructions and shelf index only in model requests. Rename, edit, move and move-out take effect on the next run without a correction chain or history comparison. Hashes are audit fingerprints only.
3. **A project document shelf.** `project_documents` plus immutable, hash-qualified storage with a separate namespace per document row (§6.2), direct upload, listing, preview/download, active-content dedup, and move-to-trash. A derived markdown artifact is cached for the lifetime of its owning document's immutable original.
4. **Bounded, lazy document access for member threads.** A capped request-scoped `<documents>` index provides IDs for discovery; `list_project_documents` / `read_project_document` serve content on demand from the host-side store through the run's pinned project identity. No document content is bulk-injected; trashed rows are invisible to all three surfaces.
5. **Promotion both ways plus a trash tier.** Save to project (thread file → shelf, copy with provenance), attach to thread (shelf → thread uploads, engaging the existing `<current_uploads>` path), a read-only aggregated member-thread file view, and recoverable deletion: document delete and project delete move rows to trash; permanent purge is a separate, separately confirmed action with its own endpoints, retention window, and ordering rules.

## Explicit Non-Goals

These are Phase-2 scope decisions, not polish cuts. Reintroducing any of them requires maintainer agreement in #5160 first.

1. **Project-scoped memory** — extraction, read modes, per-mode write routing. Phase 3 (§17 of the RFC). No `memory_mode` column, no memory read/write changes, no memory-API `scope` parameter.
2. **Agent-initiated shelf writes.** The shelf is user-curated. The tools are read-only; there is no `write_project_document`.
3. **Full-text shelf search.** Deferred until usage justifies an index.
4. **Automatic promotion** of every thread file onto the shelf.
5. **Binary content delivery into model context.** `read_project_document` serves text and converted-text only; binaries are declined with an error that points at attach-to-thread.
6. **A project-level sandbox mount for documents.** Remote providers derive sandbox identity from `(user_id, thread_id)`; harness tools keep the feature provider-agnostic.
7. **Cross-project document sharing/copying between projects.** Restore requires *an* active target project and may reassign a trashed document to it, but each document belongs to one project; there is no "copy document to another project" action.
8. **Batch upload UI semantics beyond one file per request** (§6.5); multi-file batching can follow usage.
9. **Versioning/snapshots of shelf documents.** Re-uploading changed content creates a new content address; the old row is whatever the user did with it (trash or nothing). No history, no diffs.
10. **A new RunJournal event type** (§10.5 keeps the existing `context:memory` event and adds project fingerprint payload fields).

## Chosen Architecture

### Principles carried from Phase 1 (unchanged)

- **Project is a metadata container**, not a sandbox boundary; membership changes remain organizational.
- **Stable surrogate identity**: `projects.id` is an immutable uuid4 hex.
- **Server-verified membership**: the server derives a run's project from `threads_meta`; clients never supply project identity at run time.
- **Check-and-set, not check-then-act**: existence/ownership/status validation happens inside the mutating statement or one transaction, under the same `projects` row lock Phase 1 established.
- **No dormant schema**: every column added here has a named consumer in §6/§7/§8.

### Phase-2-specific decisions (the ones a reviewer should attack first)

1. **Preserve role authority.** Framework-owned date/rules remain in SystemMessages; user-authored instructions and document names use a separate request-scoped HumanMessage (§7.2). The existing date/memory messages and their persistence behavior stay unchanged. No project revision is stored on their SystemMessages.
2. **One resolution per run, pinned.** The gateway resolves thread → project → snapshot once, at admission, and writes it into the run context as a server-owned key. Middleware does pure string work from the pinned snapshot; the document tools read the pinned `project_id` and then query live shelf rows. A mid-run move or shelf change cannot mix contexts inside a run.
3. **Immutable shelf files with exclusive row ownership.** `stored_relpath` embeds both `sha256` and a fresh document ID; different rows never share an original or derived-file path. A path's bytes never change. Consequences the design leans on: dedup is a pure function of content; a converted-markdown companion never needs invalidation; a restore re-points a row **without moving any file** (§10.6) because the relative path stays valid.
4. **Fail closed, degrade loudly.** A run without a project gets no project context and the tools refuse. A resolution failure degrades to "unassigned" with a warning rather than failing the run — the same shape admission already uses for thread metadata (`services.py:1477-1490`).
5. **The prompt stays static.** No project data enters `SYSTEM_PROMPT_TEMPLATE` (`agents/lead_agent/prompt.py:541`); only the trust declaration's *wording* changes (§7.2), because it currently describes a message shape the code no longer produces (§10.1).

## User Stories

1. As a user, I write project instructions once and every member thread's agent knows them — without me pasting them again.
2. As a user, I rename a project or edit its instructions and my *existing* conversations pick up the change on their next run.
3. As a user, I upload reference material at the project level and the agent finds and reads it on demand, without the whole shelf landing in every prompt.
4. As a user, I save a good output from one thread onto the project shelf with its origin visible, instead of downloading and re-uploading it.
5. As a user, I attach a shelf document into one thread so the agent can edit or process it through the normal uploads path.
6. As a user, I browse every file my project's threads have produced, from one place, without those files becoming shelf entries.
7. As a user, deleting a document or a project is recoverable for a retention window; permanent deletion is a separate, confirmed action.
8. As a user, moving a thread into a project gives its agent the project's instructions on the next run; moving it out retracts them.
9. As a maintainer, I can land instructions injection before documents, then shelf storage with its required trash transitions, and later the restore/purge UI. Each slice is usable with its prerequisites; rollback follows reverse dependency order (§16).

## Backend Design

### 6.1 Persistence

`persistence/projects/model.py` gains `ProjectDocumentRow`; `persistence/projects/sql.py` gains `ProjectDocumentRepository` (same docstring discipline as the existing `ProjectRow`/`ProjectRepository`).

| column | type | index / nullable | consumer |
| --- | --- | --- | --- |
| `id` | `String(64)` PK | — | every route/tool |
| `project_id` | `String(64)` | index | shelf listing, project-delete statement |
| `user_id` | `String(64)` | index | fail-closed owner filter |
| `name` | `String(255)` | — | shelf index, tool output (byte cap mirrors `_MAX_FILENAME_BYTES` in `uploads/manager.py:32`) |
| `stored_relpath` | `String` | — | resolved under `users/{user_id}/projects/` (§6.2) |
| `sha256` | `String(64)` | index | dedup key, content address |
| `size_bytes` | `Integer` | — | shelf display |
| `source_thread_id` | `String(64)` | nullable | promotion provenance |
| `source_kind` | `String(16)` | nullable | `upload` \| `output` |
| `source_name` | `String(255)` | nullable | original name inside the thread |
| `trashed_at` | `DateTime(tz)` | nullable, index | trash list, live/trashed split in every query |
| `trash_origin` | `JSON` | nullable | `{project_id, project_name}` snapshot for display + restore hint |
| `created_at` / `updated_at` | `DateTime(tz)` | — | shelf "modified" display; index ordering |

No `mime`, no `is_text`, no `version`, no `deleted_by`: text detection is a sampled read (§7.3), and the shelf has no history by design.

Repository surface (all methods ContextVar-owner-filtered, `AUTO` sentinel as in `ProjectRepository`):

- `insert_active(project_id, *, document_id, name, relpath, sha256, size_bytes, source_thread_id=None, source_kind=None, source_name=None) -> dict | None` — locks the `projects` row (`status='active'`, owner-scoped, `with_for_update()`) inside the transaction; `None` when the project is missing/foreign/archived.
- `find_active_by_sha256(project_id, sha256) -> dict | None` — dedup hit.
- `list_active(project_id, *, limit, offset) -> list[dict]` — `ORDER BY updated_at DESC, id ASC`.
- `count_active(project_id) -> int` and `shelf_snapshot(project_id, *, limit) -> (rows, total)` — feeds §7.1's pinned index in one round trip.
- `get(document_id, *, include_trashed=False) -> dict | None`.
- `trash(document_id) -> bool` — lock the owned active project, then the owned document; guarded `UPDATE … SET trashed_at=:now, trash_origin=:json WHERE id=:id AND user_id=:uid AND project_id=:pid AND trashed_at IS NULL`; `False` ⇒ 404. Archived shelves reject this write.
- `trash_all_for_project(project_id, *, project_name)` → executed inside `ProjectRepository.delete`'s transaction (§8.1).
- `list_trashed(*, limit, offset) -> list[dict]`.
- `list_all_trashed() -> list[dict]` — every trashed row of the caller, oldest first; the age-independent selection Empty trash drives through `purge` (§8.3), revalidating each row's trashed state under the purge lock so a concurrently restored row is skipped.
- `restore(document_id, *, target_project_id) -> tuple[str, dict | None]` — outcome enum as `Literal["restored", "merged", "not_found", "no_target", "content_missing"]`; database re-point plus a read-only original-file check under the document lock (§10.6).
- `purge_candidates(retention_days) -> list[dict]` — trashed rows older than the window.
- `purge(document_id, *, retention_cutoff=None, expected_trashed_at=None) -> bool` — owns the transaction and document-row lock across trashed-state validation, file removal, row deletion and commit (§6.3/§8.3); `False` ⇒ 404. Retention callers pass the selected trash timestamp and cutoff; both are revalidated under the lock, so a candidate restored and later re-trashed is not purged using its former expiry. Manual purge validates the current trashed state without an age requirement. No public unguarded `delete_row` mutation.

Migration `0024_project_documents` (renumbered from `0023` after rebasing onto `0023_user_preferences`; chain head today is `0023_user_preferences`, `migrations/AGENTS.md:22-30`): create the table + four indexes with `op.create_table`; guard with the existing `inspector.has_table` idiom the way `0019_projects.py:22-23` does. The bootstrap forward-compat floor (`persistence/bootstrap.py:133-171`) needs **no** change: `project_documents` is a new table, and old binaries treat the floor as a presence check, never deriving it from `Base.metadata`. The head pin in `tests/test_persistence_forward_revision_compat.py` must move to the new head (`0024_project_documents`).

### 6.2 Filesystem layout

```
users/{user_id}/projects/{project_id}/documents/
  .staging/{uuid}                       # in-flight upload/promote bytes
  {sha256[:2]}/{sha256}/{document_id}/
    original/{name}                    # immutable original, filename <=255 UTF-8 bytes
    derived/converted.md               # optional conversion; separate namespace
```

`stored_relpath` is stored **relative to `users/{user_id}/projects/`** — i.e. it begins with `{project_id}/documents/`. That decision makes restore independent of file moves (§10.6) and keeps every read confinement check identical to `Paths.resolve_virtual_path`'s pattern (`config/paths.py:446-484`): resolve, then assert `resolved.relative_to(users/{user_id}/projects/)`.

Each new row receives a fresh server-generated uuid4-hex `document_id` before final placement; IDs and storage namespaces are never reused. Dedup is a database decision among active `(project_id, sha256)` rows, not physical sharing. A dedup hit returns the existing row without publishing another file. Re-upload after trash gets a new row and a distinct path even for identical bytes and name. Restore keeps its namespace; merge cleanup deletes only the discarded row's namespace. The display filename occupies its own path component (no hash prefix or `.md` suffix), so the accepted 255-byte filename remains valid on supported filesystems. Conversion detects type from the original filename extension and writes `derived/converted.md` via a temporary file and atomic rename, serialized per document.

New `Paths` helpers, mirroring `thread_dir`/`sandbox_uploads_dir` (`config/paths.py:310-351`) including `_validate_user_id`-style safe-id checks on `project_id`:

- `user_projects_dir(user_id) -> Path`
- `user_project_dir(user_id, project_id) -> Path`
- `project_documents_dir(user_id, project_id) -> Path`
- `project_document_path(user_id, relpath) -> Path` — joins under `user_projects_dir` and re-checks confinement.

### 6.3 Atomicity rules (Phase 2)

Phase 1 implemented check-and-set as "take the `projects` row lock inside the write transaction" (SQLite `BEGIN IMMEDIATE` + `SELECT … WHERE id/user_id/status='active' FOR UPDATE`; `persistence/thread_meta/sql.py:57-79, 126-161`). Phase 2 reuses that idiom rather than inventing a second one:

- **Shelf insert (upload / promote):** stage and hash bytes, allocate a fresh document ID, then one transaction — lock active owned project row → dedup `SELECT` among active `(project_id, sha256)` rows → on a miss, atomically place bytes in that document's exclusive namespace → `INSERT` → commit. A hit removes staging and returns the existing row. Placement precedes insert (§10.3); failed inserts clean up only their own namespace best-effort, with crash leftovers collected after 24 hours.
- **Attach-to-thread:** lock and validate the owned live source document, stage a stable copy, then invoke the shared thread-upload ingestion service (§7.3), which validates the target and owns filename allocation, conversion, permissions and sandbox synchronization. Archived source projects permit this read.
- **Trash:** lock the owned active project row, then the owned document row in the same transaction; guarded `UPDATE` with `trashed_at IS NULL`; missing/archived project or `rowcount = 0` ⇒ 404.
- **Restore:** one transaction — lock the target active owned project row, then identify the source and any merge-candidate rows and lock them in ID order; revalidate source ownership and `trashed_at IS NOT NULL` after locking; either merge into an active row with the same `sha256` or clear trash fields and re-point `project_id`. Missing/already restored/purged source ⇒ 404. Before either outcome, check original existence/size under the source lock; `content_missing` leaves the source trashed. Merge additionally verifies the surviving target content under its document lock. No file mutation inside the restore transaction; discarded-source cleanup follows commit.
- **Project delete:** the §8.1 three statements inside the existing transaction, under the same project row lock `ProjectRepository.delete` already takes (`persistence/projects/sql.py:159-176`).
- **Purge:** one database transaction holds the owned document row lock continuously across `SELECT … WHERE trashed_at IS NOT NULL` → unlink original and derived file → delete row → commit. Restore cannot pass its source-row lock meanwhile. Filesystem operations are not rollbackable; other unlink failures roll back the database mutation and retain a retryable trashed row. `FileNotFoundError` counts as already removed (§8.3). SQLite uses `BEGIN IMMEDIATE`.
- **Lock order:** operations needing a project lock acquire it before document locks; multiple document locks use ID order. Project deletion locks affected document rows in ID order before its bulk update. Purge acquires only its document lock and never later waits for a project lock. All restore, trash, conversion and purge paths honor document serialization; conversion revalidates active state after locking and cannot publish a derived file after purge.

### 6.4 Configuration

New `config/projects_config.py` following the `read_before_write_config.py` shape (typed Pydantic model + `Field(...)` bounds), plus an `AppConfig.projects` field (`config/app_config.py:185-262`) and a `projects:` block in `config.example.yaml`:

| key | default | bounds | consumer |
| --- | --- | --- | --- |
| `instructions_max_bytes` | `8192` | `ge=256, le=262144` | write-time 422 (§6.5) |
| `shelf_index_max_entries` | `50` | `ge=1, le=500` | §7.1 index render |
| `shelf_index_max_bytes` | `4096` | `ge=512, le=65536` | §7.1 index render |
| `trash_retention_days` | `30` | `ge=1, le=3650` | §8.3 sweep |

Shelf document size limits **reuse** the thread-upload limits (`uploads.max_file_size`, default 50 MiB; `routers/uploads.py:45-47, 163-168`) rather than introducing a second knob with the same meaning. `uploads.auto_convert_documents` keeps its meaning and is honored by `read_project_document`'s conversion path (§7.3): when disabled, a convertible file is declined with a clear error instead of converted.

### 6.5 Gateway API

Three new routers, mounted in `app.py:create_app` beside `projects.router` (`app.py:836`):

`routers/project_documents.py` — `APIRouter(prefix="/api/projects/{project_id}/documents", tags=["project-documents"])`:

| method + path | body / query | response | permission |
| --- | --- | --- | --- |
| `GET ""` | `limit` (default 100, 1..1000), `offset` | `ProjectDocumentListResponse` | `projects:read` |
| `POST ""` | multipart, **exactly one file** + optional `name` | `ProjectDocumentUploadResponse` (`201` created / `200` dedup hit) | `projects:write` |
| `POST "/from-thread"` | `{thread_id, kind: "upload"\|"output", name, shelf_name?: str}` | same as upload | `projects:write` + `threads:read` |
| `POST "/{document_id}/attach-to-thread/{thread_id}"` | — | `{filename, size_bytes, virtual_path, artifact_url}` | `projects:write` + `threads:write` |
| `GET "/{document_id}/content"` | `download: bool = false` | inline text or attachment | `projects:read` |
| `DELETE "/{document_id}"` | — | `204` (moved to trash) | `projects:delete` |

`routers/project_thread_files.py` — `APIRouter(prefix="/api/projects/{project_id}/thread-files")`:

| method + path | query | response | permission |
| --- | --- | --- | --- |
| `GET ""` | `offset` (member-thread cursor), `thread_limit` (default 20, 1..50), `file_limit` (default 50, 1..200) | `ThreadFilesResponse` | `projects:read` + `threads:read` |

`routers/trash.py` — `APIRouter(prefix="/api/trash", tags=["trash"])`:

| method + path | body / query | response | permission |
| --- | --- | --- | --- |
| `GET "/documents"` | `limit`, `offset` | `TrashListResponse` | `projects:read` |
| `POST "/documents/{document_id}/restore"` | `{project_id?: str}` | `RestoreResponse` (may report `merged`) | `projects:write` |
| `POST "/documents/{document_id}/purge"` | — | `204` | `projects:delete` |
| `POST "/purge"` | — | `{purged: int}` | `projects:delete` |

Request validation:

- `instructions` (existing `ProjectCreateRequest`/`ProjectPatchRequest` fields): rejected with **422** when `len(value.encode("utf-8")) > projects.instructions_max_bytes`. Truncation is a review blocker (§15).
- Upload `name`: optional; defaults to the multipart filename after `normalize_filename`; rejected on empty-after-normalize, path separators, or >255 UTF-8 bytes.
- `from-thread` `name`: required (the source file's name); `kind ∈ {upload, output}`; the source must resolve inside that thread's own uploads/outputs directory. Optional `shelf_name` defaults to the source name and follows upload-name validation.
- `restore` body: `project_id` optional; required only when the origin project no longer exists or is archived; an invalid/foreign/archived target ⇒ 404.
- Uploads accept **exactly one file per request** (§17.2): partial-failure semantics stay out of the response body, one request maps to at most one row (or one dedup hit), and the UI loops for multi-file drops.
- Pagination bounds follow the existing 422 convention (`routers/projects.py:143-157`).

Error mapping: 404 for missing/foreign resources on every route. Owned active and archived projects allow shelf listing, content/download, thread-files reads, run injection, and document tool reads. Upload/promote, restore targets, and individual document trash require an active project and return 404 for archived projects. Attach may read an archived source shelf into an owned writable thread; it does not mutate that shelf. Project deletion remains allowed under the Phase-1 contract. Resource lookup failures never expose existence via 403; **503 `"Projects"`** when the project repository is unavailable (memory backend) via the existing `deps.py:654` `_require` accessor, extended with a `project_document_repo` accessor; 413 for oversize uploads (mirroring `routers/uploads.py:320-321`); 422 for validation.

PAT default-deny: every new route must be added to the allowlist in `auth/pat.py` (`:59-68`) — the current rules cover only `/api/projects`, `/api/projects/{id}`, `archive|restore`, `/threads`, and `/threads/{id}/move`. `tests/test_pat_auth.py::test_pat_projects_policy_admits_exactly_the_mounted_routes` is the drift guard and must be extended with the new routes.

## Runtime Design

### 7.1 Run-context resolution and pinning

One async resolution per run, in the shared run-create path of `app/gateway/services.py` (the block around `:1455-1490`, after `inject_authenticated_user_context` and before `create_or_reject`):

1. Read `threads_meta.project_id` for `record.thread_id` through `run_ctx.thread_store`.
2. If it is non-NULL, load the project row (owner-scoped, `status IN ('active', 'archived')`; archived membership retains instructions and read-only shelf access) plus a **bounded** shelf snapshot: a count and the first `shelf_index_max_entries + 1` rows in `updated_at DESC, id ASC` order. The `+ 1` row exists only to decide whether the index is truncated; it is never rendered.

   Only the bounded render window and count enter runtime context, avoiding copies of unused full-shelf metadata. `shelf_hash` covers the final rendered index, not unshown rows, and is used only for audit. Shelf changes never trigger persisted corrections. Count and rows come from a consistent database snapshot; a subsequent tool call deliberately reads live rows and may differ after a concurrent mutation.
3. Build the pinned snapshot and write it under a new server-owned key:

```python
# deerflow/runtime/context_keys.py
PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"
```

```python
{
  "project_id": "…", "name": "…",
  "instructions": "…",
  "shelf": {"total": 7, "entries": [{"id","name","size_bytes","updated_at"}, …]},
  "shelf_hash": "<hex>"          # sha256 over the rendered index (see below)
}
```

4. Add `PROJECT_CONTEXT_KEY` to **both** server-owned sets so a client-supplied value can never survive: `services.py:435-446` (which pops it from `config["context"]` and `config["configurable"]` at `:586-591`) and the worker's `_SERVER_OWNED_RUNTIME_CONTEXT_KEYS` (`runtime/runs/worker.py:511-530`).
5. Resolution failure (DB error, or a thread row that does not exist yet) logs a warning and leaves the run unassigned — never fails the run; the fault is organizational, not authorization. This mirrors `_ensure_thread_metadata`'s non-fatal contract (`services.py:1477-1490`).

Consumers read only the pinned value: the middleware (§7.2) renders from it; the tools (§7.3) take `project_id` from it and then query the live shelf. No component re-resolves the thread's membership mid-run.

### 7.2 Latest-only instructions and shelf index injection

**One delivery model.** Instructions and the shelf index both live only in the assembled model request. `DynamicContextMiddleware` gains `wrap_model_call` / `awrap_model_call` hooks backed by pure rendering helpers in `deerflow/projects/context.py`; the existing `_build_full_reminder`, `_inject`, date correction and `__memory` persistence behavior remain unchanged. Project rendering does not depend on successful memory retrieval, and performs no database or filesystem I/O.

```
Persisted history (existing behavior unchanged):
SystemMessage  <system-reminder><current_date>…</current_date></system-reminder>
HumanMessage   id={user_msg_id}__memory   <memory>…</memory>  # optional
… conversation history …
HumanMessage   current user turn

Model request only, inserted immediately before the current user turn:
HumanMessage   <project id="…" name="Roadmap">
               {current instructions}
               </project>
               <documents count="7" shown="7">
               - id=abc123… | q3-report.pdf (2.1 MB, modified 2026-09-10)
               - …
               </documents>
```

- **One snapshot per run, one current block per model call.** All calls and retries within a run use the admission-pinned snapshot (§7.1), including after automatic compaction. The next run resolves a new snapshot. Tools still read live rows under the pinned project ID.
- **Latest-only semantics.** Rename, instructions edit or project move replaces the injected configuration on the next run. Empty instructions omit the instructions body while retaining the current project identity; an empty shelf omits `<documents>`. An unassigned run injects neither block and registers no project tools. No `__project` correction, move-out notice or recorded-history revision comparison exists.
- **Idempotent request assembly.** Use a reserved message ID prefix plus a server-owned `deerflow_project_context` marker and provenance to identify this middleware's transient message. Strip client-supplied copies of that marker at Gateway admission. On each assembly remove only the middleware's own recognized transient messages from the request copy, then insert at most one freshly rendered message. Never remove user messages by matching their text or an ID prefix alone. Mark it `hide_from_ui`, but do not set `dynamic_context_reminder`; never return it as a state update or write it into checkpoints.
- **Placement.** Insert before the genuine current-run user message, using server-owned run/message identity rather than the last arbitrary HumanMessage. Keep that anchor stable across the run's tool loop; do not append a new context message after each tool result or split an assistant tool-call/result sequence. If a resumed/internal run has no retained current-user anchor, use the protocol-safe position after leading SystemMessages. Recompute the valid anchor from the current request after compaction. The existing shared helper for front insertion remains unchanged; this project-specific placement belongs to the project renderer. Assert actual assembled order for normal, resumed, internal and compacted runs.
- **No history rewriting.** Existing user/assistant discussions of earlier instructions remain historical conversation, not active project configuration. The static trust declaration names the runtime-supplied current block as the source of active project settings; absence supplies no project instructions. This does not erase facts already discussed or change user-global memory semantics.
- **Compaction.** The actual summarizer rescues all messages marked `dynamic_context_reminder` (`summarization_middleware.py::_preserve_dynamic_context_reminders`). Project messages deliberately never enter that path: no project block in state, no protected correction accumulation, and no special project retention rule. The next model request simply renders the pinned snapshot again. The earlier draft's claim that normal compaction discards these reminders is withdrawn.

**Bounded rendering and trust.** The `<project>` block carries the pinned ID/name and current instructions. Escape attribute values, and pass instructions and document names through `neutralize_untrusted_tags`. Add `"project"` and `"documents"` to `_BLOCKED_TAG_NAMES`, the frontend `INTERNAL_MARKER_TAGS` and export scrub vocabulary; update the denylist drift guard without weakening it. Neither project values nor document names enter a SystemMessage. Rewrite `prompt.py`'s trust passage to distinguish the existing user-role `<memory>` data and request-scoped project data from framework rules; tag escaping does not grant system authority.

The index reports exact `count`/`shown`, orders entries by `updated_at DESC, id ASC`, and includes each stable document ID. Emit whole entries within `shelf_index_max_entries` and `shelf_index_max_bytes`; count IDs, escaped names, wrappers, separators and the overflow note in the byte cap, reserving wrapper/note space first. The note is actionable: `…and 12 more — call list_project_documents to list them all`. It is the bounded prefix of the shelf ordering at admission, not a guarantee that later live pagination sees an unchanged shelf.

**Audit fingerprints, not update state.** Retain the existing `context:memory` event type with additive project fields:

```python
content={"content_sha256": <hex | None>, "project_context_revision": <str | None>, "project_shelf_revision": <str | None>}
# content_sha256: selected existing __memory message only; null when absent
# project_context_revision: sha256(rendered <project> text), or null
# project_shelf_revision: sha256(rendered <documents> text), or null
```

Project hashes describe the blocks actually supplied to the model. They are never compared to history and never stored in reminder `additional_kwargs`. Extend `record_memory_context` to accept nullable `content_sha256`; emit once at first model-request assembly after delivery is known whenever memory or either project block is supplied, including project-only runs without `__memory`. Later model calls in the run do not duplicate the event. Runs with no such context retain the no-event behavior. A failed assembly must not claim successful delivery; existing memory failures follow their configured policy. Readers accept older payloads without project fields.

These are fingerprints, not retained versions. Neither instructions nor index text is retained in the transcript by this injector, and a hash cannot reconstruct either historical block. Run-event UI must not promise exact configuration replay. Document storage, user chat history and global memory are separate from this request-only injection lifecycle.

### 7.3 Documents: bounded project-level access

Three tiers, cheapest first; trashed rows are excluded from all three.

1. **Shelf index (discovery)** — the `<documents>` block rendered into each run's request from the pinned snapshot (§7.2), capped by `shelf_index_max_entries` / `shelf_index_max_bytes`, ordered `updated_at DESC`, entries rendered as `- id={document_id} | {name} ({size}, modified {date})`. The stable ID is directly usable by `read_project_document`, including for same-name documents, and is included in the byte cap and rendered hash. Metadata only. Because it is re-rendered every run, the only staleness window is **inside one run** — a document the user trashes, purges, renames, or adds after this run's admission is not in this run's block — and it never accumulates: nothing about the shelf is persisted, so there is no stale listing later in the conversation. That window never reaches content: every read re-validates live (§7.3 tier 2) and fails with an explicit error (§11) instead of serving stale bytes.
2. **On-demand read (content)** — two harness-side tools in a new `deerflow/projects/tools.py`, registered with `get_project_document_tools()` and appended to the lead agent's tool list beside the memory tools (`agents/lead_agent/agent.py:182-192, 1024-1030`) via the same collision-skipping helper, generalized from `_append_memory_tools_without_name_conflicts`. **Registration is conditional on the run's pinned project context**: the tools are appended only when `PROJECT_CONTEXT_KEY` is present, so a non-project run never pays their schema tokens and never sees them. This is cheap because assembly is already per run — `make_lead_agent(config)` → `assemble_lead_agent(config)` (`agents/lead_agent/agent.py:758-801, 878+`) computes the tool list from run-scoped config today (`agent_name`, model overrides, `should_use_memory_tools`), and no run-graph cache depends on it (`_state_accessor_graph_cache` caches only the state-accessor graph, keyed `(assistant_id, mode, snapshot_frequency)` — `app/gateway/services.py:916-951`). The predicate reads the **server-owned pinned key only**, never a client-influenceable field, and both tools still fail closed if the key is somehow absent at call time (belt and braces). After admission has resolved and stored the snapshot (§7.1), middleware and tool registration share one predicate over the server-owned pinned key. Resolution must not depend on that predicate before the key exists. An empty instructions block or shelf may omit rendered text without suppressing the tools; admission failure leaves the key absent and registers neither tool.
   - `list_project_documents(offset: int = 0, limit: int = 50) -> str` — JSON listing of live shelf rows (paged, `limit ≤ 200`) in the index's own `updated_at DESC, id ASC` order, returning `total` and `next_offset` so the model can walk the shelf the index truncated; for shelves beyond the index cap.
   - `read_project_document(document_id: str, offset: int = 0, limit: int = 8000) -> str` — bounded slice of the document's text. `limit ≤ 20000` characters; the response carries `{name, total_chars, offset, returned_chars, truncated, content}`. Text detection samples the head of the file with the existing `is_text_file_by_content` helper (`routers/artifacts.py:235`), extracted to a shared `deerflow/utils/` module so router and tool use one implementation. Convertible types (`CONVERTIBLE_EXTENSIONS`, `utils/file_conversion.py:32`) are converted with `convert_file_to_markdown` on first read and served from the document-owned `derived/converted.md` companion; conversion is skipped and the call declined when `uploads.auto_convert_documents` is off. Non-convertible binaries are declined with an error that names attach-to-thread as the route.
   - Both tools take `project_id` from `runtime.context[PROJECT_CONTEXT_KEY]` and `user_id` from `resolve_runtime_user_id(runtime)` (`runtime/user_context.py:178-219`), following `list_uploaded_files_tool.py:42-63`. Missing project context or a missing session factory ⇒ a tool error, never an empty success.
   - **Subagents do not get these tools in Phase 2.** The subagent runtime has its own middleware set (date-only, no memory lookup) and its own tool list; the lead agent reads what it needs and passes content down in the task prompt. Extending shelf access to subagents is a separate decision with its own consumers, not a side effect of the lead's registration.
   - Every file read, restore content check and conversion is offloaded (`asyncio.to_thread` / `convert_file_to_markdown`'s own >1 MiB offload) and needs a `tests/blocking_io/` anchor — the repo's guard suite covers async paths that touch the filesystem.
3. **Attach to thread (explicit, shelf → thread)** — `POST …/attach-to-thread/{thread_id}` reads an owned live document (active or archived source project allowed) and materializes an independent copy through a shared thread-upload ingestion service extracted from `routers/uploads.py`. The service owns staging, `claim_unique_filename`, size checks, optional conversion under `uploads.auto_convert_documents`, sandbox-readable permissions, and non-mounted-provider synchronization of original and derived files via the existing authorized sandbox request lease. A denied `sandbox:execute` follows ordinary uploads: retain the host upload without allocating a sandbox. Acquisition/sync/conversion failures follow the ordinary upload service's error and cleanup behavior; no successful attachment is returned before required sync completes. Tests pin parity for both callers, including partial-sync cleanup behavior. The source shelf is unchanged.

   Return `{filename, size_bytes, virtual_path, artifact_url}` only after ingestion succeeds. The frontend adds the file to the composer's attachment list, engaging existing `additional_kwargs.files` → `UploadsMiddleware` `<current_uploads>`. Source validation and a stable source read are serialized against purge; target thread ownership/write admission is revalidated through the shared upload service. Do not hold the document transaction across sandbox allocation/network sync: stage the source copy under its lock, then perform ingestion with ordinary thread-upload lifecycle guarantees.


### 7.4 Save to shelf, and the conversation-files view

**Save to project** (`POST …/documents/from-thread`, `{thread_id, kind, name, shelf_name?}`): copies the thread file (uploads or outputs) into the shelf as a project-owned snapshot. The source file is untouched; the shelf holds no reference into thread storage, so deleting the thread cannot affect it. `source_thread_id` / `source_kind` / `source_name` are recorded and rendered as a provenance badge ("from *thread name* · output"). `name` locates the source file inside the thread; the promote dialog's editable name field sends `shelf_name` (default: the source name) and is the only way the two diverge — which is exactly what makes `source_name` a consumed column rather than a dormant one (RFC §4.3: "original name inside the thread, if renamed on the shelf"). Validation is the upload path's: owner-checked thread and project, active project required, `uploads.max_file_size`, staging + `os.replace`, document-owned hash-qualified path. Source resolution is confined to that thread's own `user-data/{uploads,outputs}` directory — the `resolve_virtual_path` discipline (`config/paths.py:446-484`), not a string join.

**Conversation-files view** (`GET …/thread-files`): read-only aggregation over member threads. Response shape:

```json
{"groups": [{"thread_id": "…", "display_name": "…", "updated_at": "…",
             "files": [{"kind": "upload", "name": "…", "size_bytes": 0, "modified_at": "…",
                        "artifact_url": "/api/threads/…/artifacts/mnt/user-data/uploads/…"}]}],
 "next_offset": 20, "truncated": false}
```

Bounded fan-out: member threads are paged (`thread_limit` default 20, max 50) over the same non-archived ordering the project thread list uses; each thread contributes its uploads (via `list_files_in_dir(sandbox_uploads_dir)`, `uploads/manager.py:287`) and its outputs (a new listing over `sandbox_outputs_dir` — no outputs-listing endpoint exists today, so this helper is new and shared with nothing else). Per-thread file cap `file_limit`; the response reports `truncated` rather than silently cutting. No storage of its own: entries disappear when their thread is deleted, which is the honest ownership statement. The view is the discovery route for Save to project and never feeds the shelf, the index, or the tools.

## 8. Delete, Trash, and Archive Semantics

### 8.1 Project delete

`ProjectRepository.delete` keeps its shape (owner-scoped project row lock, then the statements below in one transaction) and gains the second statement:

1. `UPDATE threads_meta SET project_id = NULL WHERE project_id = :pid` (+ owner predicate) — implemented today (`persistence/projects/sql.py:171-176`), including the recency-safe `updated_at` self-assignment.
2. `UPDATE project_documents SET trashed_at = :now, trash_origin = :json WHERE project_id = :pid AND trashed_at IS NULL` — new; one statement, no filesystem work, rows snapshot `{project_id, project_name}` before the project row disappears.
3. `DELETE FROM projects WHERE id = :pid`.

The delete confirmation copy changes accordingly (threads unlink; shelf documents move to trash and stay recoverable for `trash_retention_days`); the current string that promises files are untouched (`frontend/src/core/i18n/locales/en-US.ts:357-358`) is wrong after Phase 2 and must be replaced, zh-CN included.

### 8.2 Trash restore

`POST /api/trash/documents/{document_id}/restore`, body `{project_id?}`:

- Target = body value, else `trash_origin.project_id` when that project still exists, is owned, and is `status='active'`; otherwise the request fails with 404 and the UI offers the project picker.
- Merge case: the target already has an active row with the same `sha256` → the trash row is deleted and the response reports `merged`. The now-unreferenced file (the trash row's exclusive document namespace, which no surviving row can reference) is unlinked best-effort after commit; failure is logged, and the sweep collects it (§8.3).
- Otherwise the row is re-pointed (`project_id` = target, `trashed_at` = NULL, `trash_origin` = NULL) in one transaction. **No file moves**: `stored_relpath` is project-root-relative (§6.2), so the bytes stay valid.
- Restoring into a project the caller does not own is a 404, indistinguishable from a missing project.

### 8.3 Permanent purge and retention

- Purge exists only through `POST /api/trash/documents/{id}/purge` and `POST /api/trash/purge`, each behind an explicit "this cannot be undone" confirmation in the UI, plus the retention sweep. Empty trash purges **every** trashed row of the caller regardless of age — its confirmation covers the whole listing — so the retention cutoff gates the sweep alone: `purge_candidates` stays the only age-filtered selection.
- Ordering: within the continuously row-locked database transaction (§6.3), unlink the original and `derived/converted.md` first, then delete the row and commit. `FileNotFoundError` is idempotent success, including a missing optional conversion. Other filesystem failures retain the trashed row and return a retryable error. A crash, partial unlink, or database commit failure after unlink may leave a trashed row with missing content; the next purge completes it. Restore checks original existence and size (and the surviving merge target when applicable) under the same document-row locks and rejects `content_missing` with 409 rather than activating a broken row. Database rollback cannot restore bytes. Merge cleanup is separate: its committed row removal can leave only unreferenced files.
- Retention: `projects.trash_retention_days` (default 30). The sweep invokes the same guarded purge service for expired trash, then performs non-destructive row reconciliation. It runs lazily on `GET /api/trash/documents` and once at gateway startup in the `lifespan` handler (`app.py:196`, beside the other startup work at `:253-320`). No new daemon, no scheduler dependency.
- The sweep also reconciles storage, bounded by age; any active or trashed row protects its entire original/derived namespace, even after restore to another project: `.staging/*` entries and any unreferenced file under a user's `projects/*/documents/` older than 24 hours are removed. Nothing younger than 24 hours is ever collected, so an in-flight upload cannot be swept.
- Emptying a project's last trashed document leaves an empty directory; `rmdir` parents best-effort.
- **Row-side reconciliation.** The sweep's other direction: a row whose content file is missing (unlinked), or whose on-disk size differs from `size_bytes`, older than the same 24-hour guard, is **detected but never auto-deleted**. The sweep logs it at warning level and the row is surfaced as `content_missing` (§11). Deleting the row would erase the user's only record that the document existed and take the provenance with it; disposal starts with the user moving active content to trash; manual purge or eligible retention purge may then remove the trashed row. Files are immutable and hash-qualified, so a size mismatch means external interference, not staleness — it is reported, never repaired in place.

### 8.4 Archive

The Phase-1 archive matrix is unchanged for threads and gains the document row it could not express before:

| Question | Answer |
| --- | --- |
| Can its threads still run? | Yes |
| Do runs still get instructions / shelf index injected? | Yes — injection reads the archived project's row (§7.1 step 2) |
| Can threads be moved into it? | No (Phase 1 enforcement) |
| Can documents be uploaded/promoted into it? | No — the shelf insert locks the project row with `status='active'` (§6.3); the UI omits archived projects from the upload/promote surfaces |
| Can its shelf be read? | Yes — list, preview/download, thread-files and tools remain available; the project page shows a read-only banner |
| Can a shelf file be attached to a thread? | Yes — including from an archived project, subject to target thread write permission and normal upload/sandbox rules |
| Can individual shelf files be trashed or restored into it? | No — these mutations require an active project; whole-project deletion keeps its existing contract and trashes the shelf |
| Where do its threads appear? | Flat list unchanged; grouped mode collapses into "Archived" (Phase 1) |

## 9. Frontend Design

Default copy language is `en-US` (`core/i18n/locale.ts:3`); every new key lands in `locales/types.ts`, `en-US.ts`, and `zh-CN.ts` together.

- **Project page** (`app/workspace/projects/[id]/page.tsx`) gains tabs — Chats (existing), Documents, Instructions, Settings (existing) — following the Tabs pattern already used by `app/workspace/chats/page.tsx:130-138`.
  - **Documents** has two areas separated by a divider: the curated shelf (upload button + drag-drop, rows with name / size / modified / provenance badge, preview, download, attach-to-thread, move-to-trash) and, below, the read-only conversation-files browser (grouped by thread, each entry with preview and **Save to project**). Row layout and per-row actions reuse `ArtifactFileList` (`components/workspace/artifacts/artifact-file-list.tsx:34-192`); preview reuses `ArtifactFilePreview` / `ArtifactViewer` / the `/artifacts/view` route. Trash is **not** an undo toast here: deleting shows a confirmation that names the trash and the retention window.
  - **Instructions** is a `Textarea` with explicit save through `usePatchProject` (the field is already plumbed: `core/projects/api.ts:79, 104-106`), a live byte counter against `projects.instructions_max_bytes`, and a client-side guard that mirrors the 422.
- **Trash view**: new route `/workspace/trash` — deliberately **not** under `/workspace/projects/`, where the dynamic `[id]` segment would swallow a literal `trash` path — reachable from the project page's Documents section and the sidebar Projects section header, listing trashed documents with origin project name and remaining retention, per-entry Restore / Delete-permanently, and "Empty trash" with its own confirmation. Action rows follow `app/workspace/chats/page.tsx:200-216`.
- **Sidebar**: `ProjectsSection` gains a Trash entry point. No grouping changes.
- **Move menu**: unchanged — the non-isolation hint (`move-to-project-menu.tsx:100-103`) stays verbatim.
- **Interim memory notice**: the project page's empty state (and the Documents tab's empty state) carries the RFC §10 copy — memory stays user-global until Phase 3, so anything discussed in a project may enter global memory. This is the "clear notice" the issue's acceptance list asked for, now that documents exist.
- **State**: new hooks in `core/projects/` — `useProjectDocuments`, `useUploadProjectDocument`, `usePromoteThreadFile`, `useAttachProjectDocument`, `useDeleteProjectDocument`, `useProjectThreadFiles` with query keys under `["projects", "documents", projectId]` / `["projects", "thread-files", projectId]`; `core/trash/` with `useTrashDocuments`, `useRestoreDocument`, `usePurgeDocument`, `useEmptyTrash`. Mutations invalidate the `["projects"]` prefix (the `invalidateProjectCaches` convention, `core/projects/hooks.ts:38-46`) and `["threads"]` where attach changes a thread's uploads.
- **Static-demo guard**: every Phase-2 surface returns `null` under `isStaticWebsiteOnly()`, matching `projects-section.tsx:266-268`.

## 10. Deviation Register (RFC v2 and Phase-1 spec vs. code)

This register explains significant departures from the RFC and predecessor spec. This entire spec is authoritative for Phase 2 whether or not a difference is repeated here; historical RFC acceptance criteria apply only as explicitly adopted by this spec.

### 10.1 Reminder shape and role authority

The RFC placed project instructions inside a SystemMessage. This spec preserves the existing authority split: project identity/instructions and document names use request-scoped HumanMessage data. Existing date SystemMessages and `__memory` messages retain their current behavior; project data is not spliced into either.

### 10.2 Coalescing does not own project state

SystemMessage coalescing may deduplicate date reminders, but the project block is a separate request-only HumanMessage. No project revision is carried or re-emitted by a SystemMessage; model-request composition must retain exactly one current block (§7.2).

### 10.3 File-before-row, not row-before-file

RFC §5.2 stages bytes, commits the row, then moves the file, and accepts a crash window that leaves "a shelf row without a file". That broken state is *visible* to the model (the index lists it) whereas the inverse is not. Phase 2 renames the staged file into its document-owned hash-qualified home **before** inserting the row: a crash leaves an unreferenced file that no consumer sees and the sweep collects. The RFC's own §4.4 already accepts the file-side leak as the bounded failure.

### 10.4 `shelf_revision` hashes the rendered index

RFC §7.1 defines `shelf_revision` as "document count + max `updated_at` among active rows". That pair is blind to a rename, to the index crossing its entry/byte cap in either direction, and to ordering ties. The implementation hashes the rendered `<documents>` text — the exact bytes the model was given, which is also what a revision identity should mean. Semantics (a shelf change refreshes the index) are unchanged and strictly tightened.

### 10.5 Explicit project audit fields

The existing `context:memory` hash covers only the selected `__memory` message. Project blocks no longer ride that message, so audit requires separate `project_context_revision` and `project_shelf_revision` fingerprints over the rendered blocks (§7.2). Extend the existing event and its emission guard for project-only runs; do not add an event type or claim the memory hash covers project instructions. Fingerprints cannot reconstruct historical configuration.

### 10.6 Restore re-points without moving files

RFC §5.1 says restore "physically moves the file when the target directory differs". Because `stored_relpath` is stored relative to `users/{user_id}/projects/` (§6.2), the path stays valid across a re-point: restore changes only database ownership and trash fields, with no file move. A read-only existence/size check under the document lock prevents restore from activating content lost in a partial purge (§8.3). Merge cleanup after commit is the only filesystem mutation on the restore path; trash remains filesystem-free.

### 10.7 Admission does not translate the reserved key (Phase-1 divergence, restated for Phase 2)

RFC §6 says first-run admission validates `deerflow_project_id` and writes the membership column. It does not: admission strips the key and never writes membership (`services.py:207-218`, pinned by `tests/test_thread_meta_repo.py:598-623`), and the client-side gap is closed by the frontend pre-creating the thread with `project_id` (`chat-page.tsx:213-230`). Phase 2 therefore resolves project context from `threads_meta` at run start (§7.1) instead of from run metadata, and adds nothing to the admission key path.

### 10.8 Atomicity uses the landed lock idiom

RFC §5.2 writes the checks as literal `INSERT … WHERE EXISTS (SELECT …)` SQL. Phase 1 shipped the equivalent as a locked `SELECT … FOR UPDATE` (with SQLite `BEGIN IMMEDIATE`) inside the write transaction. Phase 2 extends that idiom; a reviewer comparing against the RFC's SQL snippets should read §6.3 instead.

### 10.9 Dedup returns the first name, not the requested one

RFC §4.4 says re-adding identical content returns the existing row, without saying whose `name` wins. Decision: the **first** writer's name wins, and the response is the existing row (`200` instead of `201`). The existing row and its original provenance win as well. A new row after trash receives a fresh exclusive namespace (§6.2), even for identical bytes/name. Physical files are never shared across rows; conversion cache validity follows immutable bytes within that row, not dedup across lifecycles.

### 10.10 Truncation policy: bounded index, accepted discovery tail

RFC §7.2 caps the index but leaves two things open: what a truncated shelf implies for discovery, and what order the visible subset is chosen in. Decisions, with the weakness they accept stated up front:

- **Truncation is accepted but never silent and never inert**: exact `count`/`shown`, the omitted count, and an overflow note that names `list_project_documents` (§7.2). The model is never left knowing "there is more" without a next step.
- **Ordering is `updated_at DESC, id ASC`**, identical to what the tools page in. Consequence: newly added material is what the agent sees for free, and the *old-but-important* document is exactly the one that falls off the visible subset as a shelf grows. That is the real cost of this policy, and it is bounded by the tool tier rather than hidden: the tail is one call away, the count says how large it is, and the user can always attach a specific document.
- Alternatives rejected for this phase: **star/pin a document** (needs a new column plus a UI action before it has a consumer — the "no dormant schema" rule), **name or `created_at` ordering** (deterministic but drops the recency signal the common case relies on; a stable order would also reshuffle less, so it is the first thing to revisit if usage shows the tail is being missed), **full-text/embedding search over the shelf** (deferred by the RFC; an index is a much larger commitment than a page-at-a-time tool).
- If the needle-in-a-haystack case turns out to dominate, the smallest sufficient fix is a re-examination of *ordering*, not a bigger injection: the caps are config, but an unbounded index contradicts the non-goal the issue tracker set.

### 10.11 Project tools exist only in project runs

RFC §7.2 lists the two tools but never says who registers them or when. Decision: registration is **conditional on the run's pinned project context** (§7.3), evaluated through the one shared predicate described there, after admission has resolved the snapshot. Consumers share the pinned identity; empty blocks and injection failure have the explicit delivery semantics in §7.2/§7.3.

Consequences accepted, each with its mitigation:

- A run whose resolution failed silently lacks both the block and the tools; the only signal is the admission warning (§7.1) and the next run's self-heal. Stated rather than hidden: for an organizational feature, silent degradation is preferable to failing the run, but it is a real loss of capability for that run.
- The assembly descriptor gains a second variant per agent (with/without the project tools), because the tool list feeds `build_assembly_descriptor` (`agents/lead_agent/agent.py:850-875`). Tests and observers that assert a single stable descriptor must accept both; `test_agent_assembly_descriptor.py`-style coverage pins both branches.
- The tools stay in the always-on list for project runs rather than joining deferred tool search: the injected index advertises `list_project_documents` by name, and a tool that is advertised but not directly callable is worse than one that is absent.

Rejected: unconditionally registered tools that fail closed. It costs every non-project run a fixed schema budget for a capability it can never use — the recurring cost lands on the majority case — and the "it preserves an explicit error signal" counter-argument is weak, because the `<project>` block is absent too, leaving the model nothing to act on.

### 10.12 One project snapshot per run

Admission resolves and pins membership, identity/instructions and the bounded index once. Rendering and registration use that same snapshot; tools query live content under its project ID. Re-rendering per model call does not mean re-reading the database or changing membership during the tool loop. Resolution failure is handled at admission; the pure project renderer does not add an async database bridge to memory injection. Live offset pagination may drift after concurrent shelf mutations, despite using the same ordering as the index.

### 10.13 Latest configuration instead of a persisted correction chain

The earlier draft persisted initial instructions and appended a revision-marked correction on each change. This is superseded: the model receives only the current run's project configuration via request assembly (§7.2). There is no identity revision comparison, missing-history-key recovery branch or correction-retention policy. Existing summarization preserves all `dynamic_context_reminder` messages; marking every project correction that way would accumulate protected instructions despite a per-message cap. Request-only injection removes that interaction without changing memory/date retention.

Latest-only refers to injected configuration, not deletion of historical chat. Request blocks are excluded from checkpoint messages and compaction inputs; prior conversation may still mention earlier settings. Versions and exact historical configuration replay remain outside Phase 2; journal hashes are fingerprints only.

### 10.14 Request placement and prefix-cache tradeoff

Instructions and shelf index share one request-only message. Ordinary runs place it before the current user turn rather than rewriting an early historical reminder. Rendering the same pinned content again is not itself a cache miss: cache reuse depends on the final serialized request prefix, tool schemas, placement and provider behavior. Context changes or movement of the insertion boundary can change the reusable suffix; resumed-run fallback placement may affect more history. Other middleware may also insert changing data near the front. This spec promises bounded, non-accumulating context, not a guaranteed cache hit rate or that only one block is billed uncached. Validate assembled requests structurally; measure provider cache tokens and latency before making performance claims.

## 11. Error Handling

| Case | Behavior |
| --- | --- |
| Cross-user / missing project, document, thread | 404 (fail closed; never 403) |
| Upload/promote into archived or foreign project | 404 via the locked active-project check |
| `instructions` over the byte cap | 422 at write time (POST and PATCH); never truncated |
| Upload over `uploads.max_file_size` / empty file / unusable name | 413 / 400 as the uploads router does |
| Promote with a `kind`/name that resolves outside the thread's uploads/outputs | 404 (confinement failure is indistinguishable from absence) |
| Attach into a thread the caller cannot write | 404 |
| Restore with no valid target (origin gone/archived, none supplied) | 404; UI offers the picker |
| Restore that collides with active content | `merged` result; trash entry gone |
| Purge when unlink raises other than `FileNotFoundError` | Transaction rolled back, trashed row kept, 500 with a retryable message |
| Purge when original/derived content is already absent | Missing file counts as removed; complete remaining cleanup and row deletion |
| Restore whose original is absent or size-mismatched | 409 `content_missing`; row remains trashed |
| Shelf insert fails after the file was renamed into place | Unreferenced file, collected by the sweep (>24 h) |
| `read_project_document` on a binary or conversion-disabled convertible | Tool error naming attach-to-thread |
| Tool call without pinned project context | Tool error; no data |
| Document trashed or purged after this run's index was rendered | Tool error `no longer on the shelf` — never stale content; the next run's index simply omits it (nothing persisted needs repairing) |
| Row whose content file is missing (`content_missing`) | Content endpoint and tools return an explicit `content_missing` error; the project page renders that row as **content missing** with move-to-trash as its only document action in active projects; archived shelves offer no document mutation until the project is restored; the sweep logs it (§8.3) |
| Repositories unavailable (memory backend) | 503 `"Projects"` (existing accessor convention) |
| Resolution failure at admission | Log warning; run proceeds unassigned |

Purge endpoints carry no confirmation parameter: the "this cannot be undone" step is a UI contract (§8.3, §9), and is not a server-enforced confirmation handshake. Authorized API clients can call purge directly; omitting a flag neither changes nor reverses its destructive semantics.

## 12. Security and Isolation

- Every query goes through repositories that auto-filter by the ContextVar user; no route or tool accepts a `user_id`.
- The pinned project context is a server-owned runtime-context key, stripped from caller config/context at admission and refused by the worker merge. The separate `deerflow_project_context` message marker is also stripped from client-supplied message metadata; request injection stamps it together with provenance and a reserved ID prefix (§7.2).
- Document reads resolve under `users/{user_id}/projects/` and re-check `relative_to`, the same discipline as `resolve_virtual_path`; `stored_relpath` values come only from server-generated content addresses, never from request text.
- Instructions and document names are untrusted text: neutralized for blocked tags before rendering (§7.2) and denylisted in the input sanitizer so a user message cannot forge a `<project>` block.
- Trashed documents are invisible to the shelf index, the tools, and the listing APIs; they remain visible only through the user's own trash endpoints.
- Retention and purge are user-scoped like everything else; an unlink error other than already-absent content retains the trashed row; partial filesystem progress and commit failures follow the explicit retry contract (§8.3).
- PAT callers are default-denied until the new routes are added to the allowlist (`auth/pat.py`), which is the intended default.

## 13. Testing Strategy

**Backend unit**

- `ProjectDocumentRepository`: dedup among active rows (trashed rows do not block re-add), `trashed_at` filtering in every read, `shelf_snapshot` ordering, `restore` outcome matrix (`restored` / `merged` / `not_found` / `no_target` / `content_missing`), `purge_candidates` boundary at exactly `retention_days`.
- Instructions cap: boundary at exactly `instructions_max_bytes` accepted, one byte over rejected with 422 on both create and patch; multi-byte (CJK) inputs counted in UTF-8 bytes, not characters.
- Index rendering: entry cap, byte cap, truncation note, empty-shelf absence, escaping of `</project>` and of document names containing blocked tags.
- Index rendering algorithm: with CJK names the byte cap binds before the entry cap; no partial entry is ever emitted; the omitted count equals `count − shown`; the overflow note names `list_project_documents`; and, with no concurrent shelf mutations, paging the tool walks the same ordered entries. Separate tests permit live-page drift after mutation rather than asserting snapshot pagination. IDs and all wrapper/overflow bytes count toward the cap.
- Latest instructions: each of {rename, instructions edit, clear, move in, move out} changes the next run's request to the current configuration only, with no old injected instructions or correction messages. Empty instructions retain project identity; unassigned runs have no project block. Date/memory messages and metadata remain unchanged, including a simultaneous midnight transition.
- Request-only delivery: every model call/retry has exactly one current project message when assigned, with one index if nonempty, and no injected project text in checkpoint messages before/after the run. Forty edits across runs still produce only one current block, including after automatic/manual compaction. Reassembling an already decorated request replaces its own transient message without removing user content; forged marker/ID inputs cannot suppress or replace the block. Test placement before the current genuine user message, stable tool-loop positioning, and protocol-safe fallback for resumed/internal calls.
- Journal identity: one `context:memory` event per delivered run; `content_sha256` covers only the existing `__memory` message (null when absent), while project hashes cover the current rendered blocks. Test project-only runs, empty instructions, no shelf, no project, repeated calls, failed assembly and older event payloads. Project hash changes never append or rewrite checkpoint messages. Fingerprints must not be presented as reconstructable versions.
- Tools: slice boundaries (offset at/over `total_chars`), `limit` clamp at 20000, binary decline, convertible path with `auto_convert_documents` on and off, fail-closed without pinned context, reads reflecting a live shelf edit without re-attach.
- Config: defaults when `projects:` is absent, invalid values fall back with a warning (the `_get_upload_limit` idiom), bounds enforced.

**Backend integration**

- Fail-closed 404 on every new route for a foreign or missing project/document/thread.
- Upload → list → content → attach → delete → restore → trash again → purge round trip through the API, with the trash view in between.
- Filename boundary: 255 UTF-8 bytes accepted for original and convertible documents, 256 rejected; physical components remain within the filesystem limit. Same-name rows with different content have distinct IDs directly readable from the index.
- Archived matrix: list/content/tool reads/injection and attach remain available; upload/promote/individual trash/restore target return 404; project deletion still trashes its shelf.
- Attach parity with ordinary uploads: mounted and non-mounted providers, original/converted sync, readable permissions, denied `sandbox:execute` (no allocation), acquire/sync failure and partial cleanup. Composer receives a completed attachment only on success.
- Slice boundaries: A injects instructions without the document table; B alone prevents active shelf rows surviving project deletion. Validate these before adding D.
- Project delete: membership cleared, shelf trashed in the same transaction, no file touched, no permanent deletion.
- Purge ordering: injected `OSError` retains the trashed row; missing optional conversion succeeds; original unlink followed by derived unlink failure or database commit failure is retryable. Restore of missing/size-mismatched content returns 409 without activation. Cleanup uses the owning document namespace, including `derived/converted.md`.
- Retention sweep: lazy trigger on the trash listing, startup trigger, 24-hour orphan guard (a fresh staging file survives); row-side reconciliation detects a missing or size-mismatched content file, logs it, and leaves the row intact — only explicit purge or eligible retention purge may later remove a trashed row; reconciliation alone never does. Revalidate the candidate trash timestamp/cutoff under lock after a concurrent restore/re-trash.
- PAT allowlist drift guard extended with the new routes.
- Migration `0023` applies and downgrades; the forward-revision-compat head pin is updated; `test_migration_0021_batch_acceptance.py`-style parametric upgrade still passes.

**Concurrency (hard requirement)**

- Concurrent upload vs project delete: either the insert sees no active project (404) or the delete trashes the new row — never an active row pointing at a deleted project.
- Concurrent duplicate upload of identical bytes: exactly one row, one file, both requests report success.
- Concurrent restore into a project being deleted: 404 or a clean trash pass, never a row whose project row is gone and is not trashed.
- Concurrent purge vs restore of the same document: with healthy storage one wins, the loser gets 404; lock coverage includes unlink and commit, tested with barriers on SQLite and the supported row-locking database. Failed purge retains a trashed row; restore returns 409 if bytes were already removed. Exercise both lock acquisition orders.
- Upload → trash → identical same-name re-upload → purge old row: new row content and conversion survive. Repeat with restoring the old row into the same project (merge), and after restoring into another project; assert distinct namespaces and cleanup confinement.
- Concurrent conversion vs purge: conversion cannot publish after the document has been purged; no partial converted text is exposed.

**Run-pinning**

- A run started before a mid-run move completes with the pre-move instructions and tool reads; the next run injects only the newly resolved project configuration (§7.2).
- A run whose thread is unassigned gets no `<project>` block and `list_project_documents` fails closed.
- Frozen-index consistency: a document trashed after admission is still named by that run's index, the same run's `read_project_document` fails with the stale-entry error, and the next run's request-scoped index omits it without any persisted project message.
- Admission: a client-supplied `PROJECT_CONTEXT_KEY` in `config["context"]` or `configurable` never reaches the run.
- Tool availability follows the pinned key: a run assembled without `PROJECT_CONTEXT_KEY` never registers `list_project_documents` / `read_project_document` (asserted on the assembled agent's tool list, not on call behaviour), a run assembled with it registers both, and a thread that gains membership sees them on its next run while a thread that loses membership stops seeing them. Registration follows the pinned key even when instructions and shelf are both empty; the identity-only block and tools remain available. Admission failure registers neither tool. Both assembly-descriptor variants are pinned, since the tool list feeds the descriptor.

**Blocking-IO anchors**

- `backend/tests/blocking_io/` gains anchors for the new async paths that touch the filesystem: document upload staging/rename, purge unlink, restore content checks, conversion, shared attach ingestion, sweep reconciliation, and tool reads (the suite already anchors `DynamicContextMiddleware`, so its new render path inherits an existing guard). The anchor must fail when the offload is removed (the suite's existing mutation-verified style).

**Frontend**

- DOM: Documents tab render (shelf rows with provenance badge, empty state, truncation note), Instructions editor (counter, save, over-cap guard), Trash rows with retention display, delete-project copy.
- Playwright: upload → shelf → attach → delete → restore → purge through mocked routes (extend `tests/e2e/utils/mock-api.ts` with the new endpoints, following the existing default-empty pattern at `:930-956`), plus a project-with-instructions run showing no `<project>` text leaking into the rendered message list.

**Acceptance mapping**: This spec's user stories, contracts and checks above define Phase 2 completion. RFC §14 items 6–12 and 15 are historical traceability references, subject to this spec's choices.

## 14. Documentation Updates Required

- `README.md` — user-facing project instructions, shelf, archive read semantics and trash retention.
- `backend/docs/API.md` — the Phase-2 route reference (documents, thread-files, trash).
- `backend/docs/ARCHITECTURE.md` — project shelf layout, run-start pinning, role-authority split, trash tier.
- `backend/packages/harness/deerflow/persistence/migrations/AGENTS.md` — chain head moves to `0024_project_documents` (`0023_user_preferences` → `0024_project_documents`), with the forward-compat note that the floor is unchanged.
- `backend/app/gateway/AGENTS.md` — membership-writer contract gains "run admission pins project context read-only; it still never writes membership".
- `config.example.yaml` — the `projects:` block (§6.4).
- `frontend` i18n dictionaries — all new keys (§9).
- User-facing copy for the interim memory semantics and the trash retention window.

## 15. Code Review Checklist

Reject the PR on any of these:

1. `instructions` or document names rendered into a SystemMessage, or into the static system prompt.
2. Truncation of oversized instructions instead of a write-time 422.
3. Bulk document injection; an index with a silent cut; trashed rows visible to the index or tools.
4. Document tools re-resolving the thread's project at call time instead of reading the pinned key; a second resolution path.
5. Check-then-act anywhere in the new writes: an existence/ownership/status check in a read separate from its mutation.
6. A row inserted before its bytes exist at the document-owned hash-qualified path (§10.3 inverted).
7. Restore moving or rewriting original files, or trash performing filesystem work. Restore permits the locked read-only content check and post-commit merge cleanup (§8.2/§8.3).
8. Purge releasing its document lock before cleanup/commit, deleting the row before file cleanup, or swallowing an unlink error other than `FileNotFoundError`.
9. A new daemon, cron, or scheduler entry for retention.
10. A DB-level foreign key on `project_documents.project_id`, or a dormant column (`mime`, `is_text`, `version`, `deleted_by`).
11. `user_id` accepted from a request body, param, or tool argument; any 403 that leaks existence.
12. A client-supplied value surviving as pinned project context; a new runtime-context key missing from either server-owned set; a tool-registration predicate reading anything other than that server-owned key.
13. A new RunJournal event type for project context (§10.5).
14. Any of `"project"`, `"documents"` missing from `_BLOCKED_TAG_NAMES` / `INTERNAL_MARKER_TAGS`, or the drift-guard test updated by weakening rather than by classifying the new tag.
15. Any change to memory read/write paths, or a memory-API `scope` parameter.
16. Slice A depending on document storage; Slice B shipping without project-delete trash transitions; or a dependent slice being merged/reverted without its prerequisites (§16).
17. Row-side reconciliation deleting rows rather than reporting them: retention purge may remove expired trash under §8.3, but reconciliation must never remove a row, and no code path may treat a missing content file as an empty document.
18. Project injection rewriting persisted history, piggybacking on `__memory`, or setting `dynamic_context_reminder` on project messages instead of using the request-only path.
19. Comparing project revisions against history or appending a correction/move-out chain; using old instructions after the next admission has resolved a new snapshot.
20. Instructions or shelf index accumulated across requests, rendered from anything other than the pinned snapshot, or inserted between an assistant tool call and its result.

## 16. Implementation Order

Five slices, each mergeable once its prerequisites have landed. Rollbacks follow reverse dependency order; removing a prerequisite while retaining its consumers is unsupported. A slice ships with its own tests and docs per §13/§14.

- **Slice A — Instructions injection.** `ProjectsConfig` + write-time cap + 422; `deerflow/projects/context.py`, admission identity/instructions pinning (`PROJECT_CONTEXT_KEY`, both server-owned sets); request-only `<project>` rendering and idempotent placement through DynamicContext model-call hooks; server-owned transient marker stripping, provenance and frontend hiding; `project` in backend/frontend marker vocabularies and drift guards; static trust passage; nullable memory hash and audit-only project fingerprint; Instructions tab. No document repository dependency, no identity correction chain, no changes to memory/date persistence. Revert A after its dependent slices.
- **Slice B — Shelf storage, delivery, and reads.** `ProjectDocumentRow` + `0023` migration + repository; `Paths` helpers; `deerflow/projects/documents.py` and `tools.py`; extend A's pinned context with the bounded shelf snapshot; upload/list/content/delete-to-trash routes; project-delete shelf trash transition and updated delete confirmation copy, with `trash_origin` snapshots; the **request-scoped `<documents>` block** (rendered per run from the pinned snapshot, never persisted); `project_shelf_revision` in the journal payload; the two tools + `is_text_file_by_content` extraction. Depends on A for the request-scoped project renderer it extends; add `documents` to both marker vocabularies and the drift guard.
- **Slice C — Promotion and the file browser.** `from-thread`, `attach-to-thread`, `thread-files` (+ the new outputs listing helper), and their frontend surfaces. Depends on B.
- **Slice D — Trash completion.** Restore/purge/empty-trash routes, `trash_origin` display fields, retention sweep + startup hook, orphan reconciliation. The `DELETE …/documents/{id}` route lands in B (trashing is what "delete" means), and project deletion must already trash all active shelf rows in B; restore/purge and the sweep are D. Depends on B.
- **Slice E — Frontend completion and copy.** Documents tab (shelf + conversation-files browser), Trash route, sidebar entry point, interim-memory notice, i18n and copy updates, e2e/mocks. Can start once B/C/D route contracts freeze.

Phase 1's reserved-key wire contract, archive gates, and membership writers are **not** modified by any slice.

## 17. Resolved Decisions

These decisions fix how current configuration reaches a run and how uploads are admitted. Changing either requires updating the relevant contracts and tests, not merely choosing a different implementation detail.

### 17.1 Freshness — current at admission, stable within the run

Both instructions and document discovery use the latest snapshot resolved at admission. Every model call in that run uses it; changes made during the run take effect on the next admission. Clearing instructions removes the old body from the next request; moving out removes both project blocks. No extra turn of delay and no persistent correction are needed. Document reads remain live within the pinned project.

**Revisit if** a future requirement explicitly asks for historical instruction versions or mid-run configuration changes; neither is implied by latest-only injection.

### 17.2 Upload granularity — one file per request

`POST /api/projects/{id}/documents` takes exactly one file. Partial-failure semantics stay out of the response body (an N-file request would have to report N outcomes and pick a status code), one request maps to at most one row or one dedup hit (§10.9), and the UI already loops over dropped files. Batching is a later, additive endpoint if usage asks for it; nothing in the schema or storage layout would have to change.

**Revisit if** the shelf is used for bulk import (dozens of files per action), where per-file round trips dominate the user's time.

Tool registration is deliberately absent from this list: it is settled in the design body — conditional on the run's pinned project context (§7.3, §10.11), because a non-project run must not carry project tool schemas or see project tools at all.
