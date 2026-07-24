# Issue #4416 Run Metadata Secret Safety Design

## Context

The documented custom MCP interceptor reads a per-request `auth_token` from
run `metadata`. DeerFlow treats run metadata as observable data: the Gateway
copies it into the in-memory `RunRecord`, persistent `RunStore`, newly-created
thread metadata, runnable callback metadata, and the `run.start` event. Run,
thread, checkpoint-history, and run-event APIs can then return those stored
values.

DeerFlow already has a request-scoped secret carrier at
`config.context.secrets`. The live run config retains that carrier for tools
and interceptors, while `runtime/secret_context.py::redact_config_secrets`
removes the complete `secrets` container before the request config is persisted
or echoed. Removing the container rather than inspecting its values already
covers nested secret structures.

The root cause is therefore not missing redaction in every downstream
component. It is that the legacy `metadata.auth_token` input is admitted into
the run lifecycle before any run or thread object is built.

## Goals

- Reject the exact legacy path `metadata.auth_token` at the unified run
  admission boundary before run or thread persistence.
- Keep `config.context.secrets` available to the live MCP call while ensuring
  the full container, including nested values, is absent from persisted run
  kwargs and API echoes.
- Keep the secret policy in `runtime/secret_context.py`; stores, callbacks, and
  individual response constructors must not define independent key lists.
- Hide `auth_token` from historical run, thread/checkpoint, and RunEvent API
  responses without mutating stored records.
- Preserve ordinary metadata, including token-accounting fields such as
  `token_usage`.
- Document credential rotation and retained-data cleanup for operators who used
  the old example.

## Non-goals

- Automatically migrate `metadata.auth_token` into the supported carrier.
- Automatically rewrite existing databases, event stores, logs, backups, or
  snapshots.
- Heuristically redact every field containing `token`, `key`, or `secret`.
- Add store-specific, callback-specific, or tracing-provider-specific copies of
  the same rule.
- Change the independent `POST /api/threads` or `PATCH /api/threads/{id}`
  metadata contracts. Those endpoints do not admit a run, do not consume the
  documented MCP credential path, and are outside the maintainer-selected
  unified run admission boundary.
- Change MCP OAuth configuration or skill `required-secrets` behavior.

## Considered Approaches

### 1. Reject in the Pydantic request model

This is early for HTTP requests, but it is not the unified lifecycle boundary.
Internal launchers and future non-HTTP callers can construct request-like
objects and call `start_run()` directly. It would also couple #4416 to the
request-model refactor in the unmerged #4417 PR.

### 2. Redact independently in every store, response, callback, and event path

This protects many symptoms, but creates several policy copies that can drift.
It also allows an unsupported secret carrier to enter the runtime and makes it
unclear which layer owns admission.

### 3. Central admission rejection plus shared historical-output redaction

This is the selected approach. `start_run()` is the shared Gateway lifecycle
entry for thread-scoped, stateless, streaming, waiting, and scheduled launches.
It rejects the legacy path before `RunManager.create_or_reject()` or thread
metadata persistence. Existing records are a separate concern: API serializers
and the run-events endpoint call a shared redactor from `secret_context.py`,
while the stored data remains untouched for operator-controlled cleanup.

## Architecture

### Secret policy source

`backend/packages/harness/deerflow/runtime/secret_context.py` will own:

- the exact legacy metadata key, `auth_token`;
- a dedicated validation error for the unsupported legacy carrier;
- an admission validator that rejects the key based on presence, regardless of
  whether its value is a string, null, or a nested object;
- a non-mutating API redactor that removes only the exact top-level key from a
  metadata mapping.

The redactor will preserve every other key unchanged. It will not inspect key
substrings and will not recursively delete unrelated nested fields.

### New-request admission

`backend/app/gateway/services.py::start_run` will validate `body.metadata` at
the beginning of the run lifecycle, before:

1. `RunManager.create_or_reject()`;
2. `ThreadMetaStore.create()` or any thread status mutation;
3. `build_run_config()`, which copies `body.metadata` into the LangChain
   runnable config's `metadata` mapping;
4. LangChain callback dispatch and `RunJournal.on_chain_start()`, whose
   `run.start` event persists that runnable metadata;
5. agent task creation.

The Gateway will translate the dedicated validation error into HTTP 422 with a
message directing callers to `config.context.secrets`. Because scheduled
launches also call `start_run()`, they receive the same policy without a second
validator.

No store or callback changes are needed for newly-admitted requests: a rejected
value never reaches those layers.

The thread persistence named above is the thread upsert performed as part of
`start_run()`. Independent thread create/patch endpoints are not alternate run
admission paths and are not changed by this fix. Adding silent stripping there
would create a second policy behavior without addressing the documented run
credential path.

### Supported MCP secret flow

The documentation will show an interceptor reading:

```python
config = get_config()
secrets = (config.get("context") or {}).get("secrets") or {}
token = secrets.get("auth_token")
```

The live config passed to `run_agent()` keeps this value. The persisted
`RunRecord.kwargs["config"]` continues to use `redact_config_secrets()`, which
removes the entire `context.secrets` container and therefore all nested values.

### Historical API hiding

Admission rejection cannot repair records created before the fix. Historical
output handling is deliberately separate:

- `_record_to_response` in `thread_runs.py` redacts `RunRecord.metadata` before
  constructing `RunResponse`;
- `ThreadResponse` in `threads.py` redacts stored thread metadata for create,
  get, patch, and search responses;
- `ThreadStateResponse` in `threads.py` redacts checkpoint metadata returned by
  the state API;
- `HistoryEntry` in `threads.py` redacts each checkpoint tuple's metadata
  returned by the history API;
- `list_run_events` in `thread_runs.py` redacts each event row's `metadata`
  before returning it. This explicitly covers historical `run.start` events
  whose value followed the indirect
  `body.metadata → config["metadata"] → callback metadata → RunEventStore`
  path.

These paths must not mutate `RunRecord`, thread-store rows, checkpoint tuples,
or RunEventStore rows. Database and backup cleanup remains an operator action.

### Documentation and operations

`backend/docs/MCP_SERVER.md` will:

- replace the metadata-based interceptor example with
  `config.context.secrets`;
- show the matching request configuration shape;
- state that `metadata.auth_token` is rejected;
- tell affected operators to rotate the credential and remove retained values
  from databases, event stores, logs, snapshots, and backups according to their
  retention policy.

After an upgrade or container restart, retained records are hidden only at the
listed API output boundaries. Restarting does not delete or rewrite the stored
credential; rotation and cleanup remain required.

The root README will carry a concise user-facing security note. The backend
AGENTS guide will record the admission and historical-output boundaries so
future changes do not reintroduce distributed policy copies.

## Error Handling

- Presence of `metadata.auth_token` produces HTTP 422 before any persistent
  operation or background task starts.
- The response message identifies both the rejected legacy path and the
  supported `config.context.secrets` path.
- A metadata mapping without that exact key is accepted unchanged.
- Existing historical records remain readable, but their API representation
  omits `auth_token`.

## Test Strategy

Tests will be written before production changes and observed failing for the
expected reason.

1. Admission regression:
   - call `start_run()` with `metadata.auth_token`;
   - assert HTTP 422;
   - assert `RunManager.create_or_reject`, thread-store writes, and
     `run_agent()` were not called.
   - call `launch_scheduled_thread_run()` with the same legacy metadata and
     assert the shared `start_run()` admission rejects it before persistence.
2. Ordinary metadata:
   - include `token_usage` and other non-secret fields;
   - assert the run, thread, callback config, and API representation retain
     them.
3. Supported carrier:
   - supply nested values in `config.context.secrets`;
   - assert an MCP interceptor can read them from the live config;
   - assert persisted run kwargs and API echoes contain none of the nested
     secret values.
4. Historical output:
   - construct legacy run, thread/checkpoint, and RunEvent records containing
     `auth_token`;
   - use a historical `run.start` event to cover the indirect callback metadata
     path;
   - assert API serialization hides the exact field;
   - assert the underlying objects still contain it, proving no implicit data
     migration occurred.
5. Documentation:
   - assert the official example no longer reads authentication material from
     metadata and includes the migration/rotation guidance.

Targeted suites will cover Gateway services and endpoints, request-scoped
secret helpers, MCP session/interceptor behavior, thread responses, and
RunJournal/RunEvent APIs. The complete backend unit suite, Ruff checks, and
format checks will run before completion.

## Compatibility and Rollout

This is intentionally a breaking change for the insecure documented path.
Callers must move the credential to `config.context.secrets`. Ordinary metadata
is backward compatible. Existing records are not deleted or rewritten by the
application; operators control rotation and cleanup based on their storage and
retention environment.
