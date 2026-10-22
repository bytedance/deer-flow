"""Private LangSmith lineage survives callback and process boundaries offline."""

import asyncio
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import requests
from langchain_core.callbacks import CallbackManager
from langchain_core.runnables import RunnableLambda
from langchain_core.runnables.config import var_child_runnable_config
from langsmith import tracing_context
from langsmith.utils import tracing_is_enabled

from deerflow.config.tracing_config import reset_tracing_config
from deerflow.tracing import scoped
from deerflow.tracing.profiles import ProviderConfig, RunTracingSnapshot


class MemoryClient:
    def __init__(self, settings):
        self.settings = settings
        self.posts = []
        self.closed = False

    def create_run(self, **run):
        self.posts.append({name: run.get(name) for name in ("id", "name", "parent_run_id", "trace_id", "dotted_order", "session_name", "api_url", "api_key")})

    def update_run(self, run_id, **run):
        pass

    def flush(self, **kwargs):
        pass

    def close(self, **kwargs):
        self.closed = True


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("A parent-context regression attempted network access")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)
    monkeypatch.setenv("MONOCLE_TRACING", "false")
    reset_tracing_config()
    try:
        yield
        assert attempts == []
    finally:
        reset_tracing_config()


@pytest.fixture
def clients(monkeypatch):
    created = []

    def create(**settings):
        client = MemoryClient(settings)
        created.append(client)
        return client

    monkeypatch.setattr("langsmith.Client", create)
    return created


def snapshot(*, snapshot_id=None, **provider_changes):
    provider = ProviderConfig(provider="langsmith", endpoint="https://private.example", project="private-project", workspace_id="private-workspace", api_key="offline-key")
    return RunTracingSnapshot(snapshot_id=snapshot_id or uuid4().hex, owner_user_id="alice", agent_name="worker", mode="configured", revision="1", providers=(provider.model_copy(update=provider_changes),))


def _finished_parent(frozen, clients):
    captured = {}

    def parent_body(value):
        captured.update(scoped.capture_tracing_parent_context())
        return value

    with scoped.tracing_scope(frozen) as session:
        RunnableLambda(parent_body).invoke("parent-input-not-for-transport", config={"callbacks": session.callbacks(), "run_name": "parent", "run_id": UUID(int=1)})
    return captured, clients[-1].posts[0]


def _descriptor(frozen, parent):
    return {
        "snapshot_id": frozen.snapshot_id,
        "destination_key": scoped._key(frozen.providers[0]),
        "parent_run_id": str(parent["id"]),
        "trace_id": str(parent["trace_id"]),
        "dotted_order": parent["dotted_order"],
    }


@pytest.mark.asyncio
async def test_fresh_async_callback_exports_a_child_on_the_parent_trace(clients):
    frozen = snapshot()
    captured = {}

    async def parent_body(value):
        captured.update(scoped.capture_tracing_parent_context())
        async with scoped.async_tracing_scope(frozen, parent_contexts=captured) as child_session:
            assert tracing_is_enabled() is False
            return await RunnableLambda(str.upper).ainvoke(value, config={"callbacks": child_session.callbacks(), "run_name": "child", "run_id": UUID(int=2)})

    async with scoped.async_tracing_scope(frozen) as session:
        assert await RunnableLambda(parent_body).ainvoke("payload", config={"callbacks": session.callbacks(), "run_name": "parent", "run_id": UUID(int=1)}) == "PAYLOAD"
    parent, child = clients[0].posts
    assert child["parent_run_id"] == parent["id"]
    assert child["trace_id"] == parent["trace_id"]
    assert child["dotted_order"].startswith(parent["dotted_order"] + ".")
    assert captured["langsmith"]["parent_run_id"] == str(parent["id"])
    assert "offline-key" not in json.dumps(captured)
    assert "payload" not in json.dumps(captured)
    assert len(clients) == 1


def test_serialized_parent_survives_parent_completion_and_a_new_process(clients, tmp_path):
    frozen = snapshot()
    captured, parent = _finished_parent(frozen, clients)
    assert clients[0].closed
    script = """
import json, socket, sys
attempts = []
def blocked(*args, **kwargs):
    attempts.append(True)
    raise AssertionError("Network access is forbidden")
socket.socket.connect = blocked
socket.socket.connect_ex = blocked
socket.create_connection = blocked
import httpx, requests
requests.sessions.Session.request = blocked
httpx.Client.send = blocked
httpx.AsyncClient.send = blocked
from test_langsmith_parent_context import MemoryClient, snapshot
import langsmith
client = MemoryClient({})
langsmith.Client = lambda **kwargs: client
from deerflow.tracing.scoped import tracing_scope
from uuid import UUID
payload = json.load(sys.stdin)
frozen = snapshot(snapshot_id=payload["snapshot_id"])
with tracing_scope(frozen, parent_contexts=payload["contexts"]) as session:
    callback = session.callbacks()[0]
    callback.on_chain_start({}, {"input": "delayed child"}, run_id=UUID(int=3), name="delayed-child")
    callback.on_chain_end({}, run_id=UUID(int=3))
print(json.dumps({"posts": client.posts, "network_attempts": len(attempts)}, default=str))
"""
    backend = Path(__file__).parents[1]
    env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in (backend / "tests", backend / "packages/harness", backend / "packages/extension-api"))
    result = subprocess.run([sys.executable, "-B", "-c", script], input=json.dumps({"snapshot_id": frozen.snapshot_id, "contexts": captured}), cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    restored = json.loads(result.stdout)
    assert restored["network_attempts"] == 0
    child = restored["posts"][0]
    assert child["parent_run_id"] == str(parent["id"])
    assert child["trace_id"] == str(parent["trace_id"])
    assert child["dotted_order"].startswith(parent["dotted_order"] + ".")


@pytest.mark.asyncio
async def test_concurrent_snapshots_using_one_destination_keep_separate_trees(clients):
    barrier = asyncio.Barrier(2)

    async def invoke(index):
        frozen = snapshot()

        async def parent_body(value):
            context = scoped.capture_tracing_parent_context()
            await barrier.wait()
            async with scoped.async_tracing_scope(frozen, parent_contexts=context) as child_session:
                return await RunnableLambda(str.upper).ainvoke(value, config={"callbacks": child_session.callbacks(), "run_name": f"child-{index}", "run_id": UUID(int=index * 10 + 1)})

        async with scoped.async_tracing_scope(frozen) as session:
            await RunnableLambda(parent_body).ainvoke("payload", config={"callbacks": session.callbacks(), "run_name": f"parent-{index}", "run_id": UUID(int=index * 10)})

    await asyncio.gather(invoke(1), invoke(2))
    assert len(clients) == 1
    runs = {run["name"]: run for run in clients[0].posts}
    for index in (1, 2):
        assert runs[f"child-{index}"]["parent_run_id"] == runs[f"parent-{index}"]["id"]
        assert runs[f"child-{index}"]["trace_id"] == runs[f"parent-{index}"]["trace_id"]
    assert runs["parent-1"]["trace_id"] != runs["parent-2"]["trace_id"]


def test_restored_callback_clones_keep_internal_nodes_and_recaptured_lineage(clients):
    frozen = snapshot()
    captured, parent = _finished_parent(frozen, clients)
    with scoped.tracing_scope(frozen, parent_contexts=captured) as session:
        handler = session.callbacks()[0]
        clone = handler.copy_with_metadata_defaults(metadata={"ls_agent_type": "child"})
        root_id, node_id, leaf_id = UUID(int=5), UUID(int=6), UUID(int=7)
        handler.on_chain_start({}, {}, run_id=root_id, name="child-root")
        clone.on_chain_start({}, {}, run_id=node_id, parent_run_id=root_id, name="internal-node")
        clone.on_chain_start({}, {}, run_id=leaf_id, parent_run_id=node_id, name="internal-leaf")
        token = var_child_runnable_config.set({"callbacks": CallbackManager(handlers=[clone], parent_run_id=node_id)})
        try:
            recaptured = scoped.capture_tracing_parent_context()
        finally:
            var_child_runnable_config.reset(token)
        clone.on_chain_end({}, run_id=leaf_id)
        clone.on_chain_end({}, run_id=node_id)
        handler.on_chain_end({}, run_id=root_id)
    runs = {run["name"]: run for run in clients[-1].posts}
    assert runs["child-root"]["parent_run_id"] == parent["id"]
    assert runs["internal-node"]["parent_run_id"] == root_id
    assert runs["internal-leaf"]["parent_run_id"] == node_id
    assert all(run["trace_id"] == parent["trace_id"] for run in runs.values())
    assert recaptured["langsmith"]["parent_run_id"] == str(node_id)
    with scoped.tracing_scope(frozen, parent_contexts=recaptured) as session:
        handler = session.callbacks()[0]
        handler.on_chain_start({}, {}, run_id=UUID(int=8), name="later-grandchild")
        handler.on_chain_end({}, run_id=UUID(int=8))
    later = clients[-1].posts[0]
    assert later["parent_run_id"] == node_id
    assert later["trace_id"] == parent["trace_id"]
    assert later["dotted_order"].startswith(runs["internal-node"]["dotted_order"] + ".")


@pytest.mark.parametrize("change", [{"endpoint": "https://other.example"}, {"project": "other-project"}, {"workspace_id": "other-workspace"}, {"api_key": "other-key"}, {"snapshot_id": "other-snapshot"}])
def test_parent_context_cannot_bind_another_destination_or_snapshot(clients, change):
    frozen = snapshot()
    _, parent = _finished_parent(frozen, clients)
    context = _descriptor(frozen, parent)
    if "snapshot_id" in change:
        other = frozen.model_copy(update=change)
    else:
        provider = ProviderConfig.model_validate({**frozen.providers[0].model_dump(), **change})
        other = frozen.model_copy(update={"providers": (provider,)})
    with scoped.tracing_scope(other, parent_contexts={"langsmith": context}) as session:
        with pytest.raises(ValueError, match="parent tracing context"):
            session.callbacks()


@pytest.mark.parametrize("change", [{"parent_run_id": "invalid"}, {"trace_id": str(UUID(int=99))}, {"parent_run_id": str(UUID(int=99))}, {"dotted_order": "invalid"}, {"destination_key": None}])
def test_invalid_parent_descriptors_fail_without_echoing_their_contents(clients, change):
    frozen = snapshot()
    _, parent = _finished_parent(frozen, clients)
    context = {**_descriptor(frozen, parent), **change}
    with scoped.tracing_scope(frozen, parent_contexts={"langsmith": context}) as session:
        with pytest.raises(ValueError, match="parent tracing context") as failure:
            session.callbacks()
    assert "invalid" not in str(failure.value)
    assert "offline-key" not in str(failure.value)


def test_capture_ignores_handlers_from_another_snapshot_even_at_the_same_destination(clients):
    first, second = snapshot(), snapshot()
    with scoped.tracing_scope(first) as session:
        handler = session.callbacks()[0]
        handler.on_chain_start({}, {}, run_id=UUID(int=1), name="first")
        foreign_manager = CallbackManager(handlers=[handler], parent_run_id=UUID(int=1))
        with scoped.tracing_scope(second):
            token = var_child_runnable_config.set({"callbacks": foreign_manager})
            try:
                assert scoped.capture_tracing_parent_context() == {}
            finally:
                var_child_runnable_config.reset(token)
        handler.on_chain_end({}, run_id=UUID(int=1))


def test_restored_private_parent_does_not_enable_ambient_clients_or_replica_routing(clients, monkeypatch):
    frozen = snapshot()
    _, parent = _finished_parent(frozen, clients)
    context = {"langsmith": _descriptor(frozen, parent)}
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_RUNS_ENDPOINTS", '{"https://ambient.example":"fake-ambient-key"}')
    with tracing_context(enabled=True, client=MemoryClient({}), parent=False):
        with scoped.tracing_scope(frozen, parent_contexts=context) as session:
            assert tracing_is_enabled() is False
            callback = session.callbacks()[0]
            callback.on_chain_start({}, {}, run_id=UUID(int=4), name="restored-private")
            callback.on_chain_end({}, run_id=UUID(int=4))
            assert tracing_is_enabled() is False
    child = clients[-1].posts[0]
    assert child["parent_run_id"] == parent["id"]
    assert child["trace_id"] == parent["trace_id"]
    assert child["api_url"] is None and child["api_key"] is None
    assert clients[-1].settings["api_url"] == "https://private.example"
    assert clients[-1].settings["workspace_id"] == "private-workspace"
