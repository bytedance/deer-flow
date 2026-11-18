# DeerFlow Projects MVP — Phase 2 Implementation Plan

**Date**: 2026-09-13
**Spec revision note (2026-09-13)**: the spec's injection strategy was replaced mid-implementation. §7.2 is now **latest-only, request-scoped**: `DynamicContextMiddleware` gains `wrap_model_call`/`awrap_model_call` hooks rendering ONE transient HumanMessage per model call from the admission-pinned snapshot. The persisted identity block, `project_context_revision` in `additional_kwargs`, `__project` corrections, and `<project_update>` notices from the previous revision are abandoned (forbidden by §15 items 18-19). `_build_full_reminder`/`_inject`/date/`__memory` behavior stays byte-identical to main.
**Branch**: `projects-mvp-phase2` (worktree `../deer-flow-phase2`, base `main @ 6f81daef`)
**Scope rule**: every design decision, error mapping, and review-gate is owned by the spec. This document sequences files, symbols, and verification only. Where the spec and code disagree, the spec's deviation register (§10) wins.

## Slice map (spec §16 dependency order)

| Slice | Deliverable | Depends on |
| --- | --- | --- |
| A | Instructions injection end-to-end (config, admission pin, middleware identity half, markers, prompt, journal, frontend Instructions tab) | — |
| B | Shelf storage + delivery + reads (table/migration, Paths, routes, request-scoped `<documents>` block, tools, project-delete trash transition) | A |
| C | Promotion both ways + thread-files view (from-thread, attach-to-thread, thread-files) | B |
| D | Trash completion (restore/purge/empty, retention sweep, reconciliation) | B |
| E | Frontend completion (Documents tab, Trash route, sidebar, copy, e2e) | B/C/D contracts |

Sequencing: A → B → {C, D} → E. C and D are independent of each other once B lands; they still ship serially here because both touch `routers/` mounting, PAT allowlist, and i18n dictionaries.

## Slice A — Instructions injection

**Backend**

1. `config/projects_config.py` (new): `ProjectsConfig(BaseModel)` — `instructions_max_bytes=8192 (256..262144)`, `shelf_index_max_entries=50 (1..500)`, `shelf_index_max_bytes=4096 (512..65536)`, `trash_retention_days=30 (1..3650)`; follow `read_before_write_config.py` shape. Wire `AppConfig.projects` in `config/app_config.py` (invalid/missing → defaults + warning, `_get_upload_limit` idiom). Add `projects:` block to `config.example.yaml`.
2. `routers/projects.py`: enforce UTF-8 byte cap on `instructions` in create + patch → 422 over cap (never truncate). Uses `AppConfig.projects.instructions_max_bytes`.
3. `runtime/context_keys.py`: add `PROJECT_CONTEXT_KEY: Final[str] = "__deerflow_project_context"`. Add to BOTH server-owned sets: `app/gateway/services.py` pop-set (`:435-446`) and `runtime/runs/worker.py::_SERVER_OWNED_RUNTIME_CONTEXT_KEYS`.
4. `deerflow/projects/__init__.py` + `deerflow/projects/context.py` (new): `resolve_project_context(thread_store, thread_id, user-scoped) -> dict | None` — one async resolution: `threads_meta.project_id` → owner-scoped project row `status IN ('active','archived')` → pinned snapshot dict `{project_id, name, instructions}` (shelf fields arrive in B). Failure → warning log + `None` (never fails the run).
5. `app/gateway/services.py`: in shared run-create path (~`:1455-1490`, after `inject_authenticated_user_context`, before `create_or_reject`) call the resolver and set `config["context"][PROJECT_CONTEXT_KEY]` when resolved; non-fatal on error, mirroring `_ensure_thread_metadata`.
6. `DynamicContextMiddleware` (`agents/middlewares/dynamic_context_middleware.py`) — request-scoped project block per new §7.2:
   - Gain `wrap_model_call`/`awrap_model_call` hooks backed by PURE rendering helpers in `deerflow/projects/context.py` (no DB/FS I/O, no memory-retrieval dependency). Existing `_build_full_reminder`/`_inject`/date correction/`__memory` persistence UNCHANGED.
   - Render at most one transient HumanMessage per model call: `<project id="…" name="…">{instructions}</project>` from `runtime.context[PROJECT_CONTEXT_KEY]` (Slice A: no `<documents>`). Attribute values escape quotes/ampersands/angle brackets; instructions through `neutralize_untrusted_tags`.
   - Idempotent request assembly: reserved message-ID prefix + server-owned `deerflow_project_context` marker + provenance in `additional_kwargs` identify the transient message; each assembly removes only its own recognized transient messages from the REQUEST COPY, then inserts one fresh message. Never remove user messages by text or ID-prefix alone. `hide_from_ui` yes; NEVER `dynamic_context_reminder`; never a state update; never in checkpoints.
   - Admission strips client-supplied `deerflow_project_context` markers from message metadata (§12).
   - Placement: immediately before the genuine current-run user message via server-owned run/message identity; stable across the tool loop (never between assistant tool call and result, never appended per tool result); resumed/internal fallback = after leading SystemMessages; anchor recomputed from the current request after compaction.
   - Latest-only semantics: rename/edit/move take effect next run; no corrections, no history comparison. Empty instructions keep identity, omit body; unassigned run renders nothing.
7. `input_sanitization_middleware.py`: `_BLOCKED_TAG_NAMES` gains `"project"` ONLY in Slice A (`"documents"` lands with B). Update `test_input_sanitization_middleware.py::test_denylist_covers_framework_authority_blocks` by classification.
8. `agents/lead_agent/prompt.py:558-564`: rewrite trust passage — distinguish user-role `<memory>` data and request-scoped project data from framework rules; tag escaping grants no system authority.
9. `runtime/journal.py`: `record_memory_context` payload → `{content_sha256: str|None, project_context_revision: str|None, project_shelf_revision: str|None}`. `content_sha256` covers only the existing `__memory` message (null when absent); `project_context_revision` = sha256(rendered `<project>` text) or null; `project_shelf_revision` null in A. Fingerprints only — never compared, never stored in kwargs. Emit once per run at first model-request assembly after delivery is known, when memory OR the project block is supplied (including project-only runs without `__memory`); failed assembly claims nothing; readers tolerate old payloads.
10. `tests/blocking_io/`: middleware already anchored; no new async FS paths in A.
11. `core/messages/utils.ts::INTERNAL_MARKER_TAGS` + `core/threads/export.ts` scrub: add `"project"` and `"documents"` (spec §7.2 end state; `project_update` does not exist in the revised design).
12. Project page `app/workspace/projects/[id]/page.tsx`: tabs (Chats / Documents-placeholder / Instructions / Settings) following `app/workspace/chats/page.tsx:130-138` Tabs pattern. Instructions tab: `Textarea` + save via `usePatchProject`, live UTF-8 byte counter, client guard mirroring 422.
13. i18n: new keys in `locales/types.ts`, `en-US.ts`, `zh-CN.ts` together.

**Tests (A)**: instructions cap boundary (exact/one-over, CJK bytes, create+patch); latest-instructions matrix (rename/edit/clear/move-in/move-out change the NEXT run's request only — no old instructions, no correction messages; empty instructions keep identity; unassigned renders nothing); request-only delivery (exactly one current project message per model call incl. retries; none in checkpoints before/after; idempotent reassembly of an already-decorated request; forged marker/ID cannot suppress/replace; placement before current genuine user message; tool-loop stability; resumed/internal fallback; post-compaction re-anchor); admission strips client-supplied `PROJECT_CONTEXT_KEY` (both sets) + `deerflow_project_context` message markers; resolution failure degrades to unassigned; journal identity (project-only runs, empty instructions, repeated calls, failed assembly, old-payload readers); config defaults/bounds; PAT unchanged (no new routes in A); frontend DOM for Instructions tab.

## Slice B — Shelf storage, delivery, reads

**Backend**

1. `persistence/projects/model.py`: `ProjectDocumentRow` per spec §6.1 table (no `mime`/`is_text`/`version`/`deleted_by`).
2. Migration `0024_project_documents` (renumbered from `0023` after the rebase; head `0023_user_preferences`): `op.create_table` + 4 indexes, `inspector.has_table` guard (`0019_projects.py:22-23` idiom). Update head pin in `tests/test_persistence_forward_revision_compat.py`; `persistence/migrations/AGENTS.md` head note.
3. `persistence/projects/sql.py`: `ProjectDocumentRepository` — `insert_active`, `find_active_by_sha256`, `list_active`, `count_active`, `shelf_snapshot`, `get`, `trash`, `trash_all_for_project` (ContextVar owner filter, `AUTO` sentinel, `projects` row lock with `status='active'` + `with_for_update()`, SQLite `BEGIN IMMEDIATE` idiom from Phase 1).
4. `config/paths.py`: `user_projects_dir`, `user_project_dir`, `project_documents_dir`, `project_document_path` (join + confinement re-check), `_validate_user_id`-style safe-id checks on `project_id`. Layout per §6.2: `{sha256[:2]}/{sha256}/{document_id}/original/{name}`, `derived/converted.md`, `.staging/{uuid}`.
5. `deerflow/projects/documents.py` (new): shelf service — stage→hash→fresh doc id→(tx: lock active project→dedup select→place bytes→insert) per §6.3; dedup hit removes staging, returns existing row (first name wins, §10.9); text detection via extracted shared helper; conversion via `convert_file_to_markdown` honoring `uploads.auto_convert_documents`.
6. Extract `is_text_file_by_content` from `routers/artifacts.py:235` → `deerflow/utils/` shared module; update router import.
7. `routers/project_documents.py` (new, mounted in `app.py:create_app` beside `projects.router`): `GET ""`, `POST ""` (multipart exactly-one-file, 201/200 dedup, 413/400 mirroring uploads router), `GET "/{document_id}/content"` (`download` flag), `DELETE "/{document_id}"` → 204 (trash via repository). 404 fail-closed everywhere; 503 `"Projects"` via `deps.py` `_require` + new `project_document_repo` accessor; archived-project matrix per §8.4/§11.
8. `ProjectRepository.delete`: gain statement 2 (trash all active shelf rows with `trash_origin` snapshot) inside its existing transaction/lock (§8.1).
9. Admission resolver (`projects/context.py` from A): extend pinned snapshot with bounded shelf `{"total", "entries"}` (`shelf_index_max_entries + 1` fetch, `updated_at DESC, id ASC`; +1 never rendered) — `shelf_snapshot` one round trip.
10. Middleware: extend A's transient request-scoped message with the `<documents>` block appended after `</project>` (rendered per model call from the pinned snapshot, never persisted); line-atomic caps (entries + bytes, wrapper/overflow reserved, no partial entry); header `count`/`shown` honest + overflow note naming `list_project_documents`; `project_shelf_revision = sha256(rendered text)` → journal payload only. `"documents"` joins `_BLOCKED_TAG_NAMES` + the drift guard in this slice (spec §16).
11. `deerflow/projects/tools.py` (new): `list_project_documents(offset, limit≤200)`, `read_project_document(document_id, offset, limit≤20000 chars)`; `project_id` from pinned context, `user_id` from `resolve_runtime_user_id`; fail closed (tool error) without pin/session; binary decline naming attach-to-thread; trashed → "no longer on the shelf"; all FS reads offloaded. Conditional registration in `agents/lead_agent/agent.py` — append only when `PROJECT_CONTEXT_KEY` present, via generalized collision-skipping helper (from `_append_memory_tools_without_name_conflicts`); both assembly-descriptor variants pinned. Subagents excluded.
12. `auth/pat.py` allowlist: add B routes; extend `test_pat_auth.py::test_pat_projects_policy_admits_exactly_the_mounted_routes`.
13. `tests/blocking_io/`: anchors for upload staging/rename, conversion, tool reads (mutation-verified).

**Frontend (B)**: delete confirmation copy change (en-US + zh-CN, `en-US.ts:357-358` region); nothing else user-visible until E (Documents tab scaffolding may render shelf read-only if trivial, but full tab is E).

**Tests (B)**: repository (dedup/trashed filter/snapshot ordering), index rendering caps/escaping/overflow-note, shelf delivery (exactly one block per request, never persisted, empty-shelf absence), tools (slice boundaries, clamp, binary decline, conversion on/off, fail-closed, live-edit visibility), archived matrix, project-delete trashes shelf, filename 255/256 boundary, concurrency (upload vs delete, duplicate upload, conversion vs purge-adjacent trash), PAT drift guard, migration upgrade/downgrade, blocking-IO anchors.

## Slice C — Promotion and file browser

**Backend**

1. Extract shared thread-upload ingestion service from `routers/uploads.py` (staging, `claim_unique_filename`, size checks, optional conversion, permissions, non-mounted-provider sandbox sync via authorized lease; denied `sandbox:execute` retains host upload without allocation).
2. `routers/project_documents.py`: `POST "/from-thread"` (`{thread_id, kind, name, shelf_name?}`; source confined to that thread's uploads/outputs; records `source_thread_id/source_kind/source_name`), `POST "/{document_id}/attach-to-thread/{thread_id}"` (stage stable copy under doc lock → ingestion service owns target lifecycle; returns `{filename, size_bytes, virtual_path, artifact_url}` only on success; archived source allowed).
3. `routers/project_thread_files.py` (new): `GET ""` — paged member threads (`thread_limit`≤50), per-thread uploads via `list_files_in_dir(sandbox_uploads_dir)` + NEW outputs listing helper over `sandbox_outputs_dir`; per-thread `file_limit`; `truncated` flag; `next_offset` thread cursor.
4. PAT allowlist + drift guard extension.

**Frontend (C contracts land here, UI in E)**: hooks `usePromoteThreadFile`, `useAttachProjectDocument`, `useProjectThreadFiles` in `core/projects/`.

**Tests (C)**: from-thread confinement/404, provenance columns consumed, attach parity (mounted/non-mounted, denied sandbox:execute, failure cleanup), thread-files paging/truncation, concurrency (attach vs purge serialization).

## Slice D — Trash completion

**Backend**

1. Repository: `restore` (outcome enum `restored|merged|not_found|no_target|content_missing`; lock order target-project→docs in ID order; no file moves; read-only content check under source lock; merge cleanup post-commit), `purge_candidates(retention_days)`, `purge` (continuous row lock across validate→unlink→delete→commit; `FileNotFoundError` = already removed; other unlink errors roll back, retryable).
2. `routers/trash.py` (new): `GET "/documents"` (lazy sweep trigger), `POST "/documents/{id}/restore"`, `POST "/documents/{id}/purge"` (204), `POST "/purge"` (`{purged: int}`). Restore target = body else `trash_origin.project_id` when active/owned; else 404.
3. Retention sweep service: `purge_candidates` + guarded purge; orphan reconciliation (`.staging/*` and unreferenced files under `projects/*/documents/` older than 24h removed; row-side missing/size-mismatch → log warning + `content_missing` surfacing, NEVER auto-delete row); startup trigger in `app.py` lifespan; lazy trigger on trash listing. `rmdir` empty parents best-effort.
4. Content endpoint + tools: explicit `content_missing` error for missing/mismatched files.
5. PAT allowlist + drift guard.

**Tests (D)**: restore outcome matrix incl. 409 `content_missing`, purge ordering (injected `OSError` retains row; missing optional conversion OK; commit failure retryable), retention boundary exactly at `retention_days`, 24h orphan guard, reconciliation never deletes, concurrency (purge vs restore barriers, both lock orders, restore vs project delete), sweep lazy + startup triggers.

## Slice E — Frontend completion

1. Documents tab: shelf area (upload button + drag-drop one-file-per-request loop, rows via `ArtifactFileList` pattern, provenance badge, preview via `ArtifactFilePreview`/`ArtifactViewer`, download, attach-to-thread, move-to-trash with trash-naming confirmation, `content_missing` row rendering) + conversation-files browser (grouped by thread, Save to project).
2. `/workspace/trash` route (NOT under `/workspace/projects/`): rows with origin project + remaining retention, Restore (project picker fallback), Delete-permanently + Empty trash with explicit irreversible confirmations.
3. Sidebar `ProjectsSection` Trash entry; static-demo `null` guards (`isStaticWebsiteOnly()`); move menu untouched.
4. Archived read-only banner on project page Documents area.
5. Interim memory notice (RFC §10 copy) on project page + Documents empty state.
6. Hooks: `useProjectDocuments`, `useUploadProjectDocument`, `useDeleteProjectDocument`, `useTrashDocuments`, `useRestoreDocument`, `usePurgeDocument`, `useEmptyTrash` (+ C's three); query keys per spec §9; invalidation per `invalidateProjectCaches`.
7. i18n keys (types/en-US/zh-CN together); e2e mocks in `tests/e2e/utils/mock-api.ts` + Playwright flows; no `<project>` text leaking into rendered messages.

## Documentation (land with owning slice)

- `README.md` (E), `backend/docs/API.md` (B/C/D routes), `backend/docs/ARCHITECTURE.md` (B shelf layout/pinning/authority split; D trash tier), `persistence/migrations/AGENTS.md` (B), `app/gateway/AGENTS.md` admission-pin contract (A), `config.example.yaml` (A).

## Verification gates

- After each slice: `cd backend && make lint && make test` (targeted first, then full suite at slice end).
- Frontend slices: `cd frontend && pnpm lint && pnpm typecheck`; `BETTER_AUTH_SECRET=local-dev-secret pnpm build` at E.
- Spec §15 review checklist re-read before finalizing each slice (esp. gates 1-8, 11-12, 18-20).
- Concurrency tests are a hard requirement (spec §13), not optional polish.
