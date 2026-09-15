# Issue 4416 Run Metadata Secrets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject the legacy top-level `metadata.auth_token` field before a run can persist anything, preserve request-scoped MCP credentials in `config.context.secrets`, and hide the legacy key from historical API responses.

**Architecture:** `deerflow.runtime.secret_context` remains the single owner of secret-carrier and legacy-key policy. `app.gateway.services.start_run()` is the sole new-run admission boundary; API serializers call the same non-mutating metadata redactor only to hide historical records, without changing stores or callback implementations.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, LangGraph/LangChain runnable context, pytest/anyio, ruff.

## Global Constraints

- Reject only the exact top-level metadata key `auth_token`; do not add heuristic matching for names such as `token`, `api_key`, or nested arbitrary metadata.
- Return HTTP 422 with migration guidance to `config.context.secrets`.
- Validate before `RunManager.create_or_reject()`, thread upsert/status changes, `build_run_config()`, callback creation, `RunJournal` event emission, and background task creation.
- Reuse `backend/packages/harness/deerflow/runtime/secret_context.py`; do not maintain duplicate secret-key lists in stores, callbacks, routers, or response models.
- Historical API hiding must not mutate the stored run, thread, checkpoint, or event object.
- Independent `POST /api/threads` and `PATCH /api/threads/{thread_id}` metadata contracts are outside #4416; they do not admit a run and must not silently adopt a second policy behavior.
- Existing nested values in `config.context.secrets` must remain available to the live MCP interceptor while remaining absent from persisted run config.
- Features and bug fixes ship with tests; run backend formatting and lint checks before completion.
- Update `README.md`, `backend/docs/MCP_SERVER.md`, and `backend/AGENTS.md` in the same change set.

---

### Task 1: Central legacy metadata policy

**Files:**
- Create: `backend/tests/test_run_metadata_secret_safety.py`
- Modify: `backend/packages/harness/deerflow/runtime/secret_context.py`

**Interfaces:**
- Consumes: existing `redact_config_secrets(config: Any) -> Any`.
- Produces: `LEGACY_AUTH_TOKEN_METADATA_KEY: str`, `LegacyRunMetadataSecretError(ValueError)`, `validate_run_metadata_secrets(metadata: Any) -> None`, and `redact_metadata_secrets(metadata: Any) -> Any`.

- [ ] **Step 1: Write failing unit tests for exact-key admission and non-mutating redaction**

```python
import pytest

from deerflow.runtime.secret_context import (
    LegacyRunMetadataSecretError,
    redact_metadata_secrets,
    validate_run_metadata_secrets,
)


@pytest.mark.parametrize("value", ["secret", "", None, {"nested": True}])
def test_validate_run_metadata_rejects_auth_token_key_by_presence(value):
    with pytest.raises(LegacyRunMetadataSecretError, match=r"config\.context\.secrets"):
        validate_run_metadata_secrets({"auth_token": value, "token_usage": 7})


@pytest.mark.parametrize(
    "metadata",
    [None, "not-a-mapping", {"token": "keep", "nested": {"auth_token": "keep"}}],
)
def test_validate_run_metadata_accepts_non_legacy_shapes(metadata):
    validate_run_metadata_secrets(metadata)


def test_redact_metadata_secrets_removes_exact_key_without_mutating_source():
    source = {
        "auth_token": "legacy-secret",
        "token_usage": 7,
        "nested": {"auth_token": "ordinary-nested-metadata"},
    }

    redacted = redact_metadata_secrets(source)

    assert redacted == {
        "token_usage": 7,
        "nested": {"auth_token": "ordinary-nested-metadata"},
    }
    assert source["auth_token"] == "legacy-secret"
    assert redacted is not source
```

- [ ] **Step 2: Run the new tests and observe RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_run_metadata_secret_safety.py -q
```

Expected: collection fails because the four new symbols do not yet exist.

- [ ] **Step 3: Add the minimal centralized policy**

Add to `secret_context.py`:

```python
LEGACY_AUTH_TOKEN_METADATA_KEY = "auth_token"


class LegacyRunMetadataSecretError(ValueError):
    """Raised when a run puts a request credential in persisted metadata."""


def validate_run_metadata_secrets(metadata: Any) -> None:
    """Reject the legacy credential field at run admission."""
    if isinstance(metadata, dict) and LEGACY_AUTH_TOKEN_METADATA_KEY in metadata:
        raise LegacyRunMetadataSecretError(
            "Run metadata key 'auth_token' is not allowed; "
            "pass request-scoped credentials via config.context.secrets instead."
        )


def redact_metadata_secrets(metadata: Any) -> Any:
    """Return API-safe metadata without mutating historical storage objects."""
    if not isinstance(metadata, dict):
        return metadata
    return {
        key: value
        for key, value in metadata.items()
        if key != LEGACY_AUTH_TOKEN_METADATA_KEY
    }
```

- [ ] **Step 4: Run the policy tests and observe GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_run_metadata_secret_safety.py -q
```

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit the policy unit**

```bash
git add backend/packages/harness/deerflow/runtime/secret_context.py backend/tests/test_run_metadata_secret_safety.py
git commit -m "fix(security): centralize legacy run metadata policy"
```

### Task 2: Unified run admission before persistence

**Files:**
- Modify: `backend/tests/test_gateway_services.py`
- Modify: `backend/app/gateway/services.py`

**Interfaces:**
- Consumes: `validate_run_metadata_secrets(metadata: Any) -> None` and `LegacyRunMetadataSecretError`.
- Produces: `start_run()` rejection with `HTTPException(status_code=422)` before any run/thread persistence; scheduled launches inherit the same boundary.

- [ ] **Step 1: Add a failing real-store regression test**

Add this reusable test setup beside `_capture_start_run_graph_input`:

```python
def _make_start_run_persistence_context():
    from types import SimpleNamespace

    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.store.memory import InMemoryStore

    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.runs.store.memory import MemoryRunStore

    run_store = MemoryRunStore()
    thread_store = MemoryThreadMetaStore(InMemoryStore())
    state = SimpleNamespace(
        stream_bridge=SimpleNamespace(),
        run_manager=RunManager(store=run_store),
        checkpointer=InMemorySaver(),
        store=InMemoryStore(),
        run_event_store=SimpleNamespace(),
        run_events_config=None,
        thread_store=thread_store,
        checkpoint_channel_mode="full",
        scheduled_task_service=None,
    )
    request = SimpleNamespace(
        headers={},
        state=SimpleNamespace(),
        app=SimpleNamespace(state=state),
    )
    return request, run_store, thread_store
```

Use it in a synchronous pytest test with an `asyncio.run()` scenario, matching
the existing `test_gateway_services.py` style:

```python
def test_start_run_rejects_legacy_auth_token_before_persistence():
    async def _scenario():
        request, run_store, thread_store = _make_start_run_persistence_context()
        body = RunCreateRequest(
            assistant_id="lead_agent",
            input={"messages": [{"role": "user", "content": "hi"}]},
            metadata={"auth_token": "legacy-secret", "token_usage": 7},
        )

        with patch(
            "app.gateway.services.run_agent", new_callable=AsyncMock
        ) as run_agent:
            with pytest.raises(HTTPException) as exc_info:
                await start_run(body, "thread-secret-admission", request)

        assert exc_info.value.status_code == 422
        assert "config.context.secrets" in str(exc_info.value.detail)
        assert await run_store.list_by_thread("thread-secret-admission") == []
        assert await thread_store.get("thread-secret-admission") is None
        run_agent.assert_not_called()

    asyncio.run(_scenario())
```

- [ ] **Step 2: Add a failing ordinary-metadata preservation test**

Start a run with:

```python
metadata = {"token_usage": 7, "source": "regression"}
```

The test function must accept the existing `_stub_app_config` fixture because
an admitted run calls `get_run_context()` and resolves the live `AppConfig`.
Use `_make_start_run_persistence_context()`, patch `resolve_agent_factory`, and
capture the live config in an async `fake_run_agent`:

```python
def test_start_run_preserves_ordinary_metadata(_stub_app_config):
    async def _scenario():
        thread_id = "thread-ordinary-metadata"
        metadata = {"token_usage": 7, "source": "regression"}
        request, _run_store, thread_store = (
            _make_start_run_persistence_context()
        )
        captured: dict[str, Any] = {}

        async def fake_run_agent(*args, **kwargs):
            captured["config"] = kwargs["config"]

        with (
            patch(
                "app.gateway.services.resolve_agent_factory",
                return_value=object(),
            ),
            patch(
                "app.gateway.services.run_agent",
                side_effect=fake_run_agent,
            ),
        ):
            record = await start_run(
                RunCreateRequest(
                    assistant_id="lead_agent",
                    input={
                        "messages": [
                            {"role": "user", "content": "hi"}
                        ]
                    },
                    metadata=metadata,
                ),
                thread_id,
                request,
            )
            await record.task

        assert record.metadata == metadata
        assert (await thread_store.get(thread_id))["metadata"] == metadata
        assert captured["config"]["metadata"] == metadata

    asyncio.run(_scenario())
```

This prevents the exact-key rule from becoming broad metadata stripping.

- [ ] **Step 3: Run both admission tests and observe RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_gateway_services.py::test_start_run_rejects_legacy_auth_token_before_persistence \
  tests/test_gateway_services.py::test_start_run_preserves_ordinary_metadata \
  -q
```

Expected: the legacy request is currently accepted and persisted.

- [ ] **Step 4: Install validation at the first line of `start_run()`**

Import the shared symbols and add before `get_stream_bridge(request)`:

```python
try:
    validate_run_metadata_secrets(getattr(body, "metadata", None))
except LegacyRunMetadataSecretError as exc:
    raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Do not add checks to `RunStore`, `ThreadMetaStore`, `RunJournal`, `build_run_config`, or the router handlers.

- [ ] **Step 5: Run both admission tests and observe GREEN**

Run the exact Task 2 Step 3 command.

Expected: both tests pass; the rejected path creates no row or task.

- [ ] **Step 6: Add and run the scheduled-launch regression**

Call the real scheduled launcher with a deliberately minimal app. Because validation must be the first operation in `start_run()`, the request must receive the policy error before the empty app state is accessed:

```python
def test_launch_scheduled_thread_run_rejects_legacy_auth_token():
    async def _scenario():
        with pytest.raises(HTTPException) as exc_info:
            await launch_scheduled_thread_run(
                thread_id="thread-scheduled",
                assistant_id="lead_agent",
                prompt="Run in background",
                app=SimpleNamespace(state=SimpleNamespace()),
                metadata={"auth_token": "legacy-secret"},
            )

        assert exc_info.value.status_code == 422
        assert "config.context.secrets" in str(exc_info.value.detail)

    asyncio.run(_scenario())
```

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_gateway_services.py::test_launch_scheduled_thread_run_rejects_legacy_auth_token \
  -q
```

Expected: PASS, proving scheduled metadata reaches the same admission policy rather than bypassing it.

- [ ] **Step 7: Commit the admission boundary**

```bash
git add backend/app/gateway/services.py backend/tests/test_gateway_services.py
git commit -m "fix(security): reject secrets at run admission"
```

### Task 3: Non-mutating historical API hiding

**Files:**
- Modify: `backend/tests/test_run_metadata_secret_safety.py`
- Modify: `backend/tests/test_run_events_endpoint.py`
- Modify: `backend/app/gateway/routers/thread_runs.py`
- Modify: `backend/app/gateway/routers/threads.py`

**Interfaces:**
- Consumes: `redact_metadata_secrets(metadata: Any) -> Any`.
- Produces: redacted `RunResponse`, `ThreadResponse`, `ThreadStateResponse`, `HistoryEntry`, and run-event rows while leaving their input records unchanged.

- [ ] **Step 1: Add failing response-model tests**

Construct a historical `RunRecord` containing:

```python
legacy_metadata = {"auth_token": "legacy-secret", "token_usage": 7}
record = RunRecord(
    run_id="legacy-run",
    thread_id="legacy-thread",
    assistant_id="lead_agent",
    status=RunStatus.success,
    on_disconnect=DisconnectMode.cancel,
    metadata=legacy_metadata,
)

response = _record_to_response(record)

assert response.metadata == {"token_usage": 7}
assert record.metadata["auth_token"] == "legacy-secret"
```

Import `RunRecord` from `deerflow.runtime.runs.manager` and `DisconnectMode` / `RunStatus` from `deerflow.runtime.runs.schemas`.

For each thread response model:

```python
@pytest.mark.parametrize(
    ("response_class", "required_fields"),
    [
        (ThreadResponse, {"thread_id": "legacy-thread"}),
        (ThreadStateResponse, {}),
        (HistoryEntry, {"checkpoint_id": "legacy-checkpoint"}),
    ],
)
def test_thread_metadata_response_models_hide_historical_auth_token(
    response_class, required_fields
):
    source = {"auth_token": "legacy-secret", "token_usage": 7}
    response = response_class(**required_fields, metadata=source)

    assert response.metadata == {"token_usage": 7}
    assert source["auth_token"] == "legacy-secret"
```

Cover all three classes explicitly: `ThreadResponse`, `ThreadStateResponse`, and `HistoryEntry`.

- [ ] **Step 2: Run the response tests and observe RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest tests/test_run_metadata_secret_safety.py -q
```

Expected: historical response objects still contain `auth_token`.

- [ ] **Step 3: Apply the shared redactor to response construction**

In `_record_to_response()` use:

```python
metadata=redact_metadata_secrets(record.metadata),
```

In `threads.py`, create one local response base class:

```python
class _MetadataRedactingResponse(BaseModel):
    @field_validator("metadata", mode="before", check_fields=False)
    @classmethod
    def _redact_legacy_metadata_secret(cls, value: Any) -> Any:
        return redact_metadata_secrets(value)
```

Make `ThreadResponse`, `ThreadStateResponse`, and `HistoryEntry` inherit from this base. Do not alter `ThreadCreateRequest`, `ThreadPatchRequest`, `_SERVER_RESERVED_METADATA_KEYS`, or stored rows.

Keep `check_fields=False`: the base class intentionally declares a validator
for a field that exists only on its subclasses. In the worktree's installed
Pydantic 2.13.3, `field_validator` still accepts `check_fields`, and removing
it raises `PydanticUserError` while defining the base class.

Scope note: `record.kwargs["config"]["metadata"]` is the caller's raw
LangChain `RunnableConfig.metadata`, not `RunCreateRequest.metadata`, and is
outside the exact documented legacy request field addressed by #4416. Do not
claim the admission validator cleans this separate mapping. Existing
historical values there remain subject to the operator rotation and retained
data cleanup guidance in Task 4; changing the raw RunnableConfig contract
requires separate policy review.

- [ ] **Step 4: Run the response tests and observe GREEN**

Run the exact Task 3 Step 2 command.

Expected: all helper and response tests pass.

- [ ] **Step 5: Add a failing historical `run.start` event test**

Extend `test_run_events_endpoint.py` with a fake store returning one row:

```python
stored_row = {
    "seq": 1,
    "event_type": "run.start",
    "metadata": {
        "caller": "lead_agent",
        "auth_token": "legacy-secret",
        "token_usage": 7,
    },
}
```

Call `list_run_events()` and assert:

```python
assert events[0]["metadata"] == {
    "caller": "lead_agent",
    "token_usage": 7,
}
assert stored_row["metadata"]["auth_token"] == "legacy-secret"
assert events[0] is not stored_row
```

- [ ] **Step 6: Run the event test and observe RED**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_run_events_endpoint.py::test_list_run_events_redacts_historical_run_start_metadata \
  -q
```

Expected: returned event metadata still exposes `auth_token`.

- [ ] **Step 7: Redact event rows without mutating the store result**

Replace the direct return in `list_run_events()` with:

```python
events = await event_store.list_events(
    thread_id,
    run_id,
    event_types=types,
    task_id=task_id,
    limit=limit,
    after_seq=after_seq,
)
return [
    {
        **event,
        "metadata": redact_metadata_secrets(event.get("metadata")),
    }
    if isinstance(event, dict) and "metadata" in event
    else event
    for event in events
]
```

- [ ] **Step 8: Run historical output tests and observe GREEN**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_run_metadata_secret_safety.py \
  tests/test_run_events_endpoint.py \
  -q
```

Expected: all tests pass, including existing event forwarding behavior.

- [ ] **Step 9: Commit historical API hiding**

```bash
git add \
  backend/app/gateway/routers/thread_runs.py \
  backend/app/gateway/routers/threads.py \
  backend/tests/test_run_metadata_secret_safety.py \
  backend/tests/test_run_events_endpoint.py
git commit -m "fix(security): hide legacy secrets from history APIs"
```

### Task 4: Supported MCP carrier and operator documentation

**Files:**
- Modify: `backend/tests/test_mcp_session_pool.py`
- Modify: `backend/tests/test_skill_request_scoped_secrets.py`
- Modify: `backend/docs/MCP_SERVER.md`
- Modify: `README.md`
- Modify: `backend/AGENTS.md`

**Interfaces:**
- Consumes: LangGraph `get_config()["context"]["secrets"]` and existing `redact_config_secrets`.
- Produces: tested MCP header injection from the supported carrier and migration/rotation/cleanup guidance.

- [ ] **Step 1: Add a failing MCP interceptor carrier regression**

Extend the existing pooled-tool header test pattern with an interceptor that reads the live LangGraph config:

```python
async def secret_header_interceptor(request, handler):
    from langgraph.config import get_config

    secrets = (get_config().get("context") or {}).get("secrets") or {}
    return await handler(
        request.override(headers={"Authorization": f"Bearer {secrets['MCP_AUTH_TOKEN']}"})
    )
```

Patch `langgraph.config.get_config` to return:

```python
{"context": {"secrets": {"MCP_AUTH_TOKEN": "nested-secret"}}}
```

Invoke the wrapped tool and assert:

```python
mock_session.call_tool.assert_awaited_once_with(
    "act",
    {"x": 1},
    meta={"headers": {"Authorization": "Bearer nested-secret"}},
)
```

- [ ] **Step 2: Run the MCP regression**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_mcp_session_pool.py::test_session_pool_interceptor_reads_request_scoped_secret \
  -q
```

Expected before any production change: PASS if the documented supported carrier is already wired correctly. A failure is a real compatibility gap and must be fixed in the narrowest runtime layer before proceeding.

- [ ] **Step 3: Strengthen persisted-config coverage for nested values**

Change the existing config-redaction fixture to:

```python
"secrets": {
    "ERP_TOKEN": _SECRET,
    "nested": {"secondary": _SECRET},
},
```

Keep assertions that the live source remains intact and the redacted copy contains no secret values.

- [ ] **Step 4: Run the supported-carrier regression group**

Run:

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_mcp_session_pool.py::test_session_pool_interceptor_reads_request_scoped_secret \
  tests/test_skill_request_scoped_secrets.py::TestLeakSurfaces::test_redact_config_secrets_strips_from_persisted_config \
  -q
```

Expected: both tests pass.

- [ ] **Step 5: Replace the unsafe MCP documentation example**

In `backend/docs/MCP_SERVER.md`, replace `get_config()["metadata"]["auth_token"]` with:

```python
from langgraph.config import get_config


def build_auth_interceptor():
    async def interceptor(request, handler):
        config = get_config()
        secrets = (config.get("context") or {}).get("secrets") or {}
        token = secrets.get("MCP_AUTH_TOKEN")
        if token:
            request = request.override(
                headers={**(request.headers or {}), "Authorization": f"Bearer {token}"}
            )
        return await handler(request)

    return interceptor
```

Document the request shape:

```json
{
  "metadata": {"source": "my-client"},
  "config": {
    "context": {
      "secrets": {"MCP_AUTH_TOKEN": "<request-scoped credential>"}
    }
  }
}
```

State that `metadata.auth_token` is rejected with 422 and is never the supported interceptor path.

- [ ] **Step 6: Add repository and operator guidance**

Add a concise security note to `README.md` linking to `backend/docs/MCP_SERVER.md`.

Update `backend/AGENTS.md` to state:

- `start_run()` validates the exact legacy key before run/thread persistence;
- `secret_context.py` owns admission and output-redaction policy;
- historical API hiding does not delete old database/event/log/snapshot/backup material;
- deployments that previously used `metadata.auth_token` must rotate the credential and clean all retained copies;
- restarting or upgrading DeerFlow does not perform that cleanup.

- [ ] **Step 7: Commit supported flow and docs**

```bash
git add \
  backend/tests/test_mcp_session_pool.py \
  backend/tests/test_skill_request_scoped_secrets.py \
  backend/docs/MCP_SERVER.md \
  README.md \
  backend/AGENTS.md
git commit -m "docs(security): migrate MCP credentials to secret context"
```

### Task 5: Full verification and handoff

**Files:**
- Verify all modified files.

**Interfaces:**
- Consumes: all preceding commits.
- Produces: formatting-clean, lint-clean, regression-tested branch ready for review.

- [ ] **Step 1: Run the focused security regression suite**

```bash
cd backend
.venv/bin/python -m pytest \
  tests/test_run_metadata_secret_safety.py \
  tests/test_gateway_services.py \
  tests/test_run_events_endpoint.py \
  tests/test_mcp_session_pool.py \
  tests/test_skill_request_scoped_secrets.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Format and verify formatting**

```bash
cd backend
.venv/bin/ruff format \
  packages/harness/deerflow/runtime/secret_context.py \
  app/gateway/services.py \
  app/gateway/routers/thread_runs.py \
  app/gateway/routers/threads.py \
  tests/test_run_metadata_secret_safety.py \
  tests/test_gateway_services.py \
  tests/test_run_events_endpoint.py \
  tests/test_mcp_session_pool.py \
  tests/test_skill_request_scoped_secrets.py
.venv/bin/ruff format --check \
  packages/harness/deerflow/runtime/secret_context.py \
  app/gateway/services.py \
  app/gateway/routers/thread_runs.py \
  app/gateway/routers/threads.py \
  tests/test_run_metadata_secret_safety.py \
  tests/test_gateway_services.py \
  tests/test_run_events_endpoint.py \
  tests/test_mcp_session_pool.py \
  tests/test_skill_request_scoped_secrets.py
```

Expected: no files require further formatting.

- [ ] **Step 3: Run lint**

```bash
cd backend
.venv/bin/ruff check \
  packages/harness/deerflow/runtime/secret_context.py \
  app/gateway/services.py \
  app/gateway/routers/thread_runs.py \
  app/gateway/routers/threads.py \
  tests/test_run_metadata_secret_safety.py \
  tests/test_gateway_services.py \
  tests/test_run_events_endpoint.py \
  tests/test_mcp_session_pool.py \
  tests/test_skill_request_scoped_secrets.py
```

Expected: `All checks passed!`

- [ ] **Step 4: Run the full backend suite**

```bash
cd backend
.venv/bin/python -m pytest -q
```

Expected: the full backend suite passes. If an unrelated environment-dependent test fails, record the exact command, output, and why it is unrelated; do not claim a clean full suite.

- [ ] **Step 5: Inspect repository hygiene**

```bash
git diff --check upstream/main...HEAD
git status --short
git log --oneline --decorate upstream/main..HEAD
```

Expected: no whitespace errors; only intentional files are changed; the branch contains the design, plan, implementation, tests, and documentation commits.

- [ ] **Step 6: Commit any formatter-only changes**

If Step 2 changed files:

```bash
git add \
  backend/packages/harness/deerflow/runtime/secret_context.py \
  backend/app/gateway/services.py \
  backend/app/gateway/routers/thread_runs.py \
  backend/app/gateway/routers/threads.py \
  backend/tests/test_run_metadata_secret_safety.py \
  backend/tests/test_gateway_services.py \
  backend/tests/test_run_events_endpoint.py \
  backend/tests/test_mcp_session_pool.py \
  backend/tests/test_skill_request_scoped_secrets.py
git commit -m "style: format issue 4416 security fix"
```

If Step 2 changed nothing, skip this commit.

- [ ] **Step 7: Summarize evidence for review**

Report:

- the admission boundary and exact 422 migration message;
- the five historical response surfaces;
- proof that rejected requests create neither run nor thread records;
- proof that nested `config.context.secrets` reaches an MCP interceptor but not persisted run config;
- focused and full-suite test counts;
- any remaining operational requirement to rotate and clean historical credentials.
