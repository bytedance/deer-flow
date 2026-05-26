## ADDED Requirements

### Requirement: Backward-compatible legacy User-layer UI

The existing memory settings page (`frontend/src/components/workspace/settings/memory-settings-page.tsx`) and its supporting modules (`frontend/src/core/memory/{api.ts,hooks.ts,types.ts}`) SHALL keep their current behavior unchanged when the layered UI is enabled. Specifically:

- The `useMemory()` hook SHALL continue to query the legacy `GET /api/memory` route and SHALL continue to return data shaped as the existing `UserMemory` interface (`{version, lastUpdated, user:{workContext,personalContext,topOfMind}, history:{...}, facts:[]}`).
- The `useCreateMemoryFact` / `useUpdateMemoryFact` / `useDeleteMemoryFact` / `useClearMemory` / `useImportMemory` mutation hooks SHALL continue to invoke the legacy endpoints (`POST/PATCH/DELETE /api/memory/facts/...`, `DELETE /api/memory`, `POST /api/memory/import`).
- The TanStack Query cache key `["memory"]` SHALL remain reserved for the User-layer legacy view; new layered hooks SHALL NOT write to or invalidate this key.
- Existing `UserMemory` / `MemoryFact` / `MemoryFactInput` / `MemoryFactPatchInput` TypeScript interfaces SHALL remain exported from `core/memory/types.ts` with byte-identical fields. New types are added alongside, not in place of, them.

#### Scenario: Legacy hook returns legacy shape

- **WHEN** an existing component calls `useMemory()` after the layered UI ships
- **THEN** the returned `memory` value SHALL satisfy the existing `UserMemory` TypeScript interface and SHALL contain populated `user`, `history`, and `facts` fields exactly as before

#### Scenario: Legacy mutation does not invalidate layered queries

- **WHEN** `useCreateMemoryFact` succeeds and writes to `["memory"]`
- **THEN** queries keyed under `["memory", "session", ...]` and `["memory", "domain", ...]` SHALL NOT be invalidated as a side effect

#### Scenario: Feature flag off renders unchanged page

- **WHEN** the env var `NEXT_PUBLIC_MEMORY_LAYERED_ENABLED` is unset or `"0"`
- **THEN** the rendered settings page SHALL contain no Tab toggle and SHALL be visually and behaviorally indistinguishable from the pre-change page

### Requirement: Layered TypeScript types extend, not replace, existing schema

The frontend SHALL add new types to `frontend/src/core/memory/types.ts` modeling the backend `MemoryRecord` / `MemoryScope` Pydantic schemas:

- `type MemoryLayer = "session" | "user" | "domain"`
- `interface MemoryScope { layer: MemoryLayer; tenantId: string; userId?: string; threadId?: string; agentName?: string; domain?: string; entityId?: string; }`
- `interface MemoryRecord { id: string; scope: MemoryScope; kind: "preference"|"fact"|"episode"|"domain_assertion"|"context_summary"; content: string; source: "middleware_auto"|"tool_explicit"|"user_manual"|"import"; confidence: number; createdAt: string; validFrom?: string; validTo?: string; decayPolicy?: string; tags?: string[]; metadata?: Record<string, unknown>; }`
- `interface LayeredMemoryFilter { kinds?: MemoryRecord["kind"][]; query?: string; topK?: number; }`
- `interface MemoryTelemetrySummary { memoryWrite: number; memoryRead: number; memoryComposeOutcome: number; memoryForget: number; memoryMigration: number; memoryEmbeddingUnavailable: number; }`

Field naming SHALL use camelCase to follow the existing `UserMemory` / `MemoryFact` convention; the API client SHALL be responsible for case-converting if backend returns snake_case.

#### Scenario: New types coexist with legacy

- **WHEN** the layered types are added
- **THEN** the existing `UserMemory` and `MemoryFact` exports SHALL remain available with unchanged field shapes

#### Scenario: Snake_case backend field surfaced as camelCase

- **WHEN** the backend returns `{"created_at":"2026-05-20T00:00:00Z","valid_from":null,"decay_policy":"never"}`
- **THEN** the parsed `MemoryRecord` SHALL expose those values as `record.createdAt`, `record.validFrom`, `record.decayPolicy`

### Requirement: Layered REST client and TanStack Query hooks

`frontend/src/core/memory/api.ts` SHALL export the following functions for the layered REST API (keyed off `getBackendBaseURL() + "/api/memory/{layer}/records"`):

- `listLayeredRecords(layer: MemoryLayer, scope: Partial<MemoryScope>, filter?: LayeredMemoryFilter): Promise<MemoryRecord[]>`
- `getLayeredRecord(layer: MemoryLayer, recordId: string): Promise<MemoryRecord>`
- `createLayeredRecord(layer: MemoryLayer, body: Omit<MemoryRecord, "id"|"createdAt">): Promise<MemoryRecord>`
- `updateLayeredRecord(layer: MemoryLayer, recordId: string, patch: Partial<Pick<MemoryRecord, "content"|"confidence"|"tags"|"validFrom"|"validTo"|"decayPolicy">>): Promise<MemoryRecord>`
- `deleteLayeredRecord(layer: MemoryLayer, recordId: string): Promise<void>`
- `forgetLayeredRecords(layer: MemoryLayer, filter: LayeredMemoryFilter): Promise<{ deleted: number }>`
- `getMemoryTelemetrySummary(): Promise<MemoryTelemetrySummary>`

`frontend/src/core/memory/hooks.ts` SHALL expose corresponding TanStack Query hooks:

- `useLayeredMemoryRecords(layer, scope, filter?)` — `useQuery` keyed `["memory", layer, scopeKey(scope), filterKey(filter)]`
- `useCreateLayeredRecord(layer)`, `useUpdateLayeredRecord(layer)`, `useDeleteLayeredRecord(layer)`, `useForgetLayeredMemory(layer)` — `useMutation`, on success invalidate `["memory", layer]` (any sub-key)
- `useMemoryTelemetrySummary()` — `useQuery` keyed `["memory-telemetry-summary"]` with refetch interval 30s

`scopeKey(scope)` SHALL produce a stable JSON-serializable key by emitting fields in fixed alphabetical order so identical scopes produce identical cache keys regardless of object construction order.

#### Scenario: Stable cache key across object orderings

- **WHEN** `useLayeredMemoryRecords("domain", {tenantId:"t1", domain:"equipment", entityId:"pump-123"})` and `useLayeredMemoryRecords("domain", {entityId:"pump-123", domain:"equipment", tenantId:"t1"})` are called in the same render
- **THEN** the two calls SHALL share a single TanStack Query cache entry

#### Scenario: Mutation invalidates only its layer

- **WHEN** `useCreateLayeredRecord("session")` succeeds
- **THEN** queries keyed under `["memory", "session", ...]` SHALL be invalidated and queries keyed `["memory"]` (legacy) and `["memory", "user", ...]` / `["memory", "domain", ...]` SHALL NOT be invalidated

#### Scenario: Telemetry hook polls every 30 seconds

- **WHEN** `useMemoryTelemetrySummary()` is mounted
- **THEN** the hook SHALL refetch automatically with an interval of approximately 30 seconds and SHALL NOT trigger refetch on window focus

### Requirement: Three-Tab UI on memory settings page

`frontend/src/components/workspace/settings/memory-settings-page.tsx` SHALL render a top-level Tab toggle with three options when `process.env.NEXT_PUBLIC_MEMORY_LAYERED_ENABLED === "1"`:

- **User** (default selection) — renders the existing `MemorySettingsPage` body unchanged.
- **Session** — renders a Session-layer view scoped to a `thread_id` resolved from the current URL (`/workspace/chats/[thread_id]` or `/workspace/agents/[agent_name]/chats/[thread_id]`); when no thread is active, renders an empty state with a CTA "open a chat first" — no thread picker is added to the settings page itself.
- **Domain** — renders a Domain-layer view with a `domain` dropdown and an `entity_id` text input as filters.

When the feature flag is unset or "0", the Tab toggle SHALL NOT render and the page SHALL behave identically to the pre-change page.

#### Scenario: Default tab is User

- **WHEN** the user navigates to `/workspace/settings/memory` with the flag enabled
- **THEN** the User Tab SHALL be the active selection on first render

#### Scenario: Session tab uses URL-resolved thread

- **WHEN** the user is on `/workspace/chats/thr_abc/settings/memory` and selects the Session Tab
- **THEN** the rendered records SHALL be those of `thread_id="thr_abc"` and no thread picker SHALL be shown in the Tab body

#### Scenario: Session tab without active thread shows empty state

- **WHEN** the user opens the Session Tab from `/workspace/settings/memory` (no thread in URL)
- **THEN** the body SHALL display an empty state and SHALL NOT call `listLayeredRecords("session", ...)`

### Requirement: Permission-driven read-only and write affordances

The UI SHALL infer write permission per layer from backend responses, not from a client-side role check:

- On Tab activation, the layered list query SHALL be issued; if it returns 200 OK, the Tab is reachable. If it returns `403 MEMORY_FORBIDDEN`, the Tab body SHALL render an "insufficient permissions" message and SHALL NOT issue further requests in that Tab.
- The "Create" / "Edit" / "Delete" buttons SHALL be optimistically rendered for User Tab (always — user owns their data) and Session Tab (read + Promote only — no Create / Delete buttons by default since session writes are agent-driven), and SHALL be conditionally rendered for Domain Tab.
- For Domain Tab, the "Create" button visibility SHALL be controlled by attempting an empty-body `POST /api/memory/domain/records` probe is NOT acceptable; instead, the UI SHALL hide the "Create" button by default and reveal it only after the user clicks an explicit "Try as admin" link, which surfaces any 403 as a toast — avoiding silent permission probes.
- Any write that returns 403 SHALL display a localized toast via `memoryErrorToastText("MEMORY_FORBIDDEN", locale)` and SHALL NOT mutate local state.

#### Scenario: Forbidden read renders permission message

- **WHEN** `listLayeredRecords("domain", scope)` returns 403 with body `{"detail":"insufficient role","code":"MEMORY_FORBIDDEN"}`
- **THEN** the Domain Tab body SHALL render an "insufficient permissions" message and SHALL NOT retry automatically

#### Scenario: Forbidden write surfaces localized toast

- **WHEN** a regular user clicks "Try as admin" then submits a Domain record and the response is 403 `MEMORY_FORBIDDEN`
- **THEN** a toast with bilingual text from `memoryErrorToastText("MEMORY_FORBIDDEN", locale)` SHALL be shown and the local list SHALL NOT optimistically update

### Requirement: Stable error code module mirroring backend

`frontend/src/core/memory/errors.ts` SHALL define and export a stable enum of error codes that mirrors the backend `memory-management-api` error envelope (`{detail, code}`):

```ts
export type MemoryErrorCode =
  | "MEMORY_NOT_FOUND"
  | "MEMORY_FORBIDDEN"
  | "MEMORY_VALIDATION"
  | "MEMORY_STORAGE"
  | "MEMORY_EMBEDDING_UNAVAILABLE";

export class LayeredMemoryError extends Error {
  constructor(public code: MemoryErrorCode, public detail: string) { super(detail); }
}

export function memoryErrorToastText(
  code: MemoryErrorCode,
  locale: "en-US" | "zh-CN",
): string;
```

The `api.ts` layered functions SHALL throw `LayeredMemoryError` whenever the response contains a recognized `code` field, so callers can `instanceof`-check for localized handling. Non-coded errors SHALL throw a plain `Error` with the server's `detail` string (matching the existing `readMemoryResponse` pattern).

A unit test in `frontend/tests/unit/core/memory/errors.test.ts` SHALL fail when the enum drifts from the backend's `MemoryService` typed exception set; adding a new code SHALL require touching both files in lockstep, identical to the convention established by [`core/uploads/conversion-errors.ts`](frontend/src/core/uploads/conversion-errors.ts).

#### Scenario: Coded 404 throws typed error

- **WHEN** `getLayeredRecord("user", "missing")` receives `{"detail":"not found","code":"MEMORY_NOT_FOUND"}` with status 404
- **THEN** the caller SHALL receive a thrown `LayeredMemoryError` with `code="MEMORY_NOT_FOUND"` and `detail="not found"`

#### Scenario: Bilingual toast text

- **WHEN** `memoryErrorToastText("MEMORY_EMBEDDING_UNAVAILABLE", "zh-CN")` is called
- **THEN** the returned string SHALL contain Chinese localized copy distinct from the en-US variant

#### Scenario: Drift detection fails on missing code

- **WHEN** the backend `MemoryService` adds a new exception class without a matching frontend `MemoryErrorCode` entry
- **THEN** the conformance test in `frontend/tests/unit/core/memory/errors.test.ts` SHALL fail

### Requirement: Promote session record to user layer

The Session Tab SHALL expose a "Promote to User" button per record. Clicking it SHALL invoke `createLayeredRecord("user", {...})` with the record's `kind`, `content`, `confidence`, and `metadata.promoted_from = <session_record_id>`. The original Session record SHALL NOT be deleted by the promote action; the user retains the option to delete it explicitly.

After successful promotion, both the Session list and the User list SHALL reflect the change without a page reload (User cache invalidation only — Session cache need not be invalidated since the source record is unchanged).

#### Scenario: Promote creates user record with back-reference

- **WHEN** a session record `{id:"sess_1", content:"用 PDF 不要 Markdown", kind:"preference", confidence:0.9}` is promoted
- **THEN** a new User-layer record SHALL be created with the same `content`/`kind`/`confidence` and `metadata.promoted_from === "sess_1"`

#### Scenario: Promote does not delete session source

- **WHEN** the promote operation succeeds
- **THEN** the session record `sess_1` SHALL still appear in the Session Tab list

#### Scenario: Promote invalidates only user cache

- **WHEN** the promote mutation resolves
- **THEN** TanStack Query SHALL invalidate `["memory", "user"]` (sub-keys) and `["memory"]` (legacy User view), and SHALL NOT invalidate `["memory", "session", ...]`
