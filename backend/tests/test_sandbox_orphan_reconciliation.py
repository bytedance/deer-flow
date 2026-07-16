"""Tests for sandbox container orphan reconciliation on startup.

Covers:
- SandboxBackend.list_running() default behavior
- LocalContainerBackend.list_running() with mocked docker commands
- _parse_docker_timestamp() / _extract_host_port() helpers
- AioSandboxProvider._reconcile_orphans() decision logic
- SIGHUP signal handler registration
"""

import importlib
import json
import signal
import threading
import time
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from deerflow.community.aio_sandbox.sandbox_info import SandboxInfo

# ── SandboxBackend.list_running() default ────────────────────────────────────


def test_backend_list_running_default_returns_empty():
    """Base SandboxBackend.list_running() returns empty list (backward compat for RemoteSandboxBackend)."""
    from deerflow.community.aio_sandbox.backend import SandboxBackend

    class StubBackend(SandboxBackend):
        def create(self, thread_id, sandbox_id, extra_mounts=None, *, user_id=None):
            del thread_id, sandbox_id, extra_mounts, user_id
            pass

        def destroy(self, info):
            pass

        def is_alive(self, info):
            return False

        def discover(self, sandbox_id):
            return None

    backend = StubBackend()
    assert backend.list_running() == []


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_local_backend():
    """Create a LocalContainerBackend with minimal config."""
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend

    return LocalContainerBackend(
        image="test-image:latest",
        base_port=8080,
        container_prefix="deer-flow-sandbox",
        config_mounts=[],
        environment={},
    )


def _make_inspect_entry(name: str, created: str, host_port: str | None = None) -> dict:
    """Build a minimal docker inspect JSON entry matching the real schema."""
    ports: dict = {}
    if host_port is not None:
        ports["8080/tcp"] = [{"HostIp": "0.0.0.0", "HostPort": host_port}]
    return {
        "Name": f"/{name}",  # docker inspect prefixes names with "/"
        "Created": created,
        "NetworkSettings": {"Ports": ports},
    }


def _mock_ps_and_inspect(monkeypatch, ps_output: str, inspect_payload: list | None):
    """Patch subprocess.run to serve fixed ps + inspect responses."""
    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = ps_output
            result.stderr = ""
            return result
        if len(cmd) >= 2 and cmd[1] == "inspect":
            if inspect_payload is None:
                result.returncode = 1
                result.stdout = ""
                result.stderr = "inspect failed"
                return result
            result.returncode = 0
            result.stdout = json.dumps(inspect_payload)
            result.stderr = ""
            return result
        result.returncode = 1
        result.stdout = ""
        result.stderr = "unexpected command"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)


# ── LocalContainerBackend.list_running() ─────────────────────────────────────


def test_list_running_returns_containers(monkeypatch):
    """list_running should enumerate containers via docker ps and batch-inspect them."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\ndeer-flow-sandbox-def67890\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50.000000000Z", "8081"),
            _make_inspect_entry("deer-flow-sandbox-def67890", "2026-04-08T02:22:50.000000000Z", "8082"),
        ],
    )

    infos = backend.list_running()

    assert len(infos) == 2
    ids = {info.sandbox_id for info in infos}
    assert ids == {"abc12345", "def67890"}
    urls = {info.sandbox_url for info in infos}
    assert "http://localhost:8081" in urls
    assert "http://localhost:8082" in urls


def test_list_running_empty_when_no_containers(monkeypatch):
    """list_running should return empty list when docker ps returns nothing."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")
    _mock_ps_and_inspect(monkeypatch, ps_output="", inspect_payload=[])

    assert backend.list_running() == []


def test_list_running_skips_non_matching_names(monkeypatch):
    """list_running should skip containers whose names don't match the prefix pattern."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\nsome-other-container\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50Z", "8081"),
        ],
    )

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"


def test_list_running_includes_containers_without_port(monkeypatch):
    """Containers without a port mapping should still be listed (with empty URL)."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\n",
        inspect_payload=[
            _make_inspect_entry("deer-flow-sandbox-abc12345", "2026-04-08T01:22:50Z", host_port=None),
        ],
    )

    infos = backend.list_running()
    assert len(infos) == 1
    assert infos[0].sandbox_id == "abc12345"
    assert infos[0].sandbox_url == ""


def test_list_running_handles_docker_failure(monkeypatch):
    """list_running should return empty list when docker ps fails."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "daemon not running"
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


def test_list_running_handles_inspect_failure(monkeypatch):
    """list_running should return empty list when batch inspect fails."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    _mock_ps_and_inspect(
        monkeypatch,
        ps_output="deer-flow-sandbox-abc12345\n",
        inspect_payload=None,  # Signals inspect failure
    )

    assert backend.list_running() == []


def test_list_running_handles_malformed_inspect_json(monkeypatch):
    """list_running should return empty list when docker inspect emits invalid JSON."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-abc12345\n"
            result.stderr = ""
        else:
            result.returncode = 0
            result.stdout = "this is not json"
            result.stderr = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert backend.list_running() == []


def test_list_running_uses_single_batch_inspect_call(monkeypatch):
    """list_running should issue exactly ONE docker inspect call regardless of container count."""
    backend = _make_local_backend()
    monkeypatch.setattr(backend, "_runtime", "docker")

    inspect_call_count = {"count": 0}

    import subprocess

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        if len(cmd) >= 2 and cmd[1] == "ps":
            result.returncode = 0
            result.stdout = "deer-flow-sandbox-a\ndeer-flow-sandbox-b\ndeer-flow-sandbox-c\n"
            result.stderr = ""
            return result
        if len(cmd) >= 2 and cmd[1] == "inspect":
            inspect_call_count["count"] += 1
            # Expect all three names passed in a single call
            assert cmd[2:] == ["deer-flow-sandbox-a", "deer-flow-sandbox-b", "deer-flow-sandbox-c"]
            result.returncode = 0
            result.stdout = json.dumps(
                [
                    _make_inspect_entry("deer-flow-sandbox-a", "2026-04-08T01:22:50Z", "8081"),
                    _make_inspect_entry("deer-flow-sandbox-b", "2026-04-08T01:22:50Z", "8082"),
                    _make_inspect_entry("deer-flow-sandbox-c", "2026-04-08T01:22:50Z", "8083"),
                ]
            )
            result.stderr = ""
            return result
        result.returncode = 1
        result.stdout = ""
        return result

    monkeypatch.setattr(subprocess, "run", mock_run)

    infos = backend.list_running()
    assert len(infos) == 3
    assert inspect_call_count["count"] == 1  # ← The core performance assertion


# ── _parse_docker_timestamp() ────────────────────────────────────────────────


def test_parse_docker_timestamp_with_nanoseconds():
    """Should correctly parse Docker's ISO 8601 timestamp with nanoseconds."""
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    ts = _parse_docker_timestamp("2026-04-08T01:22:50.123456789Z")
    assert ts > 0
    expected = datetime(2026, 4, 8, 1, 22, 50, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 1.0


def test_parse_docker_timestamp_without_fractional_seconds():
    """Should parse plain ISO 8601 timestamps without fractional seconds."""
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    ts = _parse_docker_timestamp("2026-04-08T01:22:50Z")
    expected = datetime(2026, 4, 8, 1, 22, 50, tzinfo=UTC).timestamp()
    assert abs(ts - expected) < 1.0


def test_parse_docker_timestamp_empty_returns_zero():
    from deerflow.community.aio_sandbox.local_backend import _parse_docker_timestamp

    assert _parse_docker_timestamp("") == 0.0
    assert _parse_docker_timestamp("not a timestamp") == 0.0


# ── _extract_host_port() ─────────────────────────────────────────────────────


def test_extract_host_port_returns_mapped_port():
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    entry = {"NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "8081"}]}}}
    assert _extract_host_port(entry, 8080) == 8081


def test_extract_host_port_returns_none_when_unmapped():
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    entry = {"NetworkSettings": {"Ports": {}}}
    assert _extract_host_port(entry, 8080) is None


def test_extract_host_port_handles_missing_fields():
    from deerflow.community.aio_sandbox.local_backend import _extract_host_port

    assert _extract_host_port({}, 8080) is None
    assert _extract_host_port({"NetworkSettings": None}, 8080) is None


# ── AioSandboxProvider._reconcile_orphans() ──────────────────────────────────


def _make_provider_for_reconciliation(tmp_path=None, *, worker_id: str = "worker-test"):
    """Build a minimal AioSandboxProvider without triggering __init__ side effects.

    WARNING: This helper intentionally bypasses ``__init__`` via ``__new__`` so
    tests don't depend on Docker or touch the real idle-checker thread.  The
    downside is that this helper is tightly coupled to the set of attributes
    set up in ``AioSandboxProvider.__init__``.  If ``__init__`` gains a new
    attribute that ``_reconcile_orphans`` (or other methods under test) reads,
    this helper must be updated in lockstep — otherwise tests will fail with a
    confusing ``AttributeError`` instead of a meaningful assertion failure.
    """
    import tempfile
    from pathlib import Path

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._shutdown_called = False
    provider._idle_checker_stop = threading.Event()
    provider._idle_checker_thread = None
    provider._config = {
        "idle_timeout": 600,
        "replicas": 3,
    }
    provider._backend = MagicMock()
    provider._worker_id = worker_id
    if tmp_path is None:
        provider._lease_base_dir = Path(tempfile.mkdtemp(prefix="aio-sandbox-lease-"))
    else:
        provider._lease_base_dir = Path(tmp_path)
    return provider


def test_reconcile_adopts_old_containers_into_warm_pool(tmp_path):
    """Lease-free containers are adopted into warm pool — idle checker handles cleanup."""
    provider = _make_provider_for_reconciliation(tmp_path)
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old12345",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old12345",
        created_at=now - 1200,  # 20 minutes old, > 600s idle_timeout
    )
    provider._backend.list_running.return_value = [old_info]

    provider._reconcile_orphans()

    # Should NOT destroy directly — let idle checker handle it
    provider._backend.destroy.assert_not_called()
    assert "old12345" in provider._warm_pool


def test_reconcile_adopts_young_containers(tmp_path):
    """Young lease-free containers are adopted into warm pool for potential reuse."""
    provider = _make_provider_for_reconciliation(tmp_path)
    now = time.time()

    young_info = SandboxInfo(
        sandbox_id="young123",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young123",
        created_at=now - 60,  # 1 minute old, < 600s idle_timeout
    )
    provider._backend.list_running.return_value = [young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "young123" in provider._warm_pool
    adopted_info, release_ts = provider._warm_pool["young123"]
    assert adopted_info.sandbox_id == "young123"


def test_reconcile_mixed_containers_all_adopted(tmp_path):
    """All lease-free containers (old and young) are adopted into warm pool."""
    provider = _make_provider_for_reconciliation(tmp_path)
    now = time.time()

    old_info = SandboxInfo(
        sandbox_id="old_one",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-old_one",
        created_at=now - 1200,
    )
    young_info = SandboxInfo(
        sandbox_id="young_one",
        sandbox_url="http://localhost:8082",
        container_name="deer-flow-sandbox-young_one",
        created_at=now - 60,
    )
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "old_one" in provider._warm_pool
    assert "young_one" in provider._warm_pool


def test_reconcile_skips_already_tracked_containers(tmp_path):
    """Containers already in _sandboxes or _warm_pool should be skipped."""
    provider = _make_provider_for_reconciliation(tmp_path)
    now = time.time()

    existing_info = SandboxInfo(
        sandbox_id="existing1",
        sandbox_url="http://localhost:8081",
        container_name="deer-flow-sandbox-existing1",
        created_at=now - 1200,
    )
    # Pre-populate _sandboxes to simulate already-tracked container
    provider._sandboxes["existing1"] = MagicMock()
    provider._backend.list_running.return_value = [existing_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    # The pre-populated sandbox should NOT be moved into warm pool
    assert "existing1" not in provider._warm_pool


def test_reconcile_handles_backend_failure(tmp_path):
    """Reconciliation should not crash if backend.list_running() fails."""
    provider = _make_provider_for_reconciliation(tmp_path)
    provider._backend.list_running.side_effect = RuntimeError("docker not available")

    # Should not raise
    provider._reconcile_orphans()

    assert provider._warm_pool == {}


def test_reconcile_no_running_containers(tmp_path):
    """Reconciliation with no running containers is a no-op."""
    provider = _make_provider_for_reconciliation(tmp_path)
    provider._backend.list_running.return_value = []

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert provider._warm_pool == {}


def test_reconcile_skips_container_with_live_peer_lease(tmp_path):
    """#4206: do not adopt a container another worker still owns."""
    from deerflow.community.aio_sandbox.sandbox_lease import touch_lease

    worker_a = _make_provider_for_reconciliation(tmp_path, worker_id="worker-a")
    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    now = time.time()
    info = SandboxInfo(
        sandbox_id="shared01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-shared01",
        created_at=now - 50,
    )
    touch_lease(tmp_path, "shared01", "worker-a", idle_timeout=600)
    worker_b._backend.list_running.return_value = [info]

    worker_b._reconcile_orphans()

    assert "shared01" not in worker_b._warm_pool
    worker_b._backend.destroy.assert_not_called()
    # worker_a is unused beyond the lease identity; silence linters
    assert worker_a._worker_id == "worker-a"


def test_idle_reap_does_not_destroy_peer_owned_warm_entry(tmp_path):
    """#4206: idle reaper must not stop a container under another worker's lease."""
    from deerflow.community.aio_sandbox.sandbox_lease import touch_lease

    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    worker_b._config["idle_timeout"] = 60
    now = time.time()
    info = SandboxInfo(
        sandbox_id="a99c8444",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-a99c8444",
        created_at=now - 50,
    )
    # Simulate the bad old path: B already has it in warm (or adopted wrongly).
    worker_b._warm_pool["a99c8444"] = (info, now - 61)
    touch_lease(tmp_path, "a99c8444", "worker-a", idle_timeout=600)

    worker_b._reap_expired_warm(idle_timeout=60)

    worker_b._backend.destroy.assert_not_called()


def test_multi_worker_release_then_peer_reconcile_cannot_kill(tmp_path):
    """#4206 issue-log path: A release→warm; B reconcile+reap must not destroy."""
    from deerflow.community.aio_sandbox.sandbox_lease import touch_lease

    destroyed: list[str] = []
    running: dict[str, SandboxInfo] = {}

    def list_running():
        return list(running.values())

    def destroy(info: SandboxInfo):
        destroyed.append(info.sandbox_id)
        running.pop(info.sandbox_id, None)

    backend = MagicMock()
    backend.list_running.side_effect = list_running
    backend.destroy.side_effect = destroy

    sid = "a99c8444"
    info = SandboxInfo(
        sandbox_id=sid,
        sandbox_url="http://localhost:8080",
        container_name=f"deer-flow-sandbox-{sid}",
        created_at=time.time() - 50,
    )
    running[sid] = info

    worker_a = _make_provider_for_reconciliation(tmp_path, worker_id="worker-a")
    worker_a._backend = backend
    worker_a._config["idle_timeout"] = 60
    # A released to warm and holds the lease (release always touches lease).
    worker_a._warm_pool[sid] = (info, time.time())
    touch_lease(tmp_path, sid, "worker-a", idle_timeout=60)

    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    worker_b._backend = backend
    worker_b._config["idle_timeout"] = 60
    worker_b._reconcile_orphans()
    assert sid not in worker_b._warm_pool

    # Even if B somehow had it warm, reap must refuse.
    worker_b._warm_pool[sid] = (info, time.time() - 61)
    worker_b._reap_expired_warm(idle_timeout=60)
    assert sid not in destroyed
    assert sid in running
    assert sid in worker_a._warm_pool


# ── Review round 2 (fancyboi999): fail-open, hot-path IO, check→destroy race ──


def test_corrupt_lease_fails_closed_not_read_as_free(tmp_path):
    """P2a: a corrupt lease must not be read as 'no owner'.

    ``read_lease`` used to swallow read/parse errors and return None, so a
    corrupt or unreadable peer lease looked free and the destroy path killed the
    container. It must now raise so the provider fails closed.
    """
    from deerflow.community.aio_sandbox.sandbox_lease import (
        CorruptLeaseError,
        foreign_lease_blocks,
        lease_dir,
        lease_path,
        read_lease,
    )

    lease_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    lease_path(tmp_path, "corrupt01").write_text("{ not json", encoding="utf-8")

    with pytest.raises(CorruptLeaseError):
        read_lease(lease_path(tmp_path, "corrupt01"))
    # foreign_lease_blocks propagates; the provider wrapper fails closed to True.
    with pytest.raises(OSError):
        foreign_lease_blocks(tmp_path, "corrupt01", "worker-b")

    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    assert worker_b._foreign_lease_blocks("corrupt01") is True
    assert worker_b._can_destroy_shared_container("corrupt01") is False


def test_unreadable_lease_fails_closed(tmp_path, monkeypatch):
    """P2a: a lease that raises PermissionError on read must fail closed too."""
    from deerflow.community.aio_sandbox import sandbox_lease as lease_mod
    from deerflow.community.aio_sandbox.sandbox_lease import lease_dir, lease_path

    lease_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    lease_path(tmp_path, "locked01").write_text("{}", encoding="utf-8")

    real_read_text = lease_mod.Path.read_text

    def deny(self, *args, **kwargs):
        if self.name.endswith("locked01.lease"):
            raise PermissionError("EACCES")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(lease_mod.Path, "read_text", deny)

    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    assert worker_b._foreign_lease_blocks("locked01") is True


def test_corrupt_lease_blocks_idle_destroy(tmp_path):
    """P2a end-to-end: idle reaper must not stop a container whose lease is corrupt."""
    from deerflow.community.aio_sandbox.sandbox_lease import lease_dir, lease_path

    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    worker_b._config["idle_timeout"] = 60
    now = time.time()
    info = SandboxInfo(
        sandbox_id="corrupt02",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-corrupt02",
        created_at=now - 50,
    )
    lease_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    lease_path(tmp_path, "corrupt02").write_text("garbage", encoding="utf-8")
    worker_b._warm_pool["corrupt02"] = (info, now - 61)

    worker_b._reap_expired_warm(idle_timeout=60)

    worker_b._backend.destroy.assert_not_called()


def test_get_does_not_renew_lease(tmp_path, monkeypatch):
    """P2b: get() is a pure in-memory lookup — it must not write the lease.

    ``ensure_sandbox_initialized_async`` calls ``provider.get()`` directly on the
    event loop, so a lease write here (mkdir + fsync + os.replace) would be
    blocking IO on the hot path. Renewal now happens off the event loop.
    """
    worker = _make_provider_for_reconciliation(tmp_path)
    sandbox = MagicMock()
    worker._sandboxes["sb1"] = sandbox

    touched: list[str] = []
    monkeypatch.setattr(worker, "_touch_sandbox_lease", lambda sid: touched.append(sid))

    assert worker.get("sb1") is sandbox
    assert touched == [], "get() must not renew the lease on the event-loop hot path"


def test_idle_cycle_renews_active_leases(tmp_path):
    """P2b: the background idle path renews active-sandbox leases off the event loop."""
    from deerflow.community.aio_sandbox.sandbox_lease import lease_path, read_lease

    worker = _make_provider_for_reconciliation(tmp_path, worker_id="worker-a")
    worker._sandboxes["sb1"] = MagicMock()

    worker._renew_active_leases()

    lease = read_lease(lease_path(tmp_path, "sb1"))
    assert lease is not None and lease.worker_id == "worker-a"


def test_peer_touch_cannot_interleave_with_destroy(tmp_path):
    """P1: the ownership check → container stop is one cross-process atomic op.

    A peer's ``touch_lease`` shares the same per-sandbox guard, so it cannot land
    between a destroy's ownership check and the container stop (the interleaving
    that revived the cross-worker kill). Here worker-a holds the guard mid-stop;
    worker-b's touch must block until worker-a releases it.
    """
    worker_a = _make_provider_for_reconciliation(tmp_path, worker_id="worker-a")
    worker_b = _make_provider_for_reconciliation(tmp_path, worker_id="worker-b")
    sid = "race01"
    info = SandboxInfo(
        sandbox_id=sid,
        sandbox_url="http://localhost:8080",
        container_name=f"deer-flow-sandbox-{sid}",
        created_at=time.time() - 50,
    )

    in_destroy = threading.Event()
    release_destroy = threading.Event()
    touch_done = threading.Event()

    def slow_destroy(_info):
        in_destroy.set()
        assert release_destroy.wait(3), "test did not release the destroy in time"

    worker_a._backend.destroy.side_effect = slow_destroy

    def do_destroy():
        worker_a._destroy_warm_entry(sid, info, reason="idle_timeout")

    def do_touch():
        assert in_destroy.wait(3)
        worker_b._touch_sandbox_lease(sid)
        touch_done.set()

    t_destroy = threading.Thread(target=do_destroy)
    t_touch = threading.Thread(target=do_touch)
    t_destroy.start()
    t_touch.start()
    try:
        assert in_destroy.wait(3)
        # worker-a holds the per-sandbox guard across backend.destroy; worker-b's
        # touch must not complete until the guard is released.
        assert not touch_done.wait(0.4), "peer touch interleaved with destroy — guard not exclusive"
    finally:
        release_destroy.set()
        t_destroy.join(3)
        t_touch.join(3)

    assert touch_done.is_set()
    worker_a._backend.destroy.assert_called_once()


def test_reconcile_multiple_containers_all_adopted(tmp_path):
    """Multiple lease-free containers should all be adopted into warm pool."""
    provider = _make_provider_for_reconciliation(tmp_path)
    now = time.time()

    info1 = SandboxInfo(sandbox_id="cont_one", sandbox_url="http://localhost:8081", created_at=now - 1200)
    info2 = SandboxInfo(sandbox_id="cont_two", sandbox_url="http://localhost:8082", created_at=now - 1200)

    provider._backend.list_running.return_value = [info1, info2]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "cont_one" in provider._warm_pool
    assert "cont_two" in provider._warm_pool


def test_reconcile_zero_created_at_adopted():
    """Containers with created_at=0 (unknown age) should still be adopted into warm pool."""
    provider = _make_provider_for_reconciliation()

    info = SandboxInfo(sandbox_id="unknown1", sandbox_url="http://localhost:8081", created_at=0.0)
    provider._backend.list_running.return_value = [info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "unknown1" in provider._warm_pool


def test_reconcile_idle_timeout_zero_adopts_all():
    """When idle_timeout=0 (disabled), all containers are still adopted into warm pool."""
    provider = _make_provider_for_reconciliation()
    provider._config["idle_timeout"] = 0
    now = time.time()

    old_info = SandboxInfo(sandbox_id="old_one", sandbox_url="http://localhost:8081", created_at=now - 7200)
    young_info = SandboxInfo(sandbox_id="young_one", sandbox_url="http://localhost:8082", created_at=now - 60)
    provider._backend.list_running.return_value = [old_info, young_info]

    provider._reconcile_orphans()

    provider._backend.destroy.assert_not_called()
    assert "old_one" in provider._warm_pool
    assert "young_one" in provider._warm_pool


# ── SIGHUP signal handler ───────────────────────────────────────────────────


def test_sighup_handler_registered():
    """SIGHUP handler should be registered on Unix systems."""
    if not hasattr(signal, "SIGHUP"):
        pytest.skip("SIGHUP not available on this platform")

    provider = _make_provider_for_reconciliation()

    # Save original handlers for ALL signals we'll modify
    original_sighup = signal.getsignal(signal.SIGHUP)
    original_sigterm = signal.getsignal(signal.SIGTERM)
    original_sigint = signal.getsignal(signal.SIGINT)
    try:
        aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
        provider._original_sighup = original_sighup
        provider._original_sigterm = original_sigterm
        provider._original_sigint = original_sigint
        provider.shutdown = MagicMock()

        aio_mod.AioSandboxProvider._register_signal_handlers(provider)

        # Verify SIGHUP handler is no longer the default
        handler = signal.getsignal(signal.SIGHUP)
        assert handler != signal.SIG_DFL, "SIGHUP handler should be registered"
    finally:
        # Restore ALL original handlers to avoid leaking state across tests
        signal.signal(signal.SIGHUP, original_sighup)
        signal.signal(signal.SIGTERM, original_sigterm)
        signal.signal(signal.SIGINT, original_sigint)
