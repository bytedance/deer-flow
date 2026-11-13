"""Real HTTP/auth, SQL shares, checkpoints, history and host file copies."""

import asyncio
import os
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException, Request
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from app.gateway import extension_artifacts, share_fork, share_snapshot
from app.gateway.auth.models import User
from app.gateway.auth_middleware import AuthMiddleware, _is_public
from app.gateway.csrf_middleware import CSRFMiddleware
from app.gateway.routers import shares, threads
from app.gateway.services import build_checkpoint_state_mutation_accessor
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.persistence.run.sql import RunRepository
from deerflow.persistence.thread_meta import ThreadMetaRepository
from deerflow.runtime import ConflictError, RunManager, ThreadOperationKind
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.journal import build_branch_history_seed_events
from deerflow.runtime.user_context import reset_current_user, set_current_user

ALICE = User(id=UUID(int=1), email="alice@example.com", password_hash="unused", system_role="admin")
BOB = User(id=UUID(int=2), email="bob@example.com", password_hash="unused", system_role="admin")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(os.name != "posix", reason="descriptor-confined artifact capture requires POSIX")]


@pytest_asyncio.fixture(params=[("full", "memory"), ("delta", "memory"), ("full", "db"), ("delta", "db")])
async def share_app(tmp_path, monkeypatch, request):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'http.db'}")
    async with engine.begin() as connection:
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
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield SimpleNamespace(app=app, client=client, paths=paths, output=output, state=state, config=config, request=req)
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
