"""Operator lifecycle fences retain unknown physical work across service restart."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def source(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "packages/ecs-executor"))


def test_operator_drain_shared_restarts_and_unknown_reservation(tmp_path):
    from ecs_executor.job_store import JobStore
    from ecs_executor.nodes import Node
    from ecs_executor.scheduling import Scheduling

    store = JobStore("sqlite:///" + str(tmp_path / "ledger.db"))
    store.initialize()
    nodes = {"one": Node(cpu_millis=2000, memory_mib=4096, resident_cpu_millis=1500, resident_memory_mib=2048, max_concurrency=1, profiles={"small"}, kinds={"B", "C"})}
    pool = Scheduling(store, nodes=nodes)
    job = store.create(namespace="ops", request_key="job", spec_digest="digest", record={"kind": "B", "spec": {"profile": "small"}, "profile": {"cpu_millis": 500, "memory_mib": 128}})
    store.mutate(job["id"], lambda row: row.update(state="queued"))
    pool.set_operator_drain("one", True)
    other = Scheduling(store, nodes=nodes)
    assert pool.node_status("one") == {"operator_drain": True, "unreleased": 0}
    assert other.claim("one", "daemon") is None
    assert other.claim("one", "native", kind="C") is None
    other.set_operator_drain("one", False)
    claimed = pool.claim("one", "daemon")
    assert claimed["id"] == job["id"]
    pool.set_operator_drain("one", True)
    store.mutate(job["id"], lambda row: row.update(state="uncertain", lease_until=0))
    assert pool.node_status("one") == {"operator_drain": True, "unreleased": 1}
    recovered = other.owned("one", "replacement")
    assert recovered[0]["id"] == job["id"]
    assert other.claim("one", "replacement") is None
    other.report("one", "replacement", job["id"], recovered[0]["generation"], {"state": "failed", "physical_stopped": True})
    assert pool.node_status("one")["unreleased"] == 0
    assert Scheduling(store, nodes=nodes).node_status("one")["operator_drain"] is True
    with pytest.raises(ValueError):
        pool.set_operator_drain("unknown", False)


def test_preflight_requires_real_mount_marker_and_immutable_image(tmp_path, monkeypatch):
    import json

    from ecs_executor.operations import preflight, select_image

    root = tmp_path / "nas"
    root.mkdir()
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    config = {"nas_root": str(root), "mount_id": "owned-fixture", "image": "sha256:" + "a" * 64, "scope": "production", "private_dir": str(private), "node_id": "one", "sandbox_prefix": "deer-ops-worker"}
    with pytest.raises(ValueError, match="mount"):
        preflight(config)
    config["scope"] = "owned-local-fixture"
    (root / "pool").mkdir()
    with pytest.raises(ValueError, match="marker"):
        preflight(config)
    (root / "pool/pool-mount-id").write_text("owned-fixture")
    preflight(config)
    manifest = private / "previous.json"
    manifest.write_text(json.dumps({"image": "sha256:" + "b" * 64, "executor_revision": "e0001_execution_ledger", "native_revision": "0035_native_fork_compatibility", "generation": "backup-1", "config_sha256": "c" * 64}))
    manifest.chmod(0o600)
    assert select_image(manifest)["generation"] == "backup-1"
    manifest.write_text(json.dumps({"image": "deerflow:latest"}))
    with pytest.raises(ValueError, match="immutable"):
        select_image(manifest)


@pytest.mark.asyncio
async def test_controller_remote_all_requires_literal_operator_true():
    from types import SimpleNamespace

    from ecs_executor.agent_dispatch import NativeDispatchHost

    from deerflow.runtime.runs.manager import RunRecord
    from deerflow.runtime.runs.schemas import DisconnectMode, RunStatus

    class Threads:
        async def get(self, *args, **kwargs):
            return None

    app = SimpleNamespace(state=SimpleNamespace(thread_store=Threads()))
    host = NativeDispatchHost(app, None, {"native_node": "one", "remote_origins": ["schedule"]}, {"one": "synthetic"})
    record = RunRecord(run_id="run", thread_id="thread", assistant_id=None, status=RunStatus.pending, on_disconnect=DisconnectMode.continue_, user_id="owner")

    async def snapshot_factory(**kwargs):
        assert kwargs == {"transport_node": "one", "transport_secret": "synthetic"}
        raise RuntimeError("Reached authenticated native snapshot")

    assert await host.admit_native(record, snapshot_factory) is False
    host.config["remote_all"] = "true"
    assert await host.admit_native(record, snapshot_factory) is False
    host.config["remote_all"] = True
    with pytest.raises(RuntimeError, match="Reached authenticated"):
        await host.admit_native(record, snapshot_factory)


def test_unknown_prefix_container_blocks_physical_stop(monkeypatch):
    from ecs_executor import operations

    def command(*args):
        if args[0] == "ps":
            return "" if "label=deerflow.execution.node=one" in args else "owned-id"
        return "/deer-ops-worker-unknown" if args[1] == "--format" and args[2] == "{{.Name}}" else "<no value>"

    monkeypatch.setattr(operations, "docker", command)
    with pytest.raises(RuntimeError, match="Unknown"):
        operations.physical_ids({"node_id": "one", "sandbox_prefix": "deer-ops-worker"})


def test_installed_failure_cleanup_retains_nas_and_handles_when_reservation_unknown(tmp_path, monkeypatch):
    import test_ecs_native_installed_ops as fixture

    root = tmp_path / "owned"
    (root / "nas").mkdir(parents=True)
    (root / "private").mkdir(mode=0o700)
    monkeypatch.setattr(fixture, "_fixture_idle", lambda *args: False)
    from ecs_executor import operations

    monkeypatch.setattr(operations, "docker", lambda *args: "")
    commands = []

    def compose(*args):
        commands.append(args)
        return ""

    assert fixture._cleanup_owned_fixture(root=root, project="deer-ops-owned", node="ops-owned", prefix="deer-ops-owned-worker", compose=compose, operator={}, execution_started=True) is False
    assert (root / "nas").is_dir()
    receipt = __import__("json").loads((root / "cleanup-receipt.json").read_text())
    assert receipt["project"] == "deer-ops-owned" and receipt["node"] == "ops-owned"
    assert receipt["status"] == "uncertain-retained" and commands == []


def test_default_docker_runtime_and_resident_shutdown_budget(monkeypatch):
    from ecs_executor import resident

    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "backend/Dockerfile").read_text()
    stages = [line for line in dockerfile.splitlines() if line.startswith("FROM ")]
    assert stages[-1] == "FROM runtime AS production-default"
    assert "FROM runtime AS native-core" in stages
    assert "FROM native-core AS native-role" in stages
    runtime = dockerfile.split("AS runtime\n", 1)[1].split("FROM runtime AS native-core", 1)[0]
    assert "uvicorn app.gateway.app:app" in runtime

    commands = []

    class Finished:
        returncode = 0

        def poll(self):
            return 0

    monkeypatch.setenv("ECS_RESIDENT_ROLE", "worker")
    monkeypatch.setattr(resident.subprocess, "Popen", lambda command: commands.append(command) or Finished())
    monkeypatch.setattr(resident.signal, "signal", lambda *args: None)
    with pytest.raises(SystemExit) as stopped:
        resident.main()
    assert stopped.value.code == 0
    gateway = commands[0]
    request_grace = int(gateway[gateway.index("--timeout-graceful-shutdown") + 1])
    assert request_grace == 10
    # Gateway services and remote host quiesce need separate lifespan budgets.
    assert request_grace + 71 + 120 < 240
