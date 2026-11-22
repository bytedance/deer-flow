"""PostgreSQL team flows through installed actions, real graphs and file handoffs."""

import asyncio
import base64
import json
import os
import socket
import subprocess
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api import ExtensionPrincipal
from deerflow_extension_api.plugins import ActionContext, ToolContext

from deerflow.config.paths import get_paths
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from extension_test_fixtures.agent_teams_gateway import PreviewRuns

pytestmark = pytest.mark.bundled_extension


@pytest.fixture
def postgres_config(tmp_path, monkeypatch):
    uri = os.environ.get("TEST_POSTGRES_URI")
    if not uri:
        pytest.skip("requires TEST_POSTGRES_URI")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    package = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"
    monkeypatch.syspath_prepend(str(package))
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    schema = "teams_flow_" + uuid.uuid4().hex
    yield {"enabled": True, "storage_url": uri, "storage_schema": schema}
    with psycopg.connect(uri, autocommit=True) as db:
        db.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


def installed(config):
    loaded, diagnostics = load_extensions([ExtensionSpec(use="deerflow_extension_agent_teams:install", config=config, required=True)])
    assert not diagnostics
    ((_, declaration),) = loaded.plugins
    actions = {action.name: action.handler for action in declaration.backend}
    tools = {tool.name: tool.handler for tool in declaration.tools}
    return actions, tools, actions["list"].__self__


def action_context(host, owner="alice"):
    return ActionContext(ExtensionPrincipal(owner), {"enabled": True}, agent_runs=host.bound(owner))


async def create_team(actions, host):
    return await actions["create"](
        {"request_id": "team", "name": "Release", "goal": "Review the release report", "members": [{"name": "Writer", "agent": "writer"}, {"name": "Reviewer", "agent": "reviewer"}]},
        action_context(host),
    )


async def finish_graphs(host):
    await asyncio.gather(*host.tasks)


@asynccontextmanager
async def preview_process(config, home):
    """Pass a bound loopback socket to the isolated fixture process."""
    script = """
import os, sys
from contextlib import asynccontextmanager
import uvicorn
from extension_test_fixtures.agent_teams_gateway import create_app
app = create_app(sys.argv[1], storage_url=os.environ["TEST_POSTGRES_URI"], storage_schema=sys.argv[2])
original = app.router.lifespan_context
@asynccontextmanager
async def lifespan(app):
    async with original(app):
        print("TEAM_PREVIEW_READY", flush=True)
        yield
app.router.lifespan_context = lifespan
uvicorn.run(app, fd=int(sys.argv[3]), log_level="warning")
"""
    backend = Path(__file__).resolve().parents[1]
    log = home / "server.log"
    isolated_config = home / "config.yaml"
    isolated_config.write_text("models: []\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\nauthorization:\n  enabled: false\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(backend), "DEER_FLOW_HOME": str(home), "DEER_FLOW_CONFIG_PATH": str(isolated_config)}
    with socket.socket() as listener, log.open("ab") as output:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        address = f"http://127.0.0.1:{listener.getsockname()[1]}"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            script,
            str(home),
            config["storage_schema"],
            str(listener.fileno()),
            env=env,
            cwd=home,
            pass_fds=(listener.fileno(),),
            stdout=asyncio.subprocess.PIPE,
            stderr=output,
        )
        try:
            ready = await asyncio.wait_for(process.stdout.readline(), 30)
            assert ready == b"TEAM_PREVIEW_READY\n", log.read_text(encoding="utf-8")
            async with httpx.AsyncClient(base_url=address, headers={"x-test-user": "alice", "X-Deerflow-Plugin-Viewer": "alice"}, timeout=10) as client:
                yield client
        finally:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 10)
                except TimeoutError:
                    process.kill()
                    await asyncio.wait_for(process.wait(), 10)


async def http_action(client, name, payload):
    response = await client.post(f"/api/plugins/community.agent-teams/actions/{name}", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.skipif(os.name == "nt", reason="the subprocess fixture passes a POSIX listener file descriptor")
@pytest.mark.asyncio
async def test_postgres_http_actions_survive_a_server_process_restart(postgres_config, tmp_path):
    content = b"%PDF-1.7\n\x00\xff process restart evidence"
    async with preview_process(postgres_config, tmp_path) as client:
        discovery = await client.get("/api/plugins")
        assert discovery.status_code == 200
        assert discovery.json()[0]["viewer_id"] == "alice"
        team = await http_action(client, "create", {"request_id": "http-team", "name": "Release", "goal": "Check release evidence", "members": [{"name": "Writer", "agent": "writer"}, {"name": "Review", "agent": "reviewer"}]})
        response = await client.post("/preview/artifact", json={"team_id": team["id"], "request_id": "report", "name": "Report", "content_base64": base64.b64encode(content).decode()})
        assert response.status_code == 200, response.text
        entry = response.json()["artifact"]
        reference = {"team_id": team["id"], "artifact_id": entry["artifact_id"], "version": entry["version"]}
        # Read the real endpoint until the asynchronous graph and artifact
        # capture publish their terminal result. The timeout only bounds hangs.
        async with asyncio.timeout(30):
            while True:
                completed = await http_action(client, "get", {"team_id": team["id"], "details": True})
                if completed["jobs"][0]["status"] == "completed":
                    break
        assert completed["artifacts"][0]["status"] == "ready"
        downloaded = await http_action(client, "get_artifact", reference)
        assert base64.b64decode(downloaded["content_base64"]) == content

    async with preview_process(postgres_config, tmp_path) as client:
        reopened = await http_action(client, "get", {"team_id": team["id"], "details": True})
        assert not reopened["connected"]
        assert reopened["jobs"] == completed["jobs"]
        assert reopened["artifacts"] == completed["artifacts"]
        downloaded = await http_action(client, "get_artifact", reference)
        assert base64.b64decode(downloaded["content_base64"]) == content
        denied = await client.post("/api/plugins/community.agent-teams/actions/get_artifact", json=reference, headers={"x-test-user": "bob", "X-Deerflow-Plugin-Viewer": "bob"})
        assert denied.status_code == 422
        assert base64.b64encode(content).decode() not in denied.text
        assert await http_action(client, "connect", {"team_id": team["id"]}) == {"connected": True}
        connected = await http_action(client, "get", {"team_id": team["id"], "details": True})
        assert connected["connected"]
        assert connected["jobs"] == completed["jobs"]


@pytest.mark.asyncio
async def test_postgres_team_result_and_exact_file_survive_restart(postgres_config):
    actions, tools, service = installed(postgres_config)
    host = PreviewRuns()
    replacement = None
    await service.start(None)
    try:
        team = await create_team(actions, host)
        writer, reviewer = team["members"]
        job = await actions["send"]({"team_id": team["id"], "member_id": writer["id"], "text": "Artifact fixture: produce a report", "request_id": "produce"}, action_context(host))
        await service.tick()
        content = b"%PDF-1.7\n\x00\xff immutable release evidence"
        source = get_paths().sandbox_outputs_dir(writer["thread_id"], user_id="alice") / "report.bin"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(content)
        member_context = ToolContext(ExtensionPrincipal("alice"), {"enabled": True}, writer["thread_id"], agent_runs=host.bound("alice"), run_id=job["id"])
        registration = await tools["register_team_artifact"]({"team_id": team["id"], "request_id": "report", "name": "Report", "path": "/mnt/user-data/outputs/report.bin"}, member_context)
        entry = registration["artifact"]
        ref = {"artifact_id": entry["artifact_id"], "version": entry["version"]}
        host.artifact_gate.set()
        await finish_graphs(host)
        await service.tick()
        completed = await actions["get"]({"team_id": team["id"], "details": True}, action_context(host))
        assert completed["jobs"][0]["status"] == "completed"
        assert "Release evidence verified" in completed["jobs"][0]["result"]
        assert completed["artifacts"][0]["status"] == "ready"
        await service.stop()
        source.unlink()

        # A fresh interpreter reads the persisted result and bytes through the
        # production store, independently of this process's extension objects.
        script = """
import base64, json, os
from deerflow_extension_agent_teams.postgres_store import PostgresStore
args = json.loads(os.environ["TEAM_FLOW_READ"])
store = PostgresStore(os.environ["TEST_POSTGRES_URI"], args["schema"])
try:
    store.acquire_service_lock()
    team = store.get("alice", args["team_id"])
    entry, content = store.artifact("alice", args["team_id"], args["artifact_id"], args["version"])
    print(json.dumps({"status": team["jobs"][0]["status"], "result": team["jobs"][0]["result"], "content": base64.b64encode(content).decode()}))
finally:
    store.close()
"""
        package = Path(__file__).resolve().parents[2] / "examples/deerflow-extension-agent-teams"
        env = {**os.environ, "PYTHONPATH": str(package), "TEAM_FLOW_READ": json.dumps({"schema": postgres_config["storage_schema"], "team_id": team["id"], **ref})}
        process = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", script], env=env, text=True, capture_output=True, check=True, timeout=30)
        persisted = json.loads(process.stdout)
        assert persisted["status"] == "completed"
        assert persisted["result"] == completed["jobs"][0]["result"]
        assert base64.b64decode(persisted["content"]) == content

        actions, tools, replacement = installed(postgres_config)
        await replacement.start(None)
        reopened = await actions["get"]({"team_id": team["id"], "details": True}, action_context(host))
        assert not reopened["connected"]
        assert reopened["jobs"] == completed["jobs"]
        assert (await actions["list"]({}, action_context(host, "bob")))["teams"] == []
        with pytest.raises(ValueError):
            await actions["get_artifact"]({"team_id": team["id"], **ref}, action_context(host, "bob"))
        await actions["connect"]({"team_id": team["id"]}, action_context(host))
        downloaded = await actions["get_artifact"]({"team_id": team["id"], **ref}, action_context(host))
        assert base64.b64decode(downloaded["content_base64"]) == content
        await actions["send"]({"team_id": team["id"], "member_id": reviewer["id"], "text": "Review the retained report", "request_id": "review", "artifacts": [ref]}, action_context(host))
        await replacement.tick()
        await finish_graphs(host)
        await replacement.tick()
        uploads = get_paths().sandbox_uploads_dir(reviewer["thread_id"], user_id="alice")
        assert [path.read_bytes() for path in uploads.iterdir() if path.is_file()] == [content]
        final = await actions["get"]({"team_id": team["id"], "details": True}, action_context(host))
        assert [job["status"] for job in final["jobs"]] == ["completed", "completed"]
    finally:
        host.artifact_gate.set()
        await service.stop()
        if replacement is not None:
            await replacement.stop()
        await finish_graphs(host)


@pytest.mark.asyncio
async def test_postgres_lock_loss_drains_worker_and_reconciles_frozen_admission(postgres_config, monkeypatch):
    import psycopg
    from deerflow_extension_agent_teams.store import StoreUnavailable

    actions, _, service = installed(postgres_config)
    host = PreviewRuns()
    entered, drained, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    real_bound = host.bound

    def gated_bound(owner):
        bound = real_bound(owner)
        start = bound.start

        async def admit(**kwargs):
            result = await start(**kwargs)
            entered.set()
            try:
                await release.wait()
            finally:
                drained.set()
            return result

        bound.start = admit
        return bound

    monkeypatch.setattr(host, "bound", gated_bound)
    replacement = None
    await service.start(None)
    try:
        team = await create_team(actions, host)
        member = team["members"][0]
        job = await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Check release readiness", "request_id": "uncertain"}, action_context(host))
        await service.tick(wait=False)
        await asyncio.wait_for(entered.wait(), 10)
        frozen = (await service.db("get", "alice", team["id"]))["jobs"][0]
        assert frozen["input"] is not None and frozen["run_id"] is None
        assert set(host.runs) == {job["id"]}
        actions2, _, replacement = installed(postgres_config)
        with pytest.raises(StoreUnavailable):
            await replacement.start(None)
        assert not replacement.available

        pid = service.store._connection.info.backend_pid

        def terminate_owner():
            with psycopg.connect(postgres_config["storage_url"], autocommit=True) as db:
                assert db.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone()[0]

        await asyncio.to_thread(terminate_owner)
        with pytest.raises(StoreUnavailable):
            await service.ensure_available()
        await asyncio.wait_for(drained.wait(), 10)
        assert not service.available
        with pytest.raises(StoreUnavailable):
            await service.db("change", "alice", team["id"], lambda team: team.update(name="stale writer"))
        with pytest.raises((StoreUnavailable, ValueError)):
            await actions["send"]({"team_id": team["id"], "member_id": member["id"], "text": "Stale work", "request_id": "stale"}, action_context(host))
        release.set()
        await service.stop()

        monkeypatch.setattr(host, "bound", real_bound)
        await replacement.start(None)
        saved = (await replacement.db("get", "alice", team["id"]))["jobs"][0]
        assert saved["input"] == frozen["input"]
        assert saved["status"] not in {"completed", "failed", "cancelled"}
        assert not replacement.handles
        await actions2["connect"]({"team_id": team["id"]}, action_context(host))
        await replacement.tick()
        await finish_graphs(host)
        await replacement.tick()
        assert set(host.runs) == {job["id"]}
        final = await actions2["get"]({"team_id": team["id"], "details": True}, action_context(host))
        assert final["jobs"][0]["id"] == job["id"]
        assert final["jobs"][0]["status"] == "completed"
    finally:
        release.set()
        host.artifact_gate.set()
        await service.stop()
        if replacement is not None:
            await replacement.stop()
        await finish_graphs(host)
