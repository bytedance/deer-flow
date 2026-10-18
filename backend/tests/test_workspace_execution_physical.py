"""Opt-in Shanghai Docker main. No local Docker or fake permission-success path."""

import asyncio
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_workspace_execution_wire import _exercise_native_tool_to_b
from test_workspace_executor_migration import executor_engine, native_engine  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("ECS_EXECUTOR_SCOPE_PHYSICAL_TEST") != "1", reason="dedicated Shanghai physical CI opt-in required before fixture setup"),
]


def test_scoped_native_mcp_real_docker_main(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    if os.environ.get("ECS_EXECUTOR_SCOPE_PHYSICAL_TEST") != "1":
        pytest.skip("requires the dedicated Shanghai physical job and owned shared paths")
    image = os.environ["TEST_SCOPE_EXECUTION_IMAGE"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    manifest = Path(os.environ["TEST_SCOPE_OWNED_MANIFEST"])
    assert manifest.is_file(), "CI must pre-create its private owned manifest"

    async def physical(case):
        import sqlalchemy as sa
        from ecs_executor.worker import Docker, LocalWorker

        from deerflow.authz.workspace import get_current_workspace
        from deerflow.persistence.mcp_tasks.model import McpTaskRow

        job = case.store.get(case.remote_id)
        owned = json.loads(manifest.read_text())
        owned.append({"id": job["id"], "spec_digest": job["spec_digest"]})
        manifest.write_text(json.dumps(owned))
        docker = Docker()
        ref = "deerflow-exec-" + job["id"]
        try:
            assert callable(getattr(case.jobs, "claim_queued", None)), "scoped worker claim integration is missing"
            worker = LocalWorker(case.jobs, docker=docker)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                await worker.tick()
                latest = case.store.get(case.remote_id)
                if latest["state"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.1)
            assert latest["state"] == "completed", latest
            assert latest["workspace_context"] == job["workspace_context"]
            outputs = case.jobs.publication.paths.sandbox_outputs_dir(case.run.thread_id, user_id="owner") / job["id"]
            assert (outputs / "files/report.md").read_bytes() == b"original input"
            payload = json.loads((outputs / "result.json").read_bytes())
            assert payload["stdout"] == "scoped-B-report" and payload["exit_code"] == 0
            await worker.tick()
            assert await docker.inspect(ref) is None
            latest = case.store.get(case.remote_id)
            assert latest["physical_stopped"] is True and not latest["cleanup_pending"]
            await case.tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            async with case.case.sf() as session:
                row = await session.get(McpTaskRow, case.local_id)
                assert row.status == "completed" and row.run_id == case.run.run_id
                assert row.result_artifact["uri"].endswith("/" + job["id"] + "/result.json")
                assert row.workspace_id == case.original.workspace_id
                assert row.result["exit_code"] == 0
            assert get_current_workspace() == case.other
            assert case.jobs.read_artifact("owner", job["id"])["stdout"] == "scoped-B-report"
            with case.store.engine.connect() as connection:
                assert connection.execute(sa.text("SELECT state,version FROM ecs_execution_jobs WHERE id='unknown'")).one() == ("uncertain", 7)
        finally:
            observation = await docker.inspect(ref)
            if observation is not None:
                labels = observation["Config"].get("Labels") or {}
                assert labels.get("deerflow.execution.job") == job["id"] and labels.get("deerflow.execution.spec") == job["spec_digest"]
                await docker.checked("rm", "-f", ref)
                assert await docker.inspect(ref) is None

    _exercise_native_tool_to_b(native_engine, executor_engine, tmp_path, monkeypatch, after_queue=physical, execution_image=image, execution_argv=["/bin/sh", "-c", "cat /inputs/program.txt > /output/report.md; printf scoped-B-report"])


@pytest.mark.parametrize("withdraw_at", ["created", "running"])
def test_scoped_worker_withdrawal_requires_observed_stop(native_engine, executor_engine, tmp_path, monkeypatch, withdraw_at):  # noqa: F811
    if os.environ.get("ECS_EXECUTOR_SCOPE_PHYSICAL_TEST") != "1":
        pytest.skip("requires the dedicated Shanghai physical job")
    image = os.environ["TEST_SCOPE_EXECUTION_IMAGE"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    manifest = Path(os.environ["TEST_SCOPE_OWNED_MANIFEST"])

    async def physical(case):
        import sqlalchemy as sa
        from ecs_executor.worker import Docker, LocalWorker

        from deerflow.persistence.mcp_tasks.model import McpTaskRow
        from deerflow.persistence.workspaces.model import WorkspaceMembershipRow

        job = case.store.get(case.remote_id)
        rows = json.loads(manifest.read_text())
        rows.append({"id": job["id"], "spec_digest": job["spec_digest"]})
        manifest.write_text(json.dumps(rows))
        predicate = sa.and_(WorkspaceMembershipRow.workspace_id == case.original.workspace_id, WorkspaceMembershipRow.user_id == "owner")

        def withdraw():
            with native_engine.begin() as connection:
                connection.execute(sa.update(WorkspaceMembershipRow).where(predicate).values(status="removed"))

        class ObservedDocker(Docker):
            starts = 0
            inspection_unavailable = False

            async def checked(self, *arguments):
                if arguments[0] == "start":
                    self.starts += 1
                result = await super().checked(*arguments)
                if arguments[0] == "create" and withdraw_at == "created":
                    # The real container exists. Native locks must not be held
                    # over create, and the later start fence must see withdrawal.
                    withdraw()
                return result

            async def inspect(self, reference):
                if self.inspection_unavailable:
                    self.inspection_unavailable = False
                    raise RuntimeError("fixture physical observation unavailable")
                return await super().inspect(reference)

        docker = ObservedDocker()
        worker = LocalWorker(case.jobs, docker=docker)
        ref = "deerflow-exec-" + job["id"]
        published = case.jobs.publication.paths.sandbox_outputs_dir(case.run.thread_id, user_id="owner") / job["id"]
        try:
            await worker.tick()
            if withdraw_at == "created":
                assert docker.starts == 0
            else:
                assert docker.starts == 1
                assert (await docker.inspect(ref))["State"]["Running"] is True
                assert case.store.get(job["id"])["state"] == "running"
                # Test task cancellation at the actual publication boundary,
                # independently of the outer worker's authorization check.
                with native_engine.begin() as connection:
                    connection.execute(sa.update(McpTaskRow).where(McpTaskRow.id == case.local_id).values(cancel_requested_at=datetime.now(UTC)))
                try:
                    payload = b'{"files":[],"stdout":"withheld","truncated":false,"exit_code":0}'
                    with pytest.raises(PermissionError):
                        case.jobs.publication.publish(case.store.get(job["id"]), payload, {"report.md": b"withheld"})
                    assert not published.exists()
                finally:
                    with native_engine.begin() as connection:
                        connection.execute(sa.update(McpTaskRow).where(McpTaskRow.id == case.local_id).values(cancel_requested_at=None))
                withdraw()
                docker.inspection_unavailable = True
                await worker.tick()
                pending = case.store.get(job["id"])
                assert pending["state"] == "running" and not pending.get("physical_stopped")
                assert (await docker.inspect(ref))["State"]["Running"] is True
                assert not published.exists()
                await worker.tick()
            stopped = case.store.get(job["id"])
            assert stopped["state"] == "cancelled" and stopped["physical_stopped"] is True
            assert stopped["cancel_requested"] is True and "artifact" not in stopped
            assert await docker.inspect(ref) is None
            assert not published.exists()
            await case.tasks.run_once(now=datetime.now(UTC) + timedelta(seconds=120))
            async with case.case.sf() as session:
                task = await session.get(McpTaskRow, case.local_id)
                assert task.result is None and task.result_artifact is None
                assert task.status == "working", "control settlement needs its own native receipt"
        finally:
            observation = await Docker().inspect(ref)
            if observation is not None:
                labels = observation["Config"].get("Labels") or {}
                assert labels.get("deerflow.execution.job") == job["id"] and labels.get("deerflow.execution.spec") == job["spec_digest"]
                await Docker().checked("rm", "-f", ref)
                assert await Docker().inspect(ref) is None

    _exercise_native_tool_to_b(
        native_engine, executor_engine, tmp_path, monkeypatch, after_queue=physical, execution_image=image, execution_argv=["/bin/sh", "-c", "printf private-output > /output/report.md; sleep 60; printf must-not-publish"]
    )


@pytest.mark.parametrize("executor_engine", ["postgres"], indirect=True)
def test_scoped_scheduled_c_real_b_docker_resumes_original_occurrence(native_engine, executor_engine, tmp_path, monkeypatch):  # noqa: F811
    """Single-host B Docker + ASGI MCP, not shared-pool or two-host TCP."""
    import hashlib
    from types import SimpleNamespace
    from uuid import uuid4

    import httpx
    import sqlalchemy as sa
    from ecs_executor.job_store import JobStore
    from ecs_executor.jobs import ExecutionJobs, ExecutionProfile
    from ecs_executor.mcp_server import create_server
    from ecs_executor.schema import upgrade_schema
    from ecs_executor.worker import Docker, LocalWorker
    from langchain_core.tools import tool
    from test_workspace_native_dependencies import _exercise_native_dependency

    from deerflow.authz.workspace import get_current_workspace, reset_current_workspace, set_current_workspace
    from deerflow.config.extensions_config import ExtensionsConfig
    from deerflow.mcp import client as mcp_client
    from deerflow.mcp.task_tool_caller import McpTaskToolCaller
    from deerflow.mcp.tasks.ordinary import OrdinaryMcpTaskDriver
    from deerflow.mcp.tools import _make_background_submit_tool

    image = os.environ["TEST_SCOPE_EXECUTION_IMAGE"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", image)
    manifest, evidence_path = Path(os.environ["TEST_SCOPE_OWNED_MANIFEST"]), Path(os.environ["TEST_SCOPE_EVIDENCE"])
    owned_root = Path(os.environ["TEST_SCOPE_PHYSICAL_ROOT"]).resolve()
    assert tmp_path.resolve().is_relative_to(owned_root) and manifest.is_file() and json.loads(manifest.read_text()) == []
    # A dedicated B ledger is the supported LocalWorker single-host mode. It
    # cannot accidentally reconcile active native C jobs from the pool ledger.
    database = "tenant_b_physical_" + uuid4().hex
    admin = sa.create_engine(executor_engine.url, isolation_level="AUTOCOMMIT")
    b_store = jobs = None
    evidence = {"scope": "single-host-B-Docker-ASGI-MCP", "image": image, "b_database": database, "finally_removed": False}

    def save_evidence():
        evidence_path.write_text(json.dumps(evidence, indent=2))

    def setup(case, owner, workspace_root, io_scopes):
        nonlocal jobs
        secret = b"synthetic-real-scheduled-B-key-at-least-32-bytes"
        jobs = ExecutionJobs(
            b_store,
            secret=secret,
            audience="B",
            profiles={"small": ExecutionProfile(image=image)},
            user_profiles={owner: {"small"}},
            artifact_root=tmp_path / "B-artifacts",
            workspace_root=workspace_root,
            metadata_database_url=native_engine.url.render_as_string(hide_password=False),
            workspace_required=True,
            native_server_name="ecs",
        )
        assert jobs.publication.paths.base_dir == workspace_root.resolve()
        for key, value in {"SERVER": "ecs", "SUBMIT_TOOL": "submit", "STATUS_TOOL": "status", "CANCEL_TOOL": "cancel", "AUDIENCE": "B", "SECRET": secret.decode()}.items():
            monkeypatch.setenv("ECS_EXECUTOR_SCOPE_" + key, value)
        config = ExtensionsConfig.model_validate(
            {
                "mcpInterceptors": ["ecs_executor.interceptor:build_execution_scope_interceptor"],
                "mcpServers": {
                    "ecs": {
                        "type": "http",
                        "url": "http://127.0.0.1:8003/mcp",
                        "headers": {"Authorization": "Bearer discovery-only"},
                        "user_auth": {"enabled": True, "on_missing": "deny", "users": {owner: "Bearer original-owner-credential"}},
                        "task_toolsets": [{"name": "execution", "submit_tool": "submit", "status_tool": "status", "cancel_tool": "cancel"}],
                    }
                },
            }
        )
        monkeypatch.setattr("ecs_executor.interceptor.get_extensions_config", lambda: config)
        server = create_server(jobs, user_credentials={owner: "original-owner-credential"}, discovery_credential="discovery-only")
        app = server.streamable_http_app()
        original_params = mcp_client.build_server_params

        def params(name, server_config):
            result = original_params(name, server_config)
            result["httpx_client_factory"] = lambda headers=None, timeout=None, auth=None: httpx.AsyncClient(transport=httpx.ASGITransport(app=app), headers=headers, timeout=timeout or 30, auth=auth)
            return result

        monkeypatch.setattr(mcp_client, "build_server_params", params)
        monkeypatch.setattr("deerflow.mcp.task_tool_caller.build_server_params", params)

        class ObservedOrdinaryDriver(OrdinaryMcpTaskDriver):
            async def submit(self, request):
                io_scopes.append(("submit", request.workspace_context, get_current_workspace()))
                return await super().submit(request)

            async def get_status(self, reference):
                io_scopes.append(("status", reference.workspace_context, get_current_workspace()))
                return await super().get_status(reference)

        @tool
        async def submit(request_key: str, profile: str, argv: list[str], input_refs: dict[str, dict[str, str]]) -> str:
            """Build the original research report through a durable B execution."""
            raise AssertionError("The actual ToolNode must use its native background wrapper")

        wrapped = _make_background_submit_tool(submit, server_name="ecs", task_name="execution", submit_tool="submit", status_tool="status", cancel_tool="cancel", connection_scope="deployment")
        session = server.session_manager.run()
        opened = False

        def source_directory(source, *, outputs=False, context=None):
            selected = set_current_workspace(context or source.workspace_context)
            try:
                resolve = jobs.publication.paths.sandbox_outputs_dir if outputs else jobs.publication.paths.sandbox_uploads_dir
                return resolve(source.thread_id, user_id=owner)
            finally:
                reset_current_workspace(selected)

        def arguments(source):
            upload = source_directory(source) / "program.txt"
            upload.parent.mkdir(parents=True, exist_ok=True)
            upload.write_bytes(b"owned dependency report")
            return {
                "request_key": "scheduled-report",
                "profile": "small",
                "argv": ["/bin/sh", "-c", "set -eu; cat /inputs/program.txt > /output/report.md; cat /output/report.md"],
                "input_refs": {"program.txt": {"path": "uploads/program.txt", "sha256": hashlib.sha256(upload.read_bytes()).hexdigest()}},
            }

        def output_path(source, remote_id):
            return source_directory(source, outputs=True) / remote_id / "files/report.md"

        class ObservedDocker(Docker):
            async def checked(self, *args):
                result = await super().checked(*args)
                if args[0] == "create":
                    identity = result.decode().strip()
                    # Persist exact ID before any assertion can fail. Finally
                    # cleanup is separate evidence from normal worker STOP.
                    rows = json.loads(manifest.read_text())
                    rows[-1]["container_id"] = identity
                    manifest.write_text(json.dumps(rows))
                    evidence["container_id"] = identity
                    save_evidence()
                    assert re.fullmatch(r"[0-9a-f]{64}", identity)
                    observation = await self.inspect(identity)
                    assert observation["Id"] == identity
                    labels = observation["Config"].get("Labels") or {}
                    assert labels.get("deerflow.execution.job") == rows[-1]["id"] and labels.get("deerflow.execution.spec") == rows[-1]["spec_digest"]
                    assert observation["HostConfig"]["NetworkMode"] == "none" and observation["HostConfig"]["ReadonlyRootfs"] is True
                    assert observation["Config"]["User"] == "65534:65534" and "ALL" in observation["HostConfig"]["CapDrop"]
                    assert observation["HostConfig"]["NanoCpus"] == 500000000 and observation["HostConfig"]["Memory"] == 128 * 1024 * 1024
                    assert observation["HostConfig"]["PidsLimit"] == 64
                    assert observation["Image"] == image
                    binds = {row["Destination"]: row for row in observation["Mounts"] if row["Type"] == "bind"}
                    assert set(binds) == {"/inputs", "/output"} and binds["/inputs"]["RW"] is False and binds["/output"]["RW"] is True
                    assert all(Path(row["Source"]).resolve().is_relative_to(owned_root) for row in binds.values())
                    assert observation["HostConfig"]["Tmpfs"] == {"/tmp": "rw,noexec,nosuid,size=16m"}
                    assert all(row["Type"] == "bind" or (row["Type"] == "tmpfs" and row["Destination"] == "/tmp") for row in observation["Mounts"])
                    evidence["created_with_restricted_profile"] = True
                    save_evidence()
                return result

        docker = ObservedDocker()
        current_job = None

        async def open_server():
            nonlocal opened
            await session.__aenter__()
            opened = True

        async def execute(local_task, source):
            nonlocal current_job
            current_job = b_store.get(local_task["remote_task_id"])
            assert current_job["state"] == "queued" and current_job["kind"] == "B" and current_job["workspace_context"] == asdict(case.original)
            assert current_job["run_id"] == source.run_id and current_job["incarnation"] == source.thread_incarnation
            manifest.write_text(json.dumps([{"id": current_job["id"], "spec_digest": current_job["spec_digest"]}]))
            evidence.update(b_job_id=current_job["id"], b_spec_digest=current_job["spec_digest"], committed_and_queued=True)
            save_evidence()
            source_directory(source).joinpath("program.txt").write_bytes(b"later upload must not replace the admitted snapshot")
            worker, deadline = LocalWorker(jobs, docker=docker), time.monotonic() + 120
            assert get_current_workspace() == case.other
            while time.monotonic() < deadline:
                await worker.tick()  # Keep ambient UI-other: publication must select the original scope itself.
                assert get_current_workspace() == case.other
                latest = b_store.get(current_job["id"])
                if latest["state"] in {"completed", "failed", "cancelled"}:
                    break
                await asyncio.sleep(0.1)
            assert latest["state"] == "completed", {"state": latest["state"], "error": latest.get("error")}
            other_output = source_directory(source, outputs=True, context=case.other) / current_job["id"]
            assert not other_output.exists(), "B publication escaped to the UI-selected workspace"
            assert output_path(source, current_job["id"]).read_bytes() == b"owned dependency report"
            assert get_current_workspace() == case.other
            evidence["other_workspace_output_absent"] = True
            result = jobs.read_artifact(owner, current_job["id"])
            assert result["stdout"] == "owned dependency report" and result["exit_code"] == 0
            await worker.tick()
            assert get_current_workspace() == case.other
            identity = evidence["container_id"]
            assert await docker.inspect(identity) is None
            final = b_store.get(current_job["id"])
            assert final["physical_stopped"] is True and final["cleanup_pending"] is False
            evidence.update(normal_stop_exact_id_absent=True, native_publication=True, output_sha256=hashlib.sha256(output_path(source, current_job["id"]).read_bytes()).hexdigest())
            save_evidence()

        async def close_server():
            try:
                if current_job is not None:
                    identity = evidence.get("container_id", "deerflow-exec-" + current_job["id"])
                    observation = await docker.inspect(identity)
                    if observation is not None:
                        labels = observation["Config"].get("Labels") or {}
                        assert labels.get("deerflow.execution.job") == current_job["id"] and labels.get("deerflow.execution.spec") == current_job["spec_digest"]
                        if evidence.get("container_id"):
                            assert observation["Id"] == evidence["container_id"]
                        await docker.checked("rm", "-f", observation["Id"])
                        assert await docker.inspect(observation["Id"]) is None
                        evidence["finally_removed"] = True
            finally:
                save_evidence()
                if opened:
                    await session.__aexit__(None, None, None)

        return SimpleNamespace(
            driver=ObservedOrdinaryDriver(McpTaskToolCaller(config)), tool=wrapped, arguments=arguments, output_path=output_path, execute=execute, open=open_server, close=close_server, evidence=evidence, save_evidence=save_evidence
        )

    from dataclasses import asdict

    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f'CREATE DATABASE "{database}"'))
        b_store = JobStore(executor_engine.url.set(database=database).render_as_string(hide_password=False))
        upgrade_schema(b_store.engine)
        upgrade_schema(executor_engine)  # Freeze legacy seed after the real schema upgrade, including new nullable columns.
        with executor_engine.connect() as connection:
            seed = dict(connection.execute(sa.text("SELECT * FROM ecs_execution_jobs WHERE id='unknown'")).mappings().one())
        _exercise_native_dependency(native_engine, executor_engine, monkeypatch, tmp_path, scheduled=True, physical_b=setup)
        assert evidence["c2_read_actual_published_report"] and evidence["normal_stop_exact_id_absent"] and not evidence["finally_removed"]
        assert evidence["c1_run_id"] != evidence["c2_run_id"] and evidence["task_run_count"] == 1 and evidence["final_occurrence_status"] == "success"
        with executor_engine.connect() as connection:
            assert dict(connection.execute(sa.text("SELECT * FROM ecs_execution_jobs WHERE id='unknown'")).mappings().one()) == seed
    finally:
        if jobs is not None:
            jobs.publication.engine.dispose()
        if b_store is not None:
            b_store.engine.dispose()
        try:
            with admin.connect() as connection:
                connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}"'))
        finally:
            admin.dispose()
