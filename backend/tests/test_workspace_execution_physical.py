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
