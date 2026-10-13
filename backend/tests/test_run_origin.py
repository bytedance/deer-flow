"""Server-owned ``deerflow_origin`` on runs and threads.

Only server-side launchers (scheduler, MCP notifications, extension handles,
via ``request.state.run_origin``) and the internal channel caller (via
``body.metadata``) may stamp it; every client copy is dropped from both
metadata forks of run admission (the run record and the live config, which is
what reaches checkpoint metadata). ``RunRepository`` derives
``runs.origin_kind`` from it.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.gateway.auth.models import User
from app.gateway.authz import AuthContext
from app.gateway.extension_agent_runs import GatewayAgentRunsHost
from app.gateway.internal_auth import INTERNAL_OWNER_USER_ID_HEADER_NAME, get_internal_user
from app.gateway.run_models import RunCreateRequest
from app.gateway.run_origin import resolve_request_origin
from deerflow.persistence.base import Base
from deerflow.persistence.run import RunRepository
from deerflow.persistence.run.model import RunChangeClockRow, RunRow
from deerflow.runtime.run_origin import DEERFLOW_ORIGIN_KEY, ORIGIN_KINDS, admit_origin, make_origin, origin_kind_of

CONTRACT = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "thread_origin_contract.json").read_text())


# ---------------------------------------------------------------------------
# The origin value itself
# ---------------------------------------------------------------------------


def test_contract_matches_the_module():
    assert CONTRACT["version"] == 1
    assert CONTRACT["key"] == DEERFLOW_ORIGIN_KEY
    assert sorted(CONTRACT["kinds"]) == CONTRACT["kinds"]
    assert set(CONTRACT["kinds"]) == ORIGIN_KINDS


def test_origin_key_is_distinct_from_the_message_level_scheduled_origin_key():
    from app.gateway.services import SCHEDULED_ORIGIN_KEY

    notes = json.loads((Path(__file__).resolve().parents[2] / "contracts" / "scheduled_goal_notes_contract.json").read_text())
    assert DEERFLOW_ORIGIN_KEY != SCHEDULED_ORIGIN_KEY == notes["scheduled_origin_key"]


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "schedule"},
        {"kind": "im_channel", "provider": "feishu"},
        {"kind": "github", "provider": "github"},
        {"kind": "extension", "namespace": "community.agent-teams"},
        {"kind": "mcp_notification"},
    ],
)
def test_well_formed_origins_are_admitted(value):
    assert admit_origin(value) == value
    assert origin_kind_of({DEERFLOW_ORIGIN_KEY: value}) == value["kind"]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "schedule",
        {},
        {"kind": "browser"},
        {"kind": "schedule", "extra": "x"},
        {"kind": "im_channel", "provider": "Feishu"},
        {"kind": "im_channel", "provider": "x" * 33},
        {"kind": "im_channel", "provider": 1},
        {"kind": "extension", "namespace": "a:b"},
        {"kind": "extension", "namespace": ""},
        {"kind": "extension", "namespace": "n" * 97},
        {"kind": True},
    ],
)
def test_malformed_origins_are_dropped_whole(value):
    assert admit_origin(value) is None
    assert origin_kind_of({DEERFLOW_ORIGIN_KEY: value}) is None


def test_make_origin_rejects_malformed_values():
    assert make_origin("im_channel", provider="slack") == {"kind": "im_channel", "provider": "slack"}
    with pytest.raises(ValueError):
        make_origin("browser")
    with pytest.raises(ValueError):
        make_origin("extension", namespace="bad:ns")


def test_origin_kind_of_tolerates_missing_metadata():
    assert origin_kind_of(None) is None
    assert origin_kind_of({}) is None
    assert origin_kind_of([("deerflow_origin", {"kind": "schedule"})]) is None


def test_request_origin_trusts_only_host_state_and_internal_callers():
    origin = {"kind": "im_channel", "provider": "slack"}
    body = {DEERFLOW_ORIGIN_KEY: origin}
    # Session/PAT/API callers: the body copy is ignored.
    assert resolve_request_origin(SimpleNamespace(state=SimpleNamespace(auth_source="session")), body) is None
    assert resolve_request_origin(SimpleNamespace(state=SimpleNamespace(auth_source="pat")), body) is None
    assert resolve_request_origin(SimpleNamespace(), body) is None
    # The internal channel caller may declare it; invalid shapes still drop.
    internal = SimpleNamespace(state=SimpleNamespace(auth_source="internal"))
    assert resolve_request_origin(internal, body) == origin
    assert resolve_request_origin(internal, {DEERFLOW_ORIGIN_KEY: {"kind": "schedule", "x": 1}}) is None
    assert resolve_request_origin(internal, None) is None
    # A host-set origin wins over anything in the body.
    host = SimpleNamespace(state=SimpleNamespace(auth_source="internal", run_origin={"kind": "schedule"}))
    assert resolve_request_origin(host, body) == {"kind": "schedule"}


# ---------------------------------------------------------------------------
# Run admission through a real Gateway composition (SQL run store, real graph)
# ---------------------------------------------------------------------------

_USER = User(email="origin@example.com")
OWNER = str(_USER.id)


@pytest_asyncio.fixture
async def gateway(monkeypatch, tmp_path):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import MessagesState, StateGraph
    from langgraph.store.memory import InMemoryStore

    from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
    from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
    from deerflow.runtime import RunManager
    from deerflow.runtime.events.store.memory import MemoryRunEventStore
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'runs.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync: Base.metadata.create_all(sync, tables=[RunRow.__table__, RunChangeClockRow.__table__]))
    sf = async_sessionmaker(engine, expire_on_commit=False)

    app = FastAPI()
    state = app.state
    state.checkpointer = InMemorySaver()
    state.store = InMemoryStore()
    state.thread_store = MemoryThreadMetaStore(state.store)
    state.run_store = RunRepository(sf)
    state.run_manager = RunManager(store=state.run_store)
    state.run_event_store = MemoryRunEventStore()
    state.stream_bridge = MemoryStreamBridge()
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))

    def factory(*, config):
        builder = StateGraph(MessagesState)
        builder.add_node("answer", lambda _state: {"messages": [AIMessage(content="done")]})
        builder.set_entry_point("answer")
        builder.set_finish_point("answer")
        return builder.compile()

    monkeypatch.setattr("app.gateway.services.resolve_agent_factory", lambda _: factory)
    monkeypatch.setattr("app.gateway.services.get_local_provider", lambda: SimpleNamespace(get_user=AsyncMock(return_value=_USER)))
    host = GatewayAgentRunsHost(app, load_user=AsyncMock(return_value=_USER))
    state.agent_runs_host = host
    try:
        yield app, sf
    finally:
        host.close()
        await state.run_manager.shutdown()
        reset_app_config()
        await engine.dispose()


def _session_request(app):
    request = Request({"type": "http", "app": app, "headers": [], "state": {}})
    request.state.user = _USER
    request.state.auth_source = "session"
    request.state.auth = AuthContext(_USER, ["threads:write", "threads:read", "runs:create", "runs:read", "runs:cancel"])
    return request


def _internal_request(app, owner=OWNER):
    return SimpleNamespace(app=app, headers={INTERNAL_OWNER_USER_ID_HEADER_NAME: owner}, state=SimpleNamespace(user=get_internal_user(), auth_source="internal"), cookies={})


def _body(**kwargs):
    return RunCreateRequest(assistant_id="lead_agent", input={"messages": [{"role": "user", "content": "hi"}]}, **kwargs)


async def _start(app, request, body, thread_id):
    from app.gateway.services import start_run

    record = await start_run(body, thread_id, request)
    await record.task
    return record


async def _origin_kind(sf, run_id):
    async with sf() as session:
        return (await session.get(RunRow, run_id)).origin_kind


async def _checkpoint_metadata(app, thread_id):
    checkpoint = await app.state.checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})
    assert checkpoint is not None
    return checkpoint.metadata


@pytest.mark.asyncio
async def test_session_caller_cannot_forge_an_origin_in_body_metadata(gateway):
    app, sf = gateway
    record = await _start(app, _session_request(app), _body(metadata={DEERFLOW_ORIGIN_KEY: {"kind": "schedule"}, "kept": 1}), "forged-body")
    assert DEERFLOW_ORIGIN_KEY not in record.metadata
    assert record.metadata["kept"] == 1
    assert await _origin_kind(sf, record.run_id) is None
    stored = await app.state.run_store.get(record.run_id, user_id=None)
    assert DEERFLOW_ORIGIN_KEY not in stored["metadata"]
    assert DEERFLOW_ORIGIN_KEY not in await _checkpoint_metadata(app, "forged-body")
    # The thread this run auto-created carries no marker either.
    assert DEERFLOW_ORIGIN_KEY not in (await app.state.thread_store.get("forged-body", user_id=None))["metadata"]


@pytest.mark.asyncio
async def test_client_origin_in_config_metadata_is_dropped(gateway, monkeypatch):
    app, sf = gateway
    captured = {}
    from app.gateway import services

    real_run_agent = services.run_agent

    async def capture(*args, **kwargs):
        captured["config"] = kwargs["config"]
        return await real_run_agent(*args, **kwargs)

    monkeypatch.setattr("app.gateway.services.run_agent", capture)
    body = _body(config={"metadata": {DEERFLOW_ORIGIN_KEY: {"kind": "schedule"}, "caller_key": "kept"}})
    record = await _start(app, _session_request(app), body, "forged-config")
    assert DEERFLOW_ORIGIN_KEY not in captured["config"]["metadata"]
    assert captured["config"]["metadata"]["caller_key"] == "kept"
    assert DEERFLOW_ORIGIN_KEY not in record.metadata
    assert await _origin_kind(sf, record.run_id) is None
    assert DEERFLOW_ORIGIN_KEY not in await _checkpoint_metadata(app, "forged-config")

    # An internal caller's server-resolved origin overrides a conflicting copy.
    origin = {"kind": "im_channel", "provider": "slack"}
    body = _body(metadata={DEERFLOW_ORIGIN_KEY: origin}, config={"metadata": {DEERFLOW_ORIGIN_KEY: {"kind": "extension"}}})
    record = await _start(app, _internal_request(app), body, "internal-config")
    assert captured["config"]["metadata"][DEERFLOW_ORIGIN_KEY] == origin
    assert record.metadata[DEERFLOW_ORIGIN_KEY] == origin
    assert await _origin_kind(sf, record.run_id) == "im_channel"
    # LangGraph copies only scalar config metadata into checkpoints, so the
    # origin object lives on the run (record and runs.origin_kind), not there.
    assert DEERFLOW_ORIGIN_KEY not in await _checkpoint_metadata(app, "internal-config")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"kind": "github", "provider": "github"}, "github"),
        ({"kind": "im_channel", "provider": "feishu", "extra": True}, None),
        ({"kind": "browser"}, None),
    ],
    ids=["valid", "extra-key", "unknown-kind"],
)
async def test_internal_caller_origin_is_kept_only_when_well_formed(gateway, value, expected):
    app, sf = gateway
    record = await _start(app, _internal_request(app), _body(metadata={DEERFLOW_ORIGIN_KEY: value}), f"internal-{expected}")
    assert await _origin_kind(sf, record.run_id) == expected
    assert record.user_id == OWNER
    if expected is None:
        assert DEERFLOW_ORIGIN_KEY not in record.metadata
    else:
        assert record.metadata[DEERFLOW_ORIGIN_KEY] == value


@pytest.mark.asyncio
async def test_scheduled_launch_stamps_run_and_fresh_thread(gateway):
    from app.gateway.services import launch_scheduled_thread_run

    app, sf = gateway
    result = await launch_scheduled_thread_run(
        app=app,
        thread_id="sched-run-thread",
        assistant_id="lead_agent",
        prompt="check",
        owner_user_id=OWNER,
        metadata={"scheduled_task_id": "task-1", "scheduled_task_run_id": "occurrence-1", "scheduled_trigger": "manual"},
    )
    await (await app.state.run_manager.get(result["run_id"])).task
    stored = await app.state.run_store.get(result["run_id"], user_id=None)
    assert stored["metadata"][DEERFLOW_ORIGIN_KEY] == {"kind": "schedule"}
    assert stored["origin_kind"] == "schedule"
    assert stored["user_id"] == OWNER
    thread = await app.state.thread_store.get("sched-run-thread", user_id=OWNER)
    assert thread["metadata"][DEERFLOW_ORIGIN_KEY] == {"kind": "schedule"}


@pytest.mark.asyncio
async def test_mcp_notification_launch_stamps_run_but_not_the_existing_thread(gateway):
    from app.gateway.services import launch_mcp_task_notification_run

    app, sf = gateway
    await app.state.thread_store.create("mcp-thread", user_id=OWNER, metadata={"title": "chat"})
    result = await launch_mcp_task_notification_run(
        app=app,
        thread_id="mcp-thread",
        assistant_id="lead_agent",
        owner_user_id=OWNER,
        task_id="remote-1",
        dispatch_version=1,
        dispatch_attempt=1,
        event={"status": "completed"},
    )
    await (await app.state.run_manager.get(result["run_id"])).task
    assert await _origin_kind(sf, result["run_id"]) == "mcp_notification"
    thread = await app.state.thread_store.get("mcp-thread", user_id=OWNER)
    assert thread["metadata"] == {"title": "chat"}


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", [None, "community.agent-teams"])
async def test_extension_handle_marks_its_threads_and_runs(gateway, monkeypatch, namespace):
    app, sf = gateway
    request = _session_request(app)
    monkeypatch.setattr("app.gateway.extension_agent_runs.resolve_route_permissions", AsyncMock(return_value=list(request.state.auth.permissions)))
    runs = app.state.agent_runs_host.bind(request)
    if namespace is not None:
        runs = runs.for_plugin(namespace)
    expected = make_origin("extension", namespace=namespace)

    thread_id = await runs.create_thread(thread_id="extension-thread", metadata={DEERFLOW_ORIGIN_KEY: {"kind": "schedule"}, "keep": "me"})
    thread = await app.state.thread_store.get(thread_id, user_id=OWNER)
    assert thread["metadata"][DEERFLOW_ORIGIN_KEY] == expected
    assert thread["metadata"]["keep"] == "me"

    run = await runs.start(thread_id=thread_id, input={"messages": [{"role": "user", "content": "go"}]})
    await runs.wait(thread_id=thread_id, run_id=run.run_id, timeout=5)
    assert await _origin_kind(sf, run.run_id) == "extension"
    assert (await app.state.run_store.get(run.run_id, user_id=None))["metadata"][DEERFLOW_ORIGIN_KEY] == expected


# ---------------------------------------------------------------------------
# IM channels and GitHub: the manager declares the origin on every run call
# ---------------------------------------------------------------------------


def _manager():
    from app.channels.manager import ChannelManager
    from app.channels.message_bus import MessageBus
    from app.channels.store import ChannelStore

    return ChannelManager(bus=MessageBus(), store=ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json"))


def _client(thread_id="im-thread"):
    client = MagicMock()
    client.threads.create = AsyncMock(return_value={"thread_id": thread_id})
    client.threads.update = AsyncMock(return_value={"thread_id": thread_id})
    client.threads.get = AsyncMock(return_value={"thread_id": thread_id})
    client.runs.wait = AsyncMock(return_value={"messages": [{"type": "ai", "content": "ok"}]})
    client.runs.create = AsyncMock(return_value={"run_id": "run-1", "status": "pending"})

    async def _stream(*_args, **_kwargs):
        yield SimpleNamespace(event="values", data={"messages": [{"type": "ai", "content": "ok"}]})

    client.runs.stream = MagicMock(side_effect=_stream)
    return client


def _message(channel="slack", **kwargs):
    from app.channels.message_bus import InboundMessage

    return InboundMessage(channel_name=channel, chat_id="chat-1", user_id="platform-user", owner_user_id="owner-1", text="hello", **kwargs)


@pytest.mark.asyncio
async def test_channel_wait_run_declares_im_origin():
    manager = _manager()
    client = _client()
    manager._client = client
    await manager._handle_chat(_message("slack"))
    client.runs.wait.assert_called_once()
    assert client.runs.wait.call_args.kwargs["metadata"] == {DEERFLOW_ORIGIN_KEY: {"kind": "im_channel", "provider": "slack"}}


@pytest.mark.asyncio
async def test_channel_stream_run_declares_im_origin():
    manager = _manager()
    client = _client()
    await manager._handle_streaming_chat(client, _message("feishu"), "im-thread", "lead_agent", {}, {}, {"role": "user", "content": "hello"})
    client.runs.stream.assert_called_once()
    assert client.runs.stream.call_args.kwargs["metadata"] == {DEERFLOW_ORIGIN_KEY: {"kind": "im_channel", "provider": "feishu"}}


@pytest.mark.asyncio
async def test_github_create_run_declares_github_origin():
    import app.gateway.github.run_policy  # noqa: F401 - registers the fire-and-forget policy

    manager = _manager()
    client = _client("gh-thread")
    manager._client = client
    await manager._handle_chat(_github_message())
    client.runs.create.assert_called_once()
    assert client.runs.create.call_args.kwargs["metadata"] == {DEERFLOW_ORIGIN_KEY: {"kind": "github", "provider": "github"}}


def _github_message(text="please fix"):
    from app.channels.message_bus import InboundMessage

    return InboundMessage(channel_name="github", chat_id="org/repo", user_id="octocat", owner_user_id="owner-1", text=text)


@pytest.mark.asyncio
async def test_followup_drain_declares_the_carrier_origin():
    manager = _manager()
    client = _client("gh-thread")
    for index in range(2):
        manager._buffer_followup("gh-thread", _github_message(f"comment {index}"))
    await manager._drain_followups_for_thread(client, "gh-thread", _github_message("carrier"))
    client.runs.create.assert_called_once()
    assert client.runs.create.call_args.kwargs["metadata"] == {DEERFLOW_ORIGIN_KEY: {"kind": "github", "provider": "github"}}


def test_unusable_channel_name_sends_no_origin():
    from app.channels.manager import _apply_run_origin

    kwargs = {}
    _apply_run_origin(kwargs, _message("Bad Channel"))
    assert "metadata" not in kwargs
