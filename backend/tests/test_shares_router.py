"""Real HTTP/auth, SQL shares, checkpoints, history and host file copies."""

import asyncio
import json
import os
import stat
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Overwrite
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from support.postgres import asyncpg_test_url

import deerflow.persistence.models  # noqa: F401
from app.gateway import extension_artifacts, history_seed, share_fork, share_snapshot
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware, _is_public
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import shares, threads
from app.gateway.services import build_checkpoint_state_mutation_accessor
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.persistence.postgres_schema import build_asyncpg_connect_args
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.runtime import ConflictError, RunManager, ThreadOperationKind
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.user_context import reset_current_user, set_current_user

ALICE = User(id=UUID(int=1), email="alice@example.com", password_hash="unused", system_role="admin")
BOB = User(id=UUID(int=2), email="bob@example.com", password_hash="unused", system_role="user")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "posix", reason="descriptor-confined artifact capture requires POSIX")]


@pytest_asyncio.fixture(params=[("full", "memory", "sqlite"), ("delta", "memory", "sqlite"), ("full", "db", "sqlite"), ("delta", "db", "sqlite"), ("full", "db", "postgres")])
async def share_app(tmp_path, monkeypatch, request):
    schema = None
    if request.param[2] == "postgres":
        uri = os.environ.get("TEST_POSTGRES_URI")
        if not uri:
            pytest.skip("requires TEST_POSTGRES_URI")
        schema = "share_http_" + uuid4().hex
        engine = create_async_engine(asyncpg_test_url(uri), connect_args=build_asyncpg_connect_args(schema))
    else:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'http.db'}")
    async with engine.begin() as connection:
        if schema:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(shares, "get_session_factory", lambda: factory)
    monkeypatch.setattr("app.gateway.auth_middleware.is_auth_disabled", lambda: False)
    monkeypatch.setattr("app.gateway.csrf_middleware.is_auth_disabled", lambda: False)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: AuthorizationConfig())

    async def session_user(req):
        user = {"alice": ALICE, "bob": BOB}.get(req.cookies.get("access_token"))
        if not user:
            raise HTTPException(401, "Invalid session")
        return user

    monkeypatch.setattr("app.gateway.deps.get_current_user_from_request", session_user)
    paths = Paths(base_dir=tmp_path / "home")
    monkeypatch.setattr(extension_artifacts, "get_paths", lambda: paths)
    monkeypatch.setattr(share_fork, "get_paths", lambda: paths)
    monkeypatch.setattr(extension_artifacts, "get_sandbox_provider", lambda: SimpleNamespace(uses_thread_data_mounts=True))
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.state.thread_store = ThreadMetaRepository(factory)
    app.state.checkpointer = InMemorySaver()
    app.state.run_event_store = DbRunEventStore(factory) if request.param[1] == "db" else MemoryRunEventStore()
    app.state.run_manager = RunManager(store=RunRepository(factory), event_store=app.state.run_event_store)
    app.state.checkpoint_channel_mode = request.param[0]
    app.state.store = None
    app.include_router(shares.router)
    app.include_router(threads.router)
    req = Request({"type": "http", "app": app})

    async def accessor(req, *, thread_id, **kwargs):
        # Replace agent/model assembly only. Materialization and writes use
        # the actual full/delta accessor over the real checkpoint store.
        return build_checkpoint_state_mutation_accessor(req, thread_id=thread_id, as_node="branch")

    monkeypatch.setattr(share_snapshot, "build_thread_checkpoint_state_accessor", accessor)
    await app.state.thread_store.create("source", user_id=str(ALICE.id), display_name="Shared report")
    paths.sandbox_outputs_dir("source", user_id=str(ALICE.id)).mkdir(parents=True)
    output = paths.sandbox_outputs_dir("source", user_id=str(ALICE.id)) / "report.html"
    output.write_text("<h1>Original report</h1><script>parent.pwned=true</script>", encoding="utf-8")
    messages = [HumanMessage(content="Visible question", id="h1", additional_kwargs={"files": [{"path": "private-upload"}]})]
    messages += [AIMessage(content=f"Step {i}", id=f"ai-{i}") for i in range(205)]
    messages += [ToolMessage(content="tool result", name="search", tool_call_id="c1", id="tool"), AIMessage(content="Final report", id="answer")]
    hidden = AIMessage(content="private control", id="hidden", additional_kwargs={"hide_from_ui": True})
    events = build_branch_history_seed_events([*messages, hidden, SystemMessage(content="secret prompt")], thread_id="source", run_id_prefix="source-run", parent_thread_id="source")
    user_token = set_current_user(ALICE)
    try:
        await app.state.run_event_store.put_batch(events)
    finally:
        reset_current_user(user_token)
    if request.param[1] == "db":
        app.state.run_event_store._producer_fencing = "strict"
    state, config = await accessor(req, thread_id="source")
    config = await state.aupdate(config, {"messages": messages[-1:], "artifacts": ["/mnt/user-data/outputs/report.html"]}, as_node="branch")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield SimpleNamespace(app=app, client=client, paths=paths, output=output, state=state, config=config, request=req, factory=factory)
    finally:
        if schema:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        await engine.dispose()


def headers(user="alice", csrf=True):
    return {"Cookie": f"access_token={user}; csrf_token=test-csrf", **({"X-CSRF-Token": "test-csrf"} if csrf else {})}


async def make_share(ctx):
    response = await ctx.client.post("/api/threads/source/shares", json={}, headers=headers())
    assert response.status_code == 201, response.text
    return response.json()


async def test_anonymous_snapshot_and_files_are_immutable_and_scoped(share_app):
    ctx = share_app
    share = await make_share(ctx)
    url = f"/api/shares/{share['token']}"
    response = await ctx.client.get(url)
    assert response.status_code == 200
    body = response.json()
    assert len(body["messages"]) == 208  # whole paginated history, not the compacted head
    assert body["messages"][0]["content"] == "Visible question"
    assert body["messages"][-1]["content"] == "Final report"
    assert "private-upload" not in response.text and "secret prompt" not in response.text and "private control" not in response.text
    assert response.headers["cache-control"] == "no-store"
    ctx.output.write_text("changed file", encoding="utf-8")
    await ctx.state.aupdate(ctx.config, {"messages": [AIMessage(content="Later private answer", id="later")]}, as_node="branch")
    assert (await ctx.client.get(url)).json() == body
    artifact = await ctx.client.get(url + "/artifacts/report.html")
    assert "Original report" in artifact.text
    assert "sandbox" in artifact.headers["content-security-policy"]
    assert "allow-scripts" not in artifact.headers["content-security-policy"]
    assert artifact.headers["referrer-policy"] == "no-referrer"
    ranged = await ctx.client.get(url + "/artifacts/report.html", headers={"Range": "bytes=0-3"})
    assert ranged.status_code == 206 and ranged.content == b"<h1>"
    assert (await ctx.client.get(url + "/artifacts/private-upload")).status_code == 404
    assert (await ctx.client.get("/api/threads/source/state")).status_code == 401
    assert (await ctx.client.get("/api/threads/source/state", headers=headers("bob"))).status_code == 404


async def test_share_mutations_require_owner_and_csrf(share_app):
    ctx = share_app
    assert (await ctx.client.post("/api/threads/source/shares", json={}, headers=headers("bob"))).status_code == 404
    assert (await ctx.client.post("/api/threads/source/shares", json={}, headers=headers(csrf=False))).status_code == 403
    assert (await ctx.client.post("/api/threads/source/shares", json={"expires_in_seconds": 0}, headers=headers())).status_code == 422
    assert (await ctx.client.post("/api/threads/source/shares", json={"checkpoint_id": "old"}, headers=headers())).status_code == 409
    async with ctx.app.state.run_manager.reserve_thread_operation("source", kind=ThreadOperationKind.artifact_write, user_id=str(ALICE.id)):
        assert (await ctx.client.post("/api/threads/source/shares", json={}, headers=headers())).status_code == 409
    share = await make_share(ctx)
    path = f"/api/threads/source/shares/{share['share_id']}"
    assert (await ctx.client.delete(path, headers=headers("bob"))).status_code == 404
    assert (await ctx.client.delete(path, headers=headers())).status_code == 204
    public = f"/api/shares/{share['token']}"
    assert (await ctx.client.get(public)).status_code == 404
    assert (await ctx.client.get(public + "/artifacts/report.html")).status_code == 404
    assert (await ctx.client.post(public + "/fork", json={"request_id": str(uuid4())}, headers=headers("bob"))).status_code == 404


async def test_pdf_preview_uses_browser_viewer_without_sandbox(share_app):
    ctx = share_app
    pdf = b"%PDF-1.4\n% Frozen PDF bytes\n%%EOF"
    ctx.output.with_name("report.pdf").write_bytes(pdf)
    await ctx.state.aupdate(ctx.config, {"artifacts": ["/mnt/user-data/outputs/report.pdf"]}, as_node="branch")
    share = await make_share(ctx)
    response = await ctx.client.get(f"/api/shares/{share['token']}/artifacts/report.pdf")
    assert response.content == pdf
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "sandbox" not in response.headers.get("content-security-policy", "")


async def test_fork_is_owned_by_visitor_and_survives_revocation(share_app):
    ctx = share_app
    share = await make_share(ctx)
    url = f"/api/shares/{share['token']}/fork"
    body = {"request_id": str(uuid4())}
    assert (await ctx.client.post(url, json=body)).status_code in {401, 403}
    response = await ctx.client.post(url, json=body, headers=headers("bob"))
    assert response.status_code == 200, response.text
    new_id = response.json()["thread_id"]
    assert (await ctx.client.post(url, json=body, headers=headers("bob"))).json() == {"thread_id": new_id}
    row = await ctx.app.state.thread_store.get(new_id, user_id=str(BOB.id))
    assert row and row["assistant_id"] is None
    assert await ctx.app.state.thread_store.get(new_id, user_id=str(ALICE.id)) is None
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=new_id, as_node="branch")
    state = await accessor.aget(config)
    assert len(state.values["messages"]) == 208
    assert all(m.type in {"human", "ai"} for m in state.values["messages"])
    assert "sandbox" not in state.values
    assert len(await ctx.app.state.run_event_store.list_messages(new_id, limit=1000, user_id=str(BOB.id))) == 208
    copied = ctx.paths.sandbox_outputs_dir(new_id, user_id=str(BOB.id)) / "report.html"
    assert copied.read_bytes() == ctx.output.read_bytes()
    await ctx.client.delete(f"/api/threads/source/shares/{share['share_id']}", headers=headers())
    assert copied.exists()
    # Continue with a real checkpoint write in the new owner's conversation.
    await accessor.aupdate(config, {"messages": [HumanMessage(content="Follow up", id="followup")]}, as_node="branch")
    assert (await accessor.aget(config)).values["messages"][-1].content == "Follow up"


async def test_fork_history_is_not_captured_into_recipient_memory(share_app, monkeypatch):
    from unittest.mock import MagicMock

    from langgraph.runtime import Runtime

    from deerflow.agents.middlewares import memory_middleware
    from deerflow.config.memory_config import MemoryConfig
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_KEY

    ctx = share_app
    share = await make_share(ctx)
    response = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": str(uuid4())}, headers=headers("bob"))
    assert response.status_code == 200, response.text
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=response.json()["thread_id"], as_node="branch")
    head = await accessor.aget(config)
    copied = head.values["messages"]
    assert copied and all(message.additional_kwargs.get(IMPORTED_HISTORY_KEY) == "share" for message in copied)
    assert head.values[IMPORTED_HISTORY_CHANNEL] == "share"
    # The recipient's first turn in the copy is the first memory capture for this thread.
    own = [HumanMessage(content="Bob's own question", id="bob-q"), AIMessage(content="Bob's answer", id="bob-a")]
    manager = MagicMock()
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    middleware = memory_middleware.MemoryMiddleware(memory_config=MemoryConfig(enabled=True))
    middleware.after_agent({"messages": [*copied, *own]}, Runtime(context={"thread_id": "copy", "user_id": str(BOB.id)}))
    assert [message.id for message in manager.add.call_args.args[1]] == ["bob-q", "bob-a"]
    copy = await ctx.app.state.thread_store.get(response.json()["thread_id"], user_id=str(BOB.id))
    assert copy["metadata"][share_fork.SHARE_IMPORT_HISTORY_MARKED_KEY] is True


async def _copy_from_an_earlier_build(ctx):
    """A copy as ``fork_share`` wrote it before copied messages were marked, plus one own turn."""
    thread_id = str(uuid4())
    await ctx.app.state.thread_store.create(thread_id, user_id=str(BOB.id), display_name="Old copy")
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=thread_id, as_node="branch")
    copied = [HumanMessage(content="I am Alice, CFO at Contoso", id="copied-h"), AIMessage(content="search:\nAlice's tool output", id="copied-a")]
    await accessor.aupdate(config, {"messages": Overwrite(copied), "title": "Old copy"}, as_node="branch")
    await ctx.app.state.thread_store.update_metadata(thread_id, {share_fork.SHARE_IMPORT_COMPLETE_KEY: True}, user_id=str(BOB.id))
    await accessor.aupdate(config, {"messages": [HumanMessage(content="Bob's own question", id="bob-q"), AIMessage(content="Bob's answer", id="bob-a")]}, as_node="branch")
    return thread_id, accessor, config


async def test_copy_from_an_earlier_build_is_marked_once_the_thread_is_free(share_app):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_KEY

    ctx = share_app
    threads = ctx.app.state.thread_store
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)

    def marks(snapshot):
        return {message.id: message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in snapshot.values["messages"]}

    async with ctx.app.state.run_manager.reserve_thread_operation(thread_id, kind=ThreadOperationKind.artifact_write, user_id=str(BOB.id)):
        await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=threads, metadata_timeout=5)
    assert set(marks(await accessor.aget(config)).values()) == {None}

    await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=threads, metadata_timeout=5)
    marked = await accessor.aget(config)
    # Only the turns the import wrote are someone else's; Bob's turn stays his.
    assert marks(marked) == {"copied-h": "share", "copied-a": "share", "bob-q": None, "bob-a": None}
    assert marked.values[IMPORTED_HISTORY_CHANNEL] == "share"
    assert (await threads.get(thread_id, user_id=None))["metadata"][share_fork.SHARE_IMPORT_HISTORY_MARKED_KEY] is True
    await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=threads, metadata_timeout=5)
    assert (await accessor.aget(config)).config == marked.config


async def test_copy_from_an_earlier_build_keeps_a_pending_interrupt(share_app, monkeypatch):
    from deerflow.utils.messages import IMPORTED_HISTORY_KEY

    ctx = share_app
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    build = share_fork.build_checkpoint_state_mutation_accessor

    class Paused:
        """The real accessor, reporting the head as paused before a node."""

        def __init__(self, inner):
            self.inner = inner

        async def aget(self, *args, **kwargs):
            return (await self.inner.aget(*args, **kwargs))._replace(next=("tools",))

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def paused_accessor(*args, **kwargs):
        inner, paused_config = build(*args, **kwargs)
        return Paused(inner), paused_config

    monkeypatch.setattr(share_fork, "build_checkpoint_state_mutation_accessor", paused_accessor)
    head = await accessor.aget(config)
    await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=ctx.app.state.thread_store, metadata_timeout=5)
    assert (await accessor.aget(config)).config == head.config
    assert not any(IMPORTED_HISTORY_KEY in message.additional_kwargs for message in head.values["messages"])
    assert share_fork.SHARE_IMPORT_HISTORY_MARKED_KEY not in (await ctx.app.state.thread_store.get(thread_id, user_id=None))["metadata"]


def _wire_gateway_runs(ctx, monkeypatch, tmp_path):
    """Serve real runs through the Gateway; returns the mocked memory manager."""
    from unittest.mock import AsyncMock, MagicMock

    from _agent_e2e_helpers import FakeToolCallingModel

    from app.gateway.routers import thread_runs
    from deerflow.agents.lead_agent import agent
    from deerflow.agents.middlewares import memory_middleware
    from deerflow.config import app_config
    from deerflow.persistence.projects import ProjectRepository
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    if not isinstance(ctx.app.state.run_event_store, DbRunEventStore) or ctx.app.state.checkpoint_channel_mode != "full":
        pytest.skip("exercises the gateway runtime with durable full checkpoints")
    monkeypatch.setenv("DEER_FLOW_HOME", str(ctx.paths.base_dir))
    monkeypatch.setattr("deerflow.config.paths._paths", ctx.paths)
    config = app_config.AppConfig.model_validate(
        {
            "models": [{"name": "share-test", "display_name": "Share test", "use": "langchain_openai:ChatOpenAI", "model": "unused"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "skills": {"path": str(tmp_path / "skills")},
            "tool_search": {"enabled": False},
            "memory": {"enabled": True, "injection_enabled": False},
            "title": {"enabled": False},
        }
    )
    monkeypatch.setattr(app_config, "_app_config", config)
    monkeypatch.setattr(app_config, "_app_config_is_custom", True)
    ctx.app.state.project_repo = ProjectRepository(ctx.factory)
    ctx.app.state.stream_bridge = MemoryStreamBridge()
    ctx.app.include_router(thread_runs.router)
    monkeypatch.setattr(agent, "create_chat_model", lambda **kwargs: FakeToolCallingModel(responses=[AIMessage(content="Use lst[::-1].")]))
    manager = MagicMock(aadd=AsyncMock())
    monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
    return manager


async def _run_and_capture(ctx, manager, thread_id):
    result = await ctx.client.post(f"/api/threads/{thread_id}/runs/wait", json={"input": {"messages": [{"type": "human", "content": "How do I reverse a list?"}]}}, headers=headers("bob"))
    assert result.status_code == 200, result.text
    return manager.aadd.call_args.args[1]


def _wire_manual_compaction(monkeypatch):
    """Enable compaction with a fake summary model; returns the mocked flush manager."""
    from unittest.mock import MagicMock

    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from deerflow.agents.memory import summarization_hook
    from deerflow.agents.middlewares import summarization_middleware
    from deerflow.config import app_config

    current = app_config._app_config
    monkeypatch.setattr(app_config, "_app_config", current.model_copy(update={"summarization": current.summarization.model_copy(update={"enabled": True})}))
    monkeypatch.setattr(summarization_middleware, "create_chat_model", lambda **kwargs: FakeListChatModel(responses=["SUMMARY"]))
    flush = MagicMock()
    monkeypatch.setattr(summarization_hook, "get_memory_manager", lambda: flush)
    monkeypatch.setattr(summarization_hook, "get_memory_config", lambda: SimpleNamespace(enabled=True))
    return flush


async def _compact(ctx, thread_id):
    response = await ctx.client.post(f"/api/threads/{thread_id}/compact", json={"force": True, "keep": {"type": "messages", "value": 1}}, headers=headers("bob"))
    assert response.status_code == 200 and response.json()["compacted"] is True, response.text


async def _bind_to_default_agent(accessor, config):
    """Bob already chatted in the copy on the earlier build, which bound its checkpoints to an agent."""
    from deerflow.runtime.context_keys import CHECKPOINT_AGENT_NAME_METADATA_KEY, DEFAULT_AGENT_NAME_METADATA_VALUE

    bound = {**config, "metadata": {CHECKPOINT_AGENT_NAME_METADATA_KEY: DEFAULT_AGENT_NAME_METADATA_VALUE}}
    await accessor.aupdate(bound, {"messages": [HumanMessage(content="Bob again", id="bob-q2"), AIMessage(content="Noted", id="bob-a2")]}, as_node="branch")


def _follows_copy(messages):
    from deerflow.utils.messages import FOLLOWS_IMPORTED_HISTORY_KEY

    return bool(messages) and all(message.additional_kwargs.get(FOLLOWS_IMPORTED_HISTORY_KEY) is True for message in messages)


async def test_next_run_in_a_copy_from_an_earlier_build_captures_only_the_owners_turns(share_app, monkeypatch, tmp_path):
    ctx = share_app
    manager = _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, _, _ = await _copy_from_an_earlier_build(ctx)

    captured = await _run_and_capture(ctx, manager, thread_id)
    assert [message.content for message in captured if message.type in {"human", "ai"}][:2] == ["Bob's own question", "Bob's answer"]
    assert not any("Alice" in str(message.content) for message in captured)


async def test_copy_keeps_its_provenance_through_compaction_branching_and_continuing(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_KEY

    ctx = share_app
    manager = _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    share = await make_share(ctx)
    response = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": str(uuid4())}, headers=headers("bob"))
    assert response.status_code == 200, response.text
    copy_id = response.json()["thread_id"]
    # Two own turns: compaction keeps the latest one and flushes the first.
    await _run_and_capture(ctx, manager, copy_id)
    await _run_and_capture(ctx, manager, copy_id)
    flush = _wire_manual_compaction(monkeypatch)

    # Compaction removes every copied message, and their marks with them.
    await _compact(ctx, copy_id)
    flushed = flush.add_nowait.call_args.args[1]
    assert _follows_copy(flushed) and not any(message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in flushed)
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=copy_id, as_node="branch")
    head = (await accessor.aget(config)).values["messages"]
    assert not any(message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in head)

    # A second compaction flushes a batch with no marked message left in it.
    await _run_and_capture(ctx, manager, copy_id)
    await _compact(ctx, copy_id)
    assert _follows_copy(flush.add_nowait.call_args.args[1])
    head = (await accessor.aget(config)).values["messages"]

    # A branch of the compacted copy and a run in it still capture as a copy.
    branched = await ctx.client.post(f"/api/threads/{copy_id}/branches", json={"message_id": head[-1].id}, headers=headers("bob"))
    assert branched.status_code == 200, branched.text
    assert _follows_copy(await _run_and_capture(ctx, manager, branched.json()["thread_id"]))
    assert _follows_copy(await _run_and_capture(ctx, manager, copy_id))


async def test_manual_compaction_of_an_unmigrated_copy_flushes_only_the_owners_turns(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL

    ctx = share_app
    _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    await _bind_to_default_agent(accessor, config)
    flush = _wire_manual_compaction(monkeypatch)

    # No run since the upgrade, so the copied turns are still unmarked.
    await _compact(ctx, thread_id)

    flushed = flush.add_nowait.call_args.args[1]
    # Compaction keeps the latest request, so Bob's earlier turn is what it flushes.
    assert [message.id for message in flushed] == ["bob-q", "bob-a"] and _follows_copy(flushed)
    assert (await accessor.aget(config)).values[IMPORTED_HISTORY_CHANNEL] == "share"


async def test_manual_compaction_skips_the_memory_flush_when_share_provenance_is_unknown(share_app, monkeypatch, tmp_path):
    ctx = share_app
    _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    await _bind_to_default_agent(accessor, config)
    flush = _wire_manual_compaction(monkeypatch)

    async def metadata_unavailable(*args, **kwargs):
        raise TimeoutError("metadata read timed out")

    monkeypatch.setattr(share_fork, "_read_metadata", metadata_unavailable)

    await _compact(ctx, thread_id)

    flush.add_nowait.assert_not_called()


async def test_copy_whose_import_history_is_unreadable_is_kept_out_of_memory_until_resolved(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_UNRESOLVED

    ctx = share_app
    manager = _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    await _bind_to_default_agent(accessor, config)
    flush = _wire_manual_compaction(monkeypatch)
    readable = share_fork._imported_message_ids

    async def import_checkpoint_unavailable(*args, **kwargs):
        return None

    # The metadata says legacy copy, but which turns were copied cannot be read.
    monkeypatch.setattr(share_fork, "_imported_message_ids", import_checkpoint_unavailable)
    await _compact(ctx, thread_id)
    flush.add_nowait.assert_not_called()
    assert (await accessor.aget(config)).values[IMPORTED_HISTORY_CHANNEL] == IMPORTED_HISTORY_UNRESOLVED
    result = await ctx.client.post(f"/api/threads/{thread_id}/runs/wait", json={"input": {"messages": [{"type": "human", "content": "And sets?"}]}}, headers=headers("bob"))
    assert result.status_code == 200, result.text
    manager.aadd.assert_not_called()

    # Once the import history can be read, the next run resolves it.
    monkeypatch.setattr(share_fork, "_imported_message_ids", readable)
    captured = await _run_and_capture(ctx, manager, thread_id)
    assert (await accessor.aget(config)).values[IMPORTED_HISTORY_CHANNEL] == "share"
    assert _follows_copy(captured) and not any("Alice" in str(message.content) for message in captured)
    # The turn Bob wrote while the copy was unresolved is not lost.
    assert "And sets?" in [message.content for message in captured]


def _fail_import_history_reads(ctx, monkeypatch):
    """Make reading a thread's checkpoint history raise, as an unavailable checkpoint store does."""
    checkpointer = ctx.app.state.checkpointer

    class Failing:
        def alist(self, *args, **kwargs):
            raise ConnectionError("checkpoint store unavailable")

        def __getattr__(self, name):
            return getattr(checkpointer, name)

    monkeypatch.setattr(share_fork, "get_checkpointer", lambda request: Failing())


async def test_copy_whose_import_history_read_fails_is_kept_out_of_memory(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_UNRESOLVED

    ctx = share_app
    manager = _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)

    _fail_import_history_reads(ctx, monkeypatch)
    result = await ctx.client.post(f"/api/threads/{thread_id}/runs/wait", json={"input": {"messages": [{"type": "human", "content": "And sets?"}]}}, headers=headers("bob"))

    assert result.status_code == 200, result.text
    assert (await accessor.aget(config)).values[IMPORTED_HISTORY_CHANNEL] == IMPORTED_HISTORY_UNRESOLVED
    manager.aadd.assert_not_called()


async def test_run_in_a_copy_is_refused_while_its_provenance_cannot_be_recorded(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL

    ctx = share_app
    manager = _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    build = share_fork.build_checkpoint_state_mutation_accessor

    class ReadOnly:
        """The real accessor, failing every state write."""

        def __init__(self, inner):
            self.inner = inner

        async def aupdate(self, *args, **kwargs):
            raise ConnectionError("checkpoint store unavailable")

        def __getattr__(self, name):
            return getattr(self.inner, name)

    def read_only_accessor(*args, **kwargs):
        inner, read_only_config = build(*args, **kwargs)
        return ReadOnly(inner), read_only_config

    monkeypatch.setattr(share_fork, "build_checkpoint_state_mutation_accessor", read_only_accessor)
    result = await ctx.client.post(f"/api/threads/{thread_id}/runs/wait", json={"input": {"messages": [{"type": "human", "content": "And sets?"}]}}, headers=headers("bob"))

    assert result.status_code == 503, result.text
    manager.aadd.assert_not_called()
    assert IMPORTED_HISTORY_CHANNEL not in (await accessor.aget(config)).values

    # Once provenance can be recorded, the run is admitted again.
    monkeypatch.setattr(share_fork, "build_checkpoint_state_mutation_accessor", build)
    captured = await _run_and_capture(ctx, manager, thread_id)
    assert _follows_copy(captured) and not any("Alice" in str(message.content) for message in captured)


@pytest.mark.parametrize("failure", ["missing", "read_error"])
async def test_branch_of_a_copy_with_unreadable_import_history_is_unresolved(share_app, monkeypatch, tmp_path, failure):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_UNRESOLVED

    ctx = share_app
    _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, _, _ = await _copy_from_an_earlier_build(ctx)

    async def import_checkpoint_unavailable(*args, **kwargs):
        return None

    if failure == "missing":
        monkeypatch.setattr(share_fork, "_imported_message_ids", import_checkpoint_unavailable)
    else:
        _fail_import_history_reads(ctx, monkeypatch)
    branched = await ctx.client.post(f"/api/threads/{thread_id}/branches", json={"message_id": "bob-a"}, headers=headers("bob"))

    assert branched.status_code == 200, branched.text
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=branched.json()["thread_id"], as_node="branch")
    assert (await accessor.aget(config)).values[IMPORTED_HISTORY_CHANNEL] == IMPORTED_HISTORY_UNRESOLVED


async def test_branch_of_an_unmigrated_copy_marks_the_copied_turns(share_app, monkeypatch, tmp_path):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_KEY

    ctx = share_app
    _wire_gateway_runs(ctx, monkeypatch, tmp_path)
    thread_id, _, _ = await _copy_from_an_earlier_build(ctx)

    branched = await ctx.client.post(f"/api/threads/{thread_id}/branches", json={"message_id": "bob-a"}, headers=headers("bob"))

    assert branched.status_code == 200, branched.text
    accessor, config = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=branched.json()["thread_id"], as_node="branch")
    head = await accessor.aget(config)
    assert {message.id: message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in head.values["messages"]} == {"copied-h": "share", "copied-a": "share", "bob-q": None, "bob-a": None}
    assert head.values[IMPORTED_HISTORY_CHANNEL] == "share"


async def test_copy_from_the_marking_build_gains_the_state_channel(share_app):
    from deerflow.utils.messages import IMPORTED_HISTORY_CHANNEL, IMPORTED_HISTORY_KEY

    ctx = share_app
    threads = ctx.app.state.thread_store
    thread_id, accessor, config = await _copy_from_an_earlier_build(ctx)
    # As #8422 imported it: messages already marked, no state channel yet.
    await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=threads, metadata_timeout=5)
    head = await accessor.aget(config)
    await accessor.aupdate(config, {IMPORTED_HISTORY_CHANNEL: None}, as_node="branch")

    await share_fork.ensure_share_import_history_marked(ctx.request, thread_id, threads=threads, metadata_timeout=5)

    migrated = await accessor.aget(config)
    assert migrated.values[IMPORTED_HISTORY_CHANNEL] == "share"
    assert [message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in migrated.values["messages"]] == [message.additional_kwargs.get(IMPORTED_HISTORY_KEY) for message in head.values["messages"]]


async def test_share_import_metadata_is_server_owned(share_app):
    ctx = share_app
    thread_id = str(uuid4())
    forged = {share_fork.SHARE_IMPORT_COMPLETE_KEY: True, share_fork.SHARE_IMPORT_HISTORY_MARKED_KEY: False, "keep": 1}
    response = await ctx.client.post("/api/threads", json={"thread_id": thread_id, "metadata": forged}, headers=headers("bob"))
    assert response.status_code == 200, response.text
    assert (await ctx.app.state.thread_store.get(thread_id, user_id=None))["metadata"] == {"keep": 1}


async def test_fork_rechecks_completion_after_durable_admission(share_app, monkeypatch):
    ctx = share_app
    if not isinstance(ctx.app.state.run_event_store, DbRunEventStore):
        pytest.skip("requires database-backed history and admission")
    share = await make_share(ctx)
    url = f"/api/shares/{share['token']}/fork"
    body = {"request_id": str(uuid4())}
    delayed = asyncio.Event()
    resume = asyncio.Event()
    reserves = 0
    original_reserve = share_fork._reserve_import
    first_manager = ctx.app.state.run_manager
    second_manager = RunManager(store=RunRepository(ctx.factory), event_store=ctx.app.state.run_event_store)

    @asynccontextmanager
    async def separate_worker_lock(_thread_id):
        yield

    @asynccontextmanager
    async def park_before_reservation(*args):
        nonlocal reserves
        reserves += 1
        if reserves == 1:
            delayed.set()
            await resume.wait()
        async with original_reserve(*args) as reservation:
            yield reservation

    monkeypatch.setattr(share_fork, "goal_thread_lock", separate_worker_lock)
    monkeypatch.setattr(share_fork, "_reserve_import", park_before_reservation)
    monkeypatch.setattr(history_seed, "get_run_manager", lambda request: second_manager if request.headers.get("X-Test-Worker") == "second" else first_manager)
    first = asyncio.create_task(ctx.client.post(url, json=body, headers=headers("bob")))
    async with asyncio.timeout(10):
        try:
            await delayed.wait()
            second = await ctx.client.post(url, json=body, headers={**headers("bob"), "X-Test-Worker": "second"})
            assert second.status_code == 200, second.text
            thread_id = second.json()["thread_id"]
            copied = ctx.paths.sandbox_outputs_dir(thread_id, user_id=str(BOB.id)) / "report.html"
            copied.write_bytes(b"Edited by the recipient")
        finally:
            resume.set()
            duplicate = await first
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json() == {"thread_id": thread_id}
    assert [row["thread_id"] for row in await ctx.app.state.thread_store.search(user_id=str(BOB.id))] == [thread_id]
    assert copied.read_bytes() == b"Edited by the recipient"
    assert len(await ctx.app.state.run_event_store.list_messages(thread_id, limit=1000, user_id=str(BOB.id))) == 208


async def test_fork_continues_under_recipient_run_authority(share_app, monkeypatch, tmp_path):
    from _agent_e2e_helpers import FakeToolCallingModel

    from app.gateway.routers import thread_runs
    from deerflow.agents.lead_agent import agent
    from deerflow.config import app_config
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp import cache, tools
    from deerflow.persistence.projects import ProjectRepository
    from deerflow.persistence.thread_meta.base import THREAD_PROJECT_METADATA_KEY
    from deerflow.persistence.thread_meta.model import ThreadMetaRow
    from deerflow.runtime.stream_bridge.memory import MemoryStreamBridge

    ctx = share_app
    if not isinstance(ctx.app.state.run_event_store, DbRunEventStore) or ctx.app.state.checkpoint_channel_mode != "full":
        pytest.skip("exercises the gateway runtime with durable full checkpoints")
    publisher, recipient = str(ALICE.id), str(BOB.id)
    monkeypatch.setenv("DEER_FLOW_HOME", str(ctx.paths.base_dir))
    monkeypatch.setattr("deerflow.config.paths._paths", ctx.paths)
    skill_dir = ctx.paths.user_custom_skills_dir(publisher) / "publisher-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: publisher-skill\ndescription: Publisher-only skill\n---\nPublisher-only skill body.", encoding="utf-8")
    custom_agent = ctx.paths.user_agent_dir(publisher, "publisher-agent")
    custom_agent.mkdir(parents=True)
    (custom_agent / "config.yaml").write_text("name: publisher-agent\nskills: [publisher-skill]\n", encoding="utf-8")
    (custom_agent / "SOUL.md").write_text("Publisher-only agent instructions.", encoding="utf-8")
    from deerflow.mcp.user_config import load_user_mcp_config, user_mcp_config_path

    personal_config = user_mcp_config_path(publisher)
    personal_config.parent.mkdir(parents=True, exist_ok=True)
    personal_config.write_text(json.dumps({"mcpServers": {"publisher": {"type": "http", "url": "https://fixture.example/personal", "headers": {"Authorization": "Bearer personal-publisher"}}}}), encoding="utf-8")
    assert load_user_mcp_config(publisher).mcp_servers
    assert not load_user_mcp_config(recipient).mcp_servers
    async with ctx.factory() as session:
        source = await session.get(ThreadMetaRow, "source")
        source.assistant_id = "publisher-agent"
        await session.commit()
    project = await ProjectRepository(ctx.factory).create(name="Publisher project", instructions="Publisher-only instructions", user_id=publisher)
    await ctx.app.state.thread_store.set_project("source", project["id"], user_id=publisher)
    await ctx.state.aupdate(ctx.config, {"messages": [HumanMessage(content="Publish this", additional_kwargs={"slash_skill_activation": {"skill_name": "publisher-skill"}})]}, as_node="branch")
    share = await make_share(ctx)
    fork = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": str(uuid4())}, headers=headers("bob"))
    assert fork.status_code == 200, fork.text
    destination = fork.json()["thread_id"]
    copied = await ctx.app.state.thread_store.get(destination, user_id=recipient)
    assert THREAD_PROJECT_METADATA_KEY not in copied["metadata"] and copied["assistant_id"] is None
    accessor, checkpoint = build_checkpoint_state_mutation_accessor(ctx.request, thread_id=destination, as_node="branch")
    copied_messages = (await accessor.aget(checkpoint)).values["messages"]
    assert all("slash_skill_activation" not in message.additional_kwargs for message in copied_messages)

    config = app_config.AppConfig.model_validate(
        {
            "models": [{"name": "share-test", "display_name": "Share test", "use": "langchain_openai:ChatOpenAI", "model": "unused"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "skills": {"path": str(tmp_path / "skills")},
            "tool_search": {"enabled": False},
            "memory": {"enabled": False},
            "title": {"enabled": False},
            "authorization": {
                "enabled": True,
                "provider": {
                    "use": "deerflow.authz.rbac:RbacAuthorizationProvider",
                    "config": {"roles": {"admin": {}, "user": {"tools": {"allow": "*", "deny": ["denied_tool"]}, "skills": {"allow": "*", "deny": ["restricted-skill"]}}}},
                },
            },
        }
    )
    restricted = tmp_path / "skills" / "public" / "restricted-skill"
    restricted.mkdir(parents=True)
    (restricted / "SKILL.md").write_text("---\nname: restricted-skill\ndescription: Role-restricted skill\n---\nRole-restricted skill body.", encoding="utf-8")
    monkeypatch.setattr(app_config, "_app_config", config)
    monkeypatch.setattr(app_config, "_app_config_is_custom", True)
    monkeypatch.setattr("app.gateway.authz._get_route_authorization_config", lambda: config.authorization)
    ctx.app.state.project_repo = ProjectRepository(ctx.factory)
    ctx.app.state.stream_bridge = MemoryStreamBridge()
    ctx.app.include_router(thread_runs.router)

    requests = []
    visited_paths = []

    def mcp_http(request):
        visited_paths.append(request.url.path)
        if request.method != "POST":
            return httpx.Response(405)
        payload = json.loads(request.content)
        method = payload["method"]
        if "id" not in payload:
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": payload["params"]["protocolVersion"], "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            names = {"scoped": ["scoped_probe"], "deployment": ["deployment_probe", "denied_tool"], "personal": ["publisher_only"]}[request.url.path.lstrip("/")]
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}, "description": name} for name in names]}
        else:
            assert method == "tools/call"
            requests.append((payload["params"]["name"], request.headers.get("authorization")))
            result = {"content": [{"type": "text", "text": "fixture success"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    def client_factory(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth, transport=httpx.MockTransport(mcp_http))

    original_build = tools.build_servers_config

    def build_servers(extensions):
        return {name: {**params, "httpx_client_factory": client_factory} for name, params in original_build(extensions).items()}

    monkeypatch.setattr(tools, "build_servers_config", build_servers)
    calls = []
    model_tool_names = []

    class RecordingModel(FakeToolCallingModel):
        def bind_tools(self, available, **kwargs):
            model_tool_names.append({tool.name for tool in available})
            return self

        def _generate(self, messages, *args, **kwargs):
            prompt = "\n".join(str(message.content) for message in messages)
            assert "Publisher-only instructions" not in prompt
            assert "Publisher-only agent instructions" not in prompt
            assert "Publisher-only skill" not in prompt
            assert "Role-restricted skill" not in prompt
            return super()._generate(messages, *args, **kwargs)

    def create_model(**kwargs):
        return RecordingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": name, "args": {}, "id": name} for name in ("scoped_probe", "deployment_probe", "denied_tool")],
                ),
                AIMessage(content="Recipient continuation finished."),
            ]
        )

    async def run_tool_observer(request, handler):
        context = request.runtime.context
        calls.append((context["user_id"], context["user_role"], context.get("agent_name"), context.get("project_id")))
        return await handler(request)

    from deerflow.mcp import interceptors

    original_interceptors = tools.build_mcp_tool_interceptors

    def build_interceptors(*args, **kwargs):
        return [run_tool_observer, *original_interceptors(*args, **kwargs)]

    monkeypatch.setattr(tools, "build_mcp_tool_interceptors", build_interceptors)
    monkeypatch.setattr(interceptors, "build_mcp_tool_interceptors", build_interceptors)
    monkeypatch.setattr(agent, "create_chat_model", create_model)
    for recipient_credential in ("Bearer recipient", None):
        credentials = {publisher: "Bearer publisher"}
        if recipient_credential:
            credentials[recipient] = recipient_credential
        extensions = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "scoped": {"type": "http", "url": "https://fixture.example/scoped", "tool_name_prefix": False, "headers": {"Authorization": "Bearer discovery"}, "user_auth": {"users": credentials}},
                    "deployment": {"type": "http", "url": "https://fixture.example/deployment", "tool_name_prefix": False, "headers": {"Authorization": "Bearer deployment"}},
                }
            }
        )
        monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(lambda cls, *args, **kwargs: extensions))
        loaded = await tools.get_mcp_tools(extensions)
        assert {tool.name for tool in loaded} == {"scoped_probe", "deployment_probe", "denied_tool"}
        monkeypatch.setattr(cache, "get_cached_mcp_tools", lambda: loaded)
        requests.clear()
        result = await ctx.client.post(f"/api/threads/{destination}/runs/wait", json={"input": {"messages": [{"type": "human", "content": "Continue the report"}]}}, headers=headers("bob"))
        assert result.status_code == 200, result.text
        assert "Recipient continuation finished." in result.text
        assert set(requests) == {("deployment_probe", "Bearer deployment")} | ({("scoped_probe", recipient_credential)} if recipient_credential else set())
    assert calls and all(call == (recipient, "user", None, None) for call in calls)
    assert model_tool_names and all("denied_tool" not in names for names in model_tool_names)
    assert "/personal" not in visited_paths


async def test_imported_nested_files_have_sandbox_write_permissions(share_app):
    ctx = share_app
    nested = ctx.output.parent / "reports" / "week"
    nested.mkdir(parents=True)
    (nested / "summary.txt").write_bytes(b"Report")
    await ctx.state.aupdate(ctx.config, {"artifacts": ["/mnt/user-data/outputs/reports/week/summary.txt"]}, as_node="branch")
    share = await make_share(ctx)
    previous_umask = os.umask(0o077)
    try:
        result = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": str(uuid4())}, headers=headers("bob"))
    finally:
        os.umask(previous_umask)
    assert result.status_code == 200, result.text
    root = ctx.paths.sandbox_outputs_dir(result.json()["thread_id"], user_id=str(BOB.id))
    output = root / "reports" / "week" / "summary.txt"
    assert output.read_bytes() == b"Report"
    assert stat.S_IMODE(output.stat().st_mode) == 0o666
    for directory in (root, root / "reports", output.parent):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o777


async def test_artifact_import_off_posix_is_refused_before_any_state(share_app, monkeypatch):
    ctx = share_app
    share = await make_share(ctx)
    snapshot = await ctx.client.get(f"/api/shares/{share['token']}")
    assert snapshot.json()["artifacts"]
    url = f"/api/shares/{share['token']}/fork"
    request_id = str(uuid4())
    monkeypatch.setattr(share_fork, "_ARTIFACT_IMPORT_SUPPORTED", False)
    refused = await ctx.client.post(url, json={"request_id": request_id}, headers=headers("bob"))
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"] == "Importing a share with artifacts requires POSIX"
    # The refusal precedes any workspace state, so the same request can succeed
    # once the descriptor-confined writer is available again.
    monkeypatch.setattr(share_fork, "_ARTIFACT_IMPORT_SUPPORTED", True)
    retried = await ctx.client.post(url, json={"request_id": request_id}, headers=headers("bob"))
    assert retried.status_code == 200, retried.text


async def test_unsafe_artifact_fails_without_publishing_partial_share(share_app):
    ctx = share_app
    ctx.output.unlink()
    ctx.output.symlink_to(ctx.paths.base_dir / "secret.txt")
    (ctx.paths.base_dir / "secret.txt").write_text("Do not share", encoding="utf-8")
    response = await ctx.client.post("/api/threads/source/shares", json={}, headers=headers())
    assert response.status_code == 422, response.text
    assert (await ctx.client.get("/api/threads/source/shares", headers=headers())).json() == []


async def test_public_allowlist_never_grants_mutation_authority():
    path = "/api/shares/" + "x" * 43
    for method in ("POST", "PATCH", "PUT", "DELETE"):
        assert not _is_public(path, method)
        assert not _is_public(path + "/artifacts/report.html", method)
    assert not _is_public(path + "/fork", "GET")
    assert _is_public(path, "GET")
    assert _is_public(path + "/artifacts/report.html", "HEAD")


async def test_failed_fork_rolls_back_metadata_checkpoint_history_and_files(share_app, monkeypatch):
    ctx = share_app
    share = await make_share(ctx)
    reached = []
    original = share_fork.write_history_seed
    request_id = str(uuid4())

    async def fail_seed(*args, **kwargs):
        await original(*args, **kwargs)
        reached.append(True)
        raise RuntimeError("private filesystem diagnostic")

    monkeypatch.setattr(share_fork, "write_history_seed", fail_seed)
    response = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": request_id}, headers=headers("bob"))
    assert reached == [True]
    assert response.status_code == 500 and "private filesystem" not in response.text
    assert await ctx.app.state.thread_store.search(user_id=str(BOB.id)) == []
    assert list(ctx.paths.base_dir.rglob("report.html")) == [ctx.output]
    monkeypatch.setattr(share_fork, "write_history_seed", original)
    retry = await ctx.client.post(f"/api/shares/{share['token']}/fork", json={"request_id": request_id}, headers=headers("bob"))
    assert retry.status_code == 200, retry.text
    assert len(await ctx.app.state.run_event_store.list_messages(retry.json()["thread_id"], limit=1000, user_id=str(BOB.id))) == 208


async def test_disconnect_drains_capture_before_releasing_source(share_app, monkeypatch):
    ctx = share_app
    entered, release = asyncio.Event(), asyncio.Event()
    original = shares.capture_share

    async def slow_capture(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(shares, "capture_share", slow_capture)
    task = asyncio.create_task(ctx.client.post("/api/threads/source/shares", json={}, headers=headers()))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
        # A competing writer must not enter while the cancelled request drains.
        with pytest.raises(ConflictError):
            async with ctx.app.state.run_manager.reserve_thread_operation("source", kind=ThreadOperationKind.artifact_write, user_id=str(ALICE.id)):
                pytest.fail("capture released its reservation before finishing")
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
    links = await ctx.client.get("/api/threads/source/shares", headers=headers())
    assert len(links.json()) == 1
