# API Access and Python Client

## Existing-Run Stream Actions

Existing-run SSE joins are observation-only on `GET`: supplying
`action=interrupt|rollback` returns `405`. Cancellation on this stream route is
`POST`-only and requires the `runs:cancel` permission. Accordingly, the OpenAPI
contract exposes `action` and `wait` only on `POST`; the `GET` operation exposes
only its path parameters.

## Personal Access Tokens

Non-interactive clients (CI pipelines, scripts, server-to-server integrations)
can call the Gateway API with a **personal access token (PAT)** instead of a
browser session. Create one while logged in via `POST /api/v1/auth/pats` — the
raw `dfp_...` value is shown exactly once; only its SHA-256 digest is stored —
then send it as a Bearer credential:

```http
POST /api/threads/search
Authorization: Bearer dfp_...
Content-Type: application/json

{}
```

Each token runs with its owning user's identity (owner filtering and per-user
memory keep working), carries a scope set that can only narrow that user's
permissions, and is admitted only to the thread/run lifecycle routes — every
other route answers `403` to PAT callers, and a PAT never carries admin
capability. Tokens can be listed and revoked at any time; revocation is
immediate. PATs require a database backend (SQLite/PostgreSQL). Full
reference: [API Reference — Personal Access Tokens](../../backend/docs/API.md#personal-access-tokens).

## Embedded Python Client

User messages are framed as untrusted input. Reserved XML-like tags are escaped
for model context only when present; tag-free URLs and shell commands retain
their ampersands unchanged. Encoded payloads include a note to decode exactly
once when reproducing the original text in files, code, or tool-call arguments. This preserves XML
angle brackets and literal HTML entities in verbatim-content requests while
keeping user-supplied tags separate from framework instructions. Copied encoding
notes are treated as user text; only request-local program state permits reuse
of an already encoded frame.

`chat()` and `stream()` preserve text appended by model middleware before the
first state snapshot, emitting only the suffix after the streamed text.

For `DeerFlowClient(agent_name="researcher")`, the named agent's `mcp_plugins`
selection applies to both the lead agent and its `task` / `batch_task`
delegations: `null` inherits all enabled MCP plugins, `[]` selects none, and
installation IDs select only those plugins. Call `client.reset_agent()` after
editing the saved agent configuration to refresh the selection.

`DeerFlowClient.stream()` includes `summary_text` in each `values` event. This is the current compacted context summary, or `None` when absent. Consumers can record changes without reading checkpoint internals; repeated snapshots may carry the same summary, and an initial snapshot may already contain one from an earlier turn.

DeerFlow can be used as an embedded Python library without running the full HTTP services. The `DeerFlowClient` provides direct in-process access to all agent and Gateway capabilities, returning the same response schemas as the HTTP Gateway API.

The HTTP Gateway exposes `DELETE /api/threads/{thread_id}` to remove a thread's
files, checkpoints, and metadata. If checkpoint deletion fails, the Gateway
returns 500 and retains the owner record for retry.
[Thread cleanup API](../../backend/docs/API.md#thread-cleanup)

An embedded `DeerFlowClient(config_path="custom/config.yaml")` keeps the process
config singleton on that file, even after a working-directory change. Later edits
to the file are still detected. Call `reload_app_config()` without a path to resume
ambient config discovery, or `reset_app_config()` to clear the cached selection.

For database-backed run events, deleting a run preserves its thread's sequence watermark. Thread deletion removes that watermark once no events remain, allowing a recreated thread to restart at sequence 1. Owner-scoped deletion preserves the watermark when another owner's events remain.

Single-process JSONL event storage also retains the thread sequence watermark
across run deletion and restarts, so clients using `after_seq` do not miss later
messages. Keep `runs/.seq-watermark` with the run files when backing up this
backend. New or replaced watermarks inherit the deleted run file's permission bits.
Deleting the complete thread removes the watermark and resets allocation.

Thread IDs may be supplied by callers and do not have to be UUIDs. Explicit
IDs must contain 1–64 ASCII letters, digits, hyphens, or underscores
(`^[A-Za-z0-9_-]{1,64}$`). DeerFlow generates a UUID only when `thread_id` is
omitted or `None`; an explicitly supplied empty string is invalid.
Concurrent `POST /api/threads` requests and automatic run metadata creation share
same-ID admission in one Gateway, preserving the first thread's metadata and status.
HTTP retries also preserve its current checkpoint. SQL-backed Gateways retain
duplicate-insert recovery across workers.
Existing route-addressable threads created under older, looser rules remain
readable and deletable, but cannot start new runs or create new filesystem or
sandbox state. Legacy deletion skips local path cleanup when the ID is not
safe under the canonical contract. For canonical legacy threads whose
conversation exists only in LangGraph checkpoints, DeerFlow seeds an empty
run-event feed from the checkpoint before the first new run so
`/messages/page` keeps both the old and new turns.

```python
from deerflow.client import DeerFlowClient

client = DeerFlowClient()

# Chat
response = client.chat("Analyze this paper for me", thread_id="my-thread")

# Streaming (LangGraph SSE protocol: values, messages-tuple, end)
for event in client.stream("hello"):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        print(event.data["content"])
    elif event.type == "messages-tuple" and event.data.get("type") == "tool" and "artifact" in event.data:
        # Structured tool artifacts (for example, ask_clarification cards)
        # are preserved when the ToolMessage provides one.
        print(event.data["artifact"])

# Configuration & management — returns Gateway-aligned dicts
models = client.list_models()        # {"models": [...]}
skills = client.list_skills()        # {"skills": [...]}
client.update_skill("web-search", enabled=True)
client.upload_files("thread-1", ["./report.pdf"])  # {"success": True, "files": [...]}
client.set_goal("thread-1", "finish the implementation and make all tests pass")
client.get_goal("thread-1")       # {"goal": {...}} or {"goal": None}
client.clear_goal("thread-1")
```

When continuing a thread, `values` still contains the full conversation state, while `messages-tuple` and `end.usage` cover only the current turn.

The embedded client's `end.usage` sums usage deltas across streamed chunks,
including providers such as native Gemini that report usage more than once per
reply. The completed message's usage is reconciled without counting those
chunks again; a lower completed-message count does not subtract tokens already
reported by chunks. Signed provider corrections in chunks remain supported, as
do providers that report usage only at completion.

Concurrent `upload_files()` calls preserve filenames absent at the start of each
call by assigning numeric suffixes and returning the actual saved names. The same
rule applies to new Markdown companions. Exact names already present retain
replacement behavior. Convertible files use one private source capture through
all filename retries and conversion, preserving the original permissions and
timestamps. Detected staging-file substitution is rejected; staging cleanup
failures are logged without masking the upload outcome.

The HTTP Gateway accepts `values`, `messages-tuple`, `updates`, `debug`, `tasks`, `checkpoints`, and `custom` stream modes. Unsupported modes such as `messages` and `events`, unsupported non-default run options such as webhooks, delayed execution, or `multitask_strategy="enqueue"`, and undeclared SDK options such as checkpoint durability overrides return `422` before execution instead of being silently ignored or downgraded.

All dict-returning methods are validated against Gateway Pydantic response models in CI (`TestGatewayConformance`), ensuring the embedded client stays in sync with the HTTP API schemas. See `backend/packages/harness/deerflow/client.py` for full API documentation.
