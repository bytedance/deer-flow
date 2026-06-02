## ADDED Requirements

### Requirement: BlockPersistContext provides pluggable persistence

The system SHALL provide a `BlockPersistContext` React Context that exposes a `saveContent` function. GenUI components consume this context to persist edited content without depending on specific backend APIs.

#### Scenario: Context is provided
- **WHEN** a parent component wraps GenUI blocks in `<BlockPersistProvider saveContent={...}>`
- **THEN** child components receive the `saveContent` function via `useBlockPersist()`

#### Scenario: Context is absent
- **WHEN** no `<BlockPersistProvider>` is present in the component tree
- **THEN** `useBlockPersist()` returns `null`, and components fall back to in-memory-only behavior

### Requirement: MarkdownBlock persists edits through Context

MarkdownBlock SHALL call `saveContent` from BlockPersistContext on save. When Context is unavailable, it SHALL fall back to updating the Zustand store only.

#### Scenario: Save in report context
- **WHEN** user edits markdown content and clicks Save in a report detail page
- **THEN** the system calls `saveContent(blockId, content)` from Context, which persists changes to the backend `report_payload.json`

#### Scenario: Save in chat thread context (no Context)
- **WHEN** user edits markdown content and clicks Save in a chat thread where no BlockPersistProvider exists
- **THEN** the system updates only the in-memory Zustand store and shows a success toast

#### Scenario: Save failure handling
- **WHEN** the `saveContent` call fails (network error, auth error, etag conflict)
- **THEN** the system shows an error toast and keeps the editor open with the edited content preserved

### Requirement: PUT endpoint updates report payload

The system SHALL provide `PUT /api/report-runs/{report_run_id}/payload` that accepts `{ sections: [...] }` and overwrites `report_payload.json` on disk.

#### Scenario: Successful update
- **WHEN** an authenticated user PUTs valid sections to the payload endpoint
- **THEN** the server overwrites `report_payload.json` and returns 200

#### Scenario: Payload not yet assembled
- **WHEN** the report run has no `report_payload_path` (payload not assembled)
- **THEN** the server returns 404 with detail "payload not assembled yet"

#### Scenario: Payload file missing
- **WHEN** the payload path exists in the record but the JSON file is gone
- **THEN** the server returns 410 with detail "payload file gone"
