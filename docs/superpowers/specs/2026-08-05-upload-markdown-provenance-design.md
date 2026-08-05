# Explicit Upload Markdown Provenance in Agent Context — Design

## Background

The upload API already returns the actual Markdown companion created for a
converted document through `markdown_file`. That filename is necessary when
multiple source files share a stem: for example, `a.docx` and `a.pdf` can map
to `a.md` and `a_1.md` respectively.

The web submit path currently drops `markdown_file` when it converts an upload
response into `additional_kwargs.files`. `UploadsMiddleware` therefore sees
only the source filename and reconstructs the companion as `<stem>.md`. In the
example above, both source documents can be grounded with the outline from
`a.md`, so the agent receives context from the wrong document.

This is the current-turn grounding slice of issue #3750. Historical upload
provenance, storage layout, and deletion ownership require separate product and
migration decisions and are deliberately excluded from this change.

## Goals

1. Preserve the upload API's explicit source-to-Markdown relationship through
   the web message contract and into `UploadsMiddleware`.
2. Make current-turn outline and preview extraction use the explicit companion
   when present, including collision-renamed files such as `a_1.md`.
3. Distinguish a new client that explicitly reports no companion from an old
   message that predates the provenance field.
4. Reject unsafe or stale companion metadata without exposing its raw value to
   the model.
5. Preserve legacy behavior for old messages and clients that omit the field.

## Non-goals

- Persisting a source-to-companion manifest for historical uploads.
- Changing `list_uploaded_files` historical discovery.
- Changing conversion output names or storage directories.
- Changing upload replacement, collision, or deletion behavior.
- Rendering the Markdown companion as a separate attachment in the UI.
- Adding a new dependency or changing the public upload API response.

## Chosen Approach

Carry the existing `markdown_file` response field end to end:

```text
UploadResponse.files[].markdown_file
  -> FileInMessage.markdown_file
  -> HumanMessage.additional_kwargs.files[]
  -> UploadsMiddleware._files_from_kwargs
  -> exact Markdown path under the thread uploads directory
  -> outline / preview injected into <current_uploads>
```

This fixes the provenance loss at its source. It is preferable to scanning for
`<stem>_N.md` candidates, which cannot establish ownership, and to embedding
the full outline in the browser message, which would couple upload transport to
agent prompt construction and enlarge persisted messages.

## Frontend Contract

`UploadedFileInfo.markdown_file` and `FileInMessage.markdown_file` use
`string | null` semantics:

- A filename string means conversion produced that exact companion.
- `null` means the current upload response explicitly reported no companion.
- An absent key means legacy metadata whose producer did not support explicit
  provenance.

The submit flow maps upload responses through one pure conversion helper rather
than maintaining two object literals. Both the optimistic human message and the
actual `thread.submit` payload use the helper, preventing the two paths from
drifting. The helper always writes the key for a new upload response, using
`null` when the API value is absent or null.

No attachment UI reads or renders `markdown_file`; it remains structured
transport metadata.

## Backend Validation and Resolution

`UploadsMiddleware._files_from_kwargs` continues to rebuild the source virtual
path rather than trusting the browser. When `markdown_file` is present, it also
normalizes the companion metadata:

- `null` is preserved as an explicit no-companion value.
- A string is accepted only when it is a basename with no directory component,
  has a case-insensitive `.md` suffix, is not an upload staging filename, and
  resolves to an existing regular file inside the current thread uploads
  directory.
- Any other value, traversal-shaped name, wrong extension, staging name, or
  missing file is normalized to `null` and logged without rejecting the source
upload.

The existence check applies when the thread uploads directory is available.
When it is unavailable, the middleware may preserve a shape-valid filename for
structured state, but outline extraction remains skipped exactly as it is
today.

Outline extraction follows a tri-state rule:

1. Valid explicit filename: read exactly that Markdown file.
2. Explicit `null` or invalid explicit metadata: inject no outline or preview;
   never guess a sibling.
3. Field absent: use the existing `<stem>.md` lookup for backward compatibility.

The file-outline module exposes an exact-Markdown-path extraction function and
keeps `extract_outline_for_file` as the legacy sibling-lookup wrapper. This
separates provenance resolution from outline parsing and avoids changing other
callers.

The raw companion filename is not rendered in `<current_uploads>` and is not
presented to the model. Only the existing sanitized outline or preview is
injected.

## Error Handling and Observability

Companion metadata is optional enrichment. A malformed or missing companion
must not discard an otherwise valid source upload and must not fail an agent
run. The middleware records a bounded diagnostic message containing the source
filename and rejection reason, then proceeds with an empty outline for that
file.

File read and Markdown parsing failures retain the existing best-effort
behavior: return an empty outline/preview and continue the run. No new user-
visible error is introduced.

## Testing Strategy

Implementation follows red-green-refactor. Each regression test is executed
before production changes and must fail because provenance is currently lost.

### Frontend unit tests

- A collision-renamed companion such as `a_1.md` is preserved by the pure
  upload-response-to-message mapper.
- An omitted or null API companion becomes an explicit `markdown_file: null`.
- `buildThreadSubmitMessages` keeps the resulting field on the visible human
  message only.

### Backend unit tests

- `_files_from_kwargs` preserves a valid existing `.md` basename.
- Explicit null remains distinguishable from an absent legacy key.
- Traversal names, wrong extensions, staging names, non-string values, and
  missing files are normalized to explicit no-companion metadata.
- With `a.pdf`, conflicting `a.md`, and explicit `a_1.md`, the injected context
  contains only the outline from `a_1.md`.
- Explicit null does not fall back to a conflicting `a.md`.
- A legacy message without the key still uses the existing `a.md` sibling; the
  existing regression test remains green.

### Focused and broader verification

- Run the focused frontend mapper and submit-message tests.
- Run the focused backend upload middleware tests.
- Run the strict blocking-I/O upload middleware anchor.
- Run frontend type checking and lint for the modified frontend contract.
- Run Ruff check and format verification for modified backend files.
- Run the repository's static blocking-I/O detector to ensure the changed
  middleware path introduces no new finding.

## Files and Responsibilities

- `frontend/src/core/uploads/api.ts`: represent the API's nullable companion.
- `frontend/src/core/uploads/message-files.ts`: map an upload response to stable
  message metadata.
- `frontend/src/core/messages/utils.ts`: extend `FileInMessage` with the
  optional provenance field.
- `frontend/src/core/threads/hooks.ts`: use the shared mapper for optimistic and
  submitted messages.
- `frontend/tests/unit/core/uploads/message-files.test.ts`: pin frontend
  provenance mapping.
- `frontend/tests/unit/core/threads/send-message.test.ts`: pin preservation in
  the submitted human message.
- `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`:
  validate companion metadata and select explicit versus legacy resolution.
- `backend/packages/harness/deerflow/utils/file_outline.py`: parse an exact
  Markdown path while retaining the legacy source-file wrapper.
- `backend/tests/test_uploads_middleware_core_logic.py`: reproduce the grounding
  collision and validate compatibility and unsafe-input behavior.

## Compatibility and Rollout

The upload API response is unchanged. New web messages add one nullable field
inside the existing unversioned `additional_kwargs.files` dictionaries. Backend
parsing remains tolerant of unknown keys and old messages without the field.
This permits frontend and backend rolling upgrades in either order:

- New frontend with old backend: the extra key is ignored.
- Old frontend with new backend: legacy sibling lookup remains active.

## Success Criteria

1. A current-turn source file uses its API-reported Markdown companion even
   when that companion has a collision suffix.
2. A current-turn upload with no companion cannot accidentally consume another
   file's same-stem Markdown.
3. Unsafe companion metadata cannot escape the thread uploads directory or
   cause unrelated content to enter agent context.
4. Old messages continue to receive their existing sibling-outline behavior.
5. Focused tests, type checks, linters, and the blocking-I/O regression anchor
   pass without new warnings attributable to this change.
