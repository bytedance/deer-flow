"""Conformance tests for the documented run event stream contract."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from deerflow.runtime.events.catalog import (
    FIXED_RUN_EVENT_DEFINITIONS,
    JOURNAL_RUN_EVENT_DEFINITIONS,
    MIDDLEWARE_EVENT_PATTERN,
    MIDDLEWARE_EVENT_TAG_MAX_LENGTH,
    MIDDLEWARE_EVENT_TAGS,
    RUN_EVENT_CATEGORY_MAX_LENGTH,
    RUN_EVENT_TYPE_MAX_LENGTH,
    SUBAGENT_RUN_EVENT_DEFINITIONS,
    WORKSPACE_RUN_EVENT_DEFINITIONS,
    RunEventDefinition,
    RunEventPattern,
)
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import RunJournal
from deerflow.subagents.step_events import SUBAGENT_STEP_MAX_CHARS, capture_step_message, subagent_run_event

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "contracts" / "run_event_stream_contract.json"


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _contract_events() -> dict[str, dict]:
    return {event["event_type"]: event for event in _load_contract()["events"]}


def _assert_schema_valid(schema: dict | bool, instance: object) -> None:
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.path))
    assert not errors, "; ".join(error.message for error in errors)


def _assert_fixed_event_valid(event: dict, *, persisted: bool = False) -> None:
    contract_event = _contract_events()[event["event_type"]]
    assert event["category"] == contract_event["category"]
    _assert_schema_valid(contract_event["content_schema"], event["content"])
    _assert_schema_valid(contract_event["metadata_schema"], event.get("metadata", {}))
    if persisted:
        _assert_schema_valid(_load_contract()["record_schema"], event)


def _make_llm_response(content: str = "answer", usage: dict | None = None) -> LLMResult:
    message = AIMessage(
        content=content,
        id=f"msg-{uuid4()}",
        response_metadata={"model_name": "test-model"},
        usage_metadata=usage,
    )
    return LLMResult(generations=[[ChatGeneration(message=message)]])


def _subagent_batch() -> list[dict]:
    chunks = [
        {"type": "task_started", "task_id": "call-batch", "description": "research"},
        {
            "type": "task_running",
            "task_id": "call-batch",
            "message": {
                "type": "ai",
                "content": "searching",
                "tool_calls": [{"name": "web_search", "args": {"query": "deerflow"}}],
            },
            "message_index": 1,
        },
        {"type": "task_completed", "task_id": "call-batch", "result": "done"},
    ]
    events = [subagent_run_event(chunk) for chunk in chunks]
    assert all(event is not None for event in events)
    return [{"thread_id": "thread-batch", "run_id": "run-batch", **event} for event in events if event is not None]


async def _persist_subagent_batch(store) -> list[dict]:
    await store.put_batch(_subagent_batch())
    return await store.list_events("thread-batch", "run-batch")


async def _record_run_end(store) -> dict:
    journal = RunJournal("run-output", "thread-output", store, flush_threshold=100)
    journal.on_chain_end(
        {"messages": [AIMessage(content="final answer", id="final-message")]},
        run_id=uuid4(),
        parent_run_id=None,
    )
    await journal.flush()
    events = await store.list_events("thread-output", "run-output", event_types=["run.end"])
    assert len(events) == 1
    return events[0]


def test_contract_and_runtime_catalog_have_the_same_fixed_events():
    contract = _load_contract()
    contract_types = [event["event_type"] for event in contract["events"]]
    runtime_types = [definition.event_type for definition in FIXED_RUN_EVENT_DEFINITIONS]
    contract_pairs = {(event["event_type"], event["category"]) for event in contract["events"]}
    runtime_pairs = {(definition.event_type, definition.category) for definition in FIXED_RUN_EVENT_DEFINITIONS}

    assert len(set(contract_types)) == len(contract_types)
    assert len(set(runtime_types)) == len(runtime_types)
    assert contract_pairs == runtime_pairs
    assert set(contract["categories"]) == {definition.category for definition in FIXED_RUN_EVENT_DEFINITIONS} | {MIDDLEWARE_EVENT_PATTERN.category}

    event_type_schema = contract["record_schema"]["properties"]["event_type"]
    category_schema = contract["record_schema"]["properties"]["category"]
    middleware_pattern = contract["dynamic_event_patterns"][0]
    assert event_type_schema["maxLength"] == RUN_EVENT_TYPE_MAX_LENGTH
    assert category_schema["maxLength"] == RUN_EVENT_CATEGORY_MAX_LENGTH
    assert middleware_pattern["event_type_schema"]["maxLength"] == RUN_EVENT_TYPE_MAX_LENGTH
    assert middleware_pattern["tag_schema"]["maxLength"] == MIDDLEWARE_EVENT_TAG_MAX_LENGTH

    from deerflow.persistence.models.run_event import RunEventRow

    assert RunEventRow.__table__.c.event_type.type.length == RUN_EVENT_TYPE_MAX_LENGTH
    assert RunEventRow.__table__.c.category.type.length == RUN_EVENT_CATEGORY_MAX_LENGTH


@pytest.mark.parametrize(
    ("definition_type", "kwargs"),
    [
        (RunEventDefinition, {"event_type": "test.event"}),
        (RunEventPattern, {"pattern": "test:{tag}", "prefix": "test:"}),
    ],
)
def test_runtime_catalog_rejects_categories_that_do_not_fit_persistence(definition_type, kwargs):
    assert definition_type(category="x" * RUN_EVENT_CATEGORY_MAX_LENGTH, **kwargs).category

    for invalid_category in ("", "x" * (RUN_EVENT_CATEGORY_MAX_LENGTH + 1)):
        with pytest.raises(ValueError, match="category"):
            definition_type(category=invalid_category, **kwargs)


@pytest.mark.parametrize(
    "relative_path",
    [
        "persistence/models/run_event.py",
        "workspace_changes/types.py",
    ],
)
def test_lower_level_run_event_modules_do_not_import_runtime(relative_path):
    module_path = REPO_ROOT / "backend" / "packages" / "harness" / "deerflow" / relative_path
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module is not None]
    imports.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)

    assert not [module for module in imports if module == "deerflow.runtime" or module.startswith("deerflow.runtime.")]


def test_legacy_aliases_are_read_only_and_outside_the_current_catalog():
    contract = _load_contract()
    aliases = {alias["event_type"]: alias for alias in contract["legacy_event_aliases"]}
    current_types = {definition.event_type for definition in FIXED_RUN_EVENT_DEFINITIONS}

    assert set(aliases) == {"ai_message"}
    assert aliases["ai_message"]["canonical_event_type"] == "llm.ai.response"
    assert aliases["ai_message"]["produced_by_current_runtime"] is False
    assert "/messages/page" in aliases["ai_message"]["compatibility_scope"]
    assert "legacy /messages endpoint" in aliases["ai_message"]["known_limitations"]
    assert set(aliases).isdisjoint(current_types)


def test_record_envelope_accepts_every_json_content_type():
    schema = _load_contract()["record_schema"]
    envelope = {
        "thread_id": "thread-1",
        "run_id": "run-1",
        "seq": 1,
        "event_type": "run.end",
        "category": "outputs",
        "metadata": {},
        "created_at": "2026-07-21T00:00:00+00:00",
    }

    for content in ("text", {"key": "value"}, ["value"], 1, 1.5, True, None):
        _assert_schema_valid(schema, {**envelope, "content": content})


def test_contract_schemas_are_valid_json_schema():
    contract = _load_contract()
    Draft202012Validator.check_schema(contract["record_schema"])
    for event in contract["events"]:
        Draft202012Validator.check_schema(event["content_schema"])
        Draft202012Validator.check_schema(event["metadata_schema"])
    for pattern in contract["dynamic_event_patterns"]:
        Draft202012Validator.check_schema(pattern["event_type_schema"])
        Draft202012Validator.check_schema(pattern["tag_schema"])
        Draft202012Validator.check_schema(pattern["content_schema"])
        Draft202012Validator.check_schema(pattern["metadata_schema"])


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["memory", "jsonl"])
async def test_non_database_stores_return_contract_records(backend, tmp_path):
    if backend == "memory":
        store = MemoryRunEventStore()
    else:
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        store = JsonlRunEventStore(base_dir=tmp_path / "events")

    record = await store.put(
        thread_id="thread-1",
        run_id="run-1",
        event_type="context:memory",
        category="context",
        content={"content_sha256": "a" * 64},
        metadata={},
    )

    _assert_fixed_event_valid(record, persisted=True)
    assert record["seq"] == 1


@pytest.mark.anyio
async def test_database_store_returns_contract_record_with_backend_fields(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    url = f"sqlite+aiosqlite:///{tmp_path / 'events.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        store = DbRunEventStore(get_session_factory())
        record = await store.put(
            thread_id="thread-1",
            run_id="run-1",
            event_type="context:memory",
            category="context",
            content={"content_sha256": "a" * 64},
            metadata={},
        )

        _assert_fixed_event_valid(record, persisted=True)
        assert "user_id" in record
        assert record["metadata"]["content_is_json"] is True
    finally:
        await close_engine()


@pytest.mark.anyio
async def test_run_end_backend_storage_semantics_match_contract(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore
    from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

    contract_event = _contract_events()["run.end"]
    assert set(contract_event["storage_semantics"]) == {"memory", "jsonl", "database"}

    memory_event = await _record_run_end(MemoryRunEventStore())
    jsonl_event = await _record_run_end(JsonlRunEventStore(base_dir=tmp_path / "events"))

    url = f"sqlite+aiosqlite:///{tmp_path / 'run-output.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        database_event = await _record_run_end(DbRunEventStore(get_session_factory()))
    finally:
        await close_engine()

    for event in (memory_event, jsonl_event, database_event):
        _assert_fixed_event_valid(event, persisted=True)

    assert isinstance(memory_event["content"]["messages"][0], AIMessage)
    assert isinstance(jsonl_event["content"]["messages"][0], str)
    assert isinstance(database_event["content"]["messages"][0], str)
    assert "final answer" in jsonl_event["content"]["messages"][0]
    assert "final answer" in database_event["content"]["messages"][0]


@pytest.mark.anyio
async def test_run_journal_observed_events_exactly_match_its_catalog():
    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)

    root_run_id = uuid4()
    llm_run_id = uuid4()
    journal.on_chain_start(
        {"name": "root"},
        {},
        run_id=root_run_id,
        parent_run_id=None,
        tags=["lead_agent"],
        metadata={"langgraph_step": 1},
    )
    journal.on_chat_model_start(
        {},
        [[HumanMessage(content="question", id="human-1")]],
        run_id=llm_run_id,
        tags=["lead_agent"],
    )
    journal.on_llm_end(
        _make_llm_response("answer", usage={"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}),
        run_id=llm_run_id,
        parent_run_id=None,
        tags=["lead_agent"],
    )
    journal.on_tool_end(
        ToolMessage(content="tool result", tool_call_id="call-1", name="web_search", id="tool-1"),
        run_id=uuid4(),
    )
    journal.on_llm_error(RuntimeError("model failed"), run_id=uuid4())
    journal.on_chain_error(ValueError("run failed"), run_id=uuid4())
    journal.on_chain_end({"messages": []}, run_id=root_run_id, parent_run_id=None)
    journal.record_memory_context(content_sha256="a" * 64)
    await journal.flush()

    events = await store.list_events("thread-1", "run-1")
    expected_types = {definition.event_type for definition in JOURNAL_RUN_EVENT_DEFINITIONS}

    assert {event["event_type"] for event in events} == expected_types
    for event in events:
        _assert_fixed_event_valid(event, persisted=True)


@pytest.mark.anyio
@pytest.mark.parametrize("tag", MIDDLEWARE_EVENT_TAGS)
async def test_dynamic_middleware_event_matches_pattern_contract(tag):
    store = MemoryRunEventStore()
    journal = RunJournal("run-1", "thread-1", store, flush_threshold=100)
    journal.record_middleware(
        tag,
        name="GuardrailMiddleware",
        hook="wrap_tool_call",
        action="deny",
        changes={"reason": "policy"},
    )
    await journal.flush()

    event = (await store.list_events("thread-1", "run-1"))[0]
    pattern = _load_contract()["dynamic_event_patterns"][0]

    assert pattern["pattern"] == MIDDLEWARE_EVENT_PATTERN.pattern
    assert set(pattern["known_tags"]) == set(MIDDLEWARE_EVENT_TAGS)
    assert event["event_type"] == MIDDLEWARE_EVENT_PATTERN.event_type(tag)
    assert event["category"] == MIDDLEWARE_EVENT_PATTERN.category == pattern["category"]
    _assert_schema_valid(pattern["event_type_schema"], event["event_type"])
    _assert_schema_valid(pattern["tag_schema"], tag)
    _assert_schema_valid(pattern["content_schema"], event["content"])
    _assert_schema_valid(pattern["metadata_schema"], event["metadata"])


@pytest.mark.parametrize("tag", ["", "x" * (MIDDLEWARE_EVENT_TAG_MAX_LENGTH + 1)])
def test_dynamic_middleware_event_rejects_tags_that_do_not_fit_persistence(tag):
    journal = RunJournal("run-1", "thread-1", MemoryRunEventStore(), flush_threshold=100)

    with pytest.raises(ValueError):
        journal.record_middleware(
            tag,
            name="CustomMiddleware",
            hook="after_model",
            action="record",
            changes={},
        )


def test_subagent_observed_events_exactly_match_its_catalog_and_payloads():
    long_result = "r" * (SUBAGENT_STEP_MAX_CHARS + 1)
    long_error = "e" * (SUBAGENT_STEP_MAX_CHARS + 1)
    cases = [
        {"type": "task_started", "task_id": "call-1", "description": "research"},
        {
            "type": "task_running",
            "task_id": "call-1",
            "message": {
                "type": "ai",
                "content": "searching",
                "tool_calls": [{"name": "web_search", "args": {"query": "deerflow"}}],
            },
            "message_index": 1,
        },
        {
            "type": "task_running",
            "task_id": "call-1",
            "message": {"type": "tool", "name": "web_search", "content": "result"},
            "message_index": 2,
        },
        {
            "type": "task_completed",
            "task_id": "call-1",
            "result": "done",
            "model_name": "test-model",
            "usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        },
        {"type": "task_failed", "task_id": "call-2", "error": "boom"},
        {"type": "task_cancelled", "task_id": "call-3"},
        {"type": "task_timed_out", "task_id": "call-4", "error": "timed out"},
        {"type": "task_completed", "task_id": "call-5", "result": long_result},
        {"type": "task_failed", "task_id": "call-6", "error": long_error},
    ]

    records = [subagent_run_event(case) for case in cases]
    assert all(record is not None for record in records)
    typed_records = [record for record in records if record is not None]
    expected_types = {definition.event_type for definition in SUBAGENT_RUN_EVENT_DEFINITIONS}

    assert {record["event_type"] for record in typed_records} == expected_types
    for record in typed_records:
        _assert_fixed_event_valid(record)

    ai_step, tool_step = typed_records[1]["content"], typed_records[2]["content"]
    completed, failed = typed_records[3]["content"], typed_records[4]["content"]
    timed_out = typed_records[6]["content"]
    truncated_result, truncated_error = typed_records[7]["content"], typed_records[8]["content"]
    assert ai_step["tool_calls"][0]["name"] == "web_search"
    assert tool_step["tool_name"] == "web_search"
    assert completed["result"] == "done"
    assert completed["model_name"] == "test-model"
    assert completed["usage"]["total_tokens"] == 7
    assert failed["error"] == "boom"
    assert timed_out["error"] == "timed out"
    assert len(truncated_result["result"]) == SUBAGENT_STEP_MAX_CHARS
    assert truncated_result["result_truncated"] is True
    assert len(truncated_error["error"]) == SUBAGENT_STEP_MAX_CHARS
    assert truncated_error["error_truncated"] is True
    assert {record["content"]["status"] for record in typed_records[3:]} == {
        "completed",
        "failed",
        "cancelled",
        "timed_out",
    }


def test_captured_subagent_message_survives_task_running_conversion():
    captured: list[dict] = []
    assert capture_step_message(
        AIMessage(
            content="searching",
            id="ai-step-1",
            tool_calls=[{"id": "call-1", "name": "web_search", "args": {"query": "deerflow"}}],
        ),
        captured,
        set(),
    )

    event = subagent_run_event(
        {
            "type": "task_running",
            "task_id": "task-1",
            "message": captured[0],
            "message_index": 0,
        }
    )

    assert event is not None
    assert event["event_type"] == "subagent.step"
    assert event["content"]["task_id"] == "task-1"
    assert event["content"]["message_index"] == 0
    assert event["content"]["text"] == "searching"
    assert event["content"]["tool_calls"] == [{"name": "web_search", "args": {"query": "deerflow"}}]
    _assert_fixed_event_valid(event)


@pytest.mark.parametrize(
    "chunk",
    [
        {"type": "task_started", "description": "missing task id"},
        {"type": "task_started", "task_id": "", "description": "empty task id"},
        {"type": "task_started", "task_id": "call-1", "description": 42},
        {"type": "task_running", "task_id": "call-1", "message": {"type": "ai"}},
        {"type": "task_running", "task_id": "call-1", "message": {"type": "ai"}, "message_index": -1},
        {"type": "task_running", "task_id": "call-1", "message": {"type": "ai"}, "message_index": True},
        {"type": "task_running", "task_id": "call-1", "message": "not-an-object", "message_index": 0},
        {"type": "task_completed"},
    ],
)
def test_subagent_producer_rejects_chunks_missing_contract_fields(chunk):
    assert subagent_run_event(chunk) is None


@pytest.mark.anyio
@pytest.mark.parametrize("backend", ["memory", "jsonl"])
async def test_subagent_batch_round_trip_matches_contract_for_non_database_stores(backend, tmp_path):
    if backend == "memory":
        store = MemoryRunEventStore()
    else:
        from deerflow.runtime.events.store.jsonl import JsonlRunEventStore

        store = JsonlRunEventStore(base_dir=tmp_path / "subagent-events")

    records = await _persist_subagent_batch(store)

    assert [record["event_type"] for record in records] == ["subagent.start", "subagent.step", "subagent.end"]
    for record in records:
        _assert_fixed_event_valid(record, persisted=True)


@pytest.mark.anyio
async def test_subagent_batch_round_trip_matches_contract_for_database_store(tmp_path):
    from deerflow.persistence.engine import close_engine, get_session_factory, init_engine
    from deerflow.runtime.events.store.db import DbRunEventStore

    url = f"sqlite+aiosqlite:///{tmp_path / 'subagent-events.db'}"
    await init_engine("sqlite", url=url, sqlite_dir=str(tmp_path))
    try:
        records = await _persist_subagent_batch(DbRunEventStore(get_session_factory()))
    finally:
        await close_engine()

    assert [record["event_type"] for record in records] == ["subagent.start", "subagent.step", "subagent.end"]
    for record in records:
        _assert_fixed_event_valid(record, persisted=True)


@pytest.mark.anyio
async def test_workspace_change_producer_matches_catalog_and_payload(monkeypatch, tmp_path):
    from deerflow.workspace_changes import WorkspaceRoot, scan_workspace_roots
    from deerflow.workspace_changes import recorder as recorder_module

    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    outputs.mkdir()
    roots = [
        WorkspaceRoot("workspace", workspace, "/mnt/user-data/workspace"),
        WorkspaceRoot("outputs", outputs, "/mnt/user-data/outputs"),
    ]
    before = scan_workspace_roots(roots)
    (workspace / "report.md").write_text("# Report\n", encoding="utf-8")
    monkeypatch.setattr(recorder_module, "build_thread_workspace_roots", lambda *_args, **_kwargs: roots)

    store = MemoryRunEventStore()
    record = await recorder_module.record_workspace_changes(store, "thread-1", "run-1", before)

    assert record is not None
    assert {record["event_type"]} == {definition.event_type for definition in WORKSPACE_RUN_EVENT_DEFINITIONS}
    _assert_fixed_event_valid(record, persisted=True)


def test_known_gaps_do_not_reclassify_current_events_as_missing():
    contract = _load_contract()
    gap_ids = {gap["id"] for gap in contract["known_gaps"]}
    current_types = {definition.event_type for definition in FIXED_RUN_EVENT_DEFINITIONS}

    assert {"tool-call-intent", "terminal-run-status"}.issubset(gap_ids)
    assert all(gap.get("event_type") not in current_types for gap in contract["known_gaps"])
