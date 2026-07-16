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
from unittest.mock import MagicMock, patch

import pytest

from deerflow.community.aio_sandbox.aio_sandbox_provider import SandboxBeingDestroyedError
from deerflow.community.aio_sandbox.ownership import compute_lease_ttl
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


def _make_shared_ownership_store(**kwargs):
    """A store two provider instances can share.

    Sharing one store object between two providers is how these tests model two
    gateway instances pointed at one Redis: the provider only ever sees the
    ``SandboxOwnershipStore`` ABC, so the ownership behaviour exercised here is
    backend-agnostic. The redis backend's own semantics are pinned separately in
    ``test_sandbox_ownership_store.py``.
    """
    from deerflow.community.aio_sandbox.ownership.memory import MemoryOwnershipStore

    kwargs.setdefault("ttl_seconds", 600)
    return MemoryOwnershipStore(owner_id="__shared__", **kwargs)


class _ScopedOwnershipStore:
    """View of a shared store as seen by one instance (rebinds ``owner_id``)."""

    def __init__(self, shared, owner_id: str):
        self._shared = shared
        self._owner_id = owner_id

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def supports_cross_process(self) -> bool:
        return True

    def _as_me(self, fn, *args):
        previous = self._shared._owner_id
        self._shared._owner_id = self._owner_id
        try:
            return fn(*args)
        finally:
            self._shared._owner_id = previous

    def take(self, sandbox_id):
        return self._as_me(self._shared.take, sandbox_id)

    def claim(self, sandbox_id, *, for_destroy: bool = False):
        return self._as_me(lambda sid: self._shared.claim(sid, for_destroy=for_destroy), sandbox_id)

    def renew(self, sandbox_id):
        return self._as_me(self._shared.renew, sandbox_id)

    def release(self, sandbox_id):
        return self._as_me(self._shared.release, sandbox_id)

    def owner(self, sandbox_id):
        return self._shared.owner(sandbox_id)

    def close(self):
        pass


def _make_provider_for_reconciliation(tmp_path=None, *, worker_id: str = "worker-test", store=None):
    """Build a minimal AioSandboxProvider without triggering __init__ side effects.

    WARNING: This helper intentionally bypasses ``__init__`` via ``__new__`` so
    tests don't depend on Docker or touch the real idle-checker/renewal threads.
    The downside is that this helper is tightly coupled to the set of attributes
    set up in ``AioSandboxProvider.__init__``.  If ``__init__`` gains a new
    attribute that ``_reconcile_orphans`` (or other methods under test) reads,
    this helper must be updated in lockstep — otherwise tests will fail with a
    confusing ``AttributeError`` instead of a meaningful assertion failure.

    Pass a shared *store* (see ``_make_shared_ownership_store``) to two providers
    to model two gateway instances coordinating through one ownership backend.
    ``tmp_path`` is accepted and ignored: ownership no longer lives on disk.
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)
    provider._lock = threading.Lock()
    provider._sandboxes = {}
    provider._sandbox_infos = {}
    provider._thread_sandboxes = {}
    provider._thread_locks = {}
    provider._last_activity = {}
    provider._warm_pool = {}
    provider._unowned_since = {}
    provider._shutdown_called = False
    provider._idle_checker_stop = threading.Event()
    provider._idle_checker_thread = None
    provider._renewal_stop = threading.Event()
    provider._renewal_thread = None
    provider._config = {
        "idle_timeout": 600,
        "replicas": 3,
    }
    provider._backend = MagicMock()
    provider._owner_id = worker_id
    provider._ownership_config = SandboxOwnershipConfig()
    if store is None:
        from deerflow.community.aio_sandbox.ownership.memory import MemoryOwnershipStore

        provider._ownership = MemoryOwnershipStore(owner_id=worker_id, ttl_seconds=600)
    else:
        provider._ownership = _ScopedOwnershipStore(store, worker_id)
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


def test_reconcile_skips_container_owned_by_peer():
    """#4206: do not adopt a container another instance still owns."""
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    now = time.time()
    info = SandboxInfo(
        sandbox_id="shared01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-shared01",
        created_at=now - 50,
    )
    worker_a._publish_ownership("shared01")
    worker_b._backend.list_running.return_value = [info]

    worker_b._reconcile_orphans()

    assert "shared01" not in worker_b._warm_pool
    worker_b._backend.destroy.assert_not_called()
    # The lease is still A's — B's failed claim must not have stolen it.
    assert shared.owner("shared01") == "worker-a"


def test_idle_reap_does_not_destroy_peer_owned_warm_entry():
    """#4206: idle reaper must not stop a container another instance owns."""
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
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
    worker_a._publish_ownership("a99c8444")

    worker_b._reap_expired_warm(idle_timeout=60)

    worker_b._backend.destroy.assert_not_called()


def test_multi_worker_release_then_peer_reconcile_cannot_kill():
    """#4206 issue-log path: A release→warm; B reconcile+reap must not destroy."""
    shared = _make_shared_ownership_store()
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

    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_a._backend = backend
    worker_a._config["idle_timeout"] = 60
    # A released to warm and holds the lease.
    worker_a._warm_pool[sid] = (info, time.time())
    worker_a._publish_ownership(sid)

    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
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


def test_expired_lease_lets_peer_adopt_crashed_owner_container():
    """The crash path still works: once a dead owner's lease lapses, adopt it.

    The counterpart to the tests above — ownership must not become a permanent
    leak when the owning instance dies without releasing. Adoption is delayed by
    the recovery grace, but a dead owner never republishes, so it still happens.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    shared = _make_shared_ownership_store(ttl_seconds=0.05)
    dead = _make_provider_for_reconciliation(worker_id="worker-dead", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="crashed1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-crashed1",
        created_at=time.time() - 50,
    )
    dead._publish_ownership("crashed1")
    worker_b._backend.list_running.return_value = [info]

    # Owner "crashes": stops renewing. Its lease lapses in the store.
    time.sleep(0.1)

    now = time.time()
    with patch.object(aio_mod.time, "time", return_value=now):
        worker_b._reconcile_orphans()
    assert "crashed1" not in worker_b._warm_pool, "adopted a lapsed lease without waiting out the recovery grace"

    # The dead owner never republishes, so the grace runs out and B adopts.
    with patch.object(aio_mod.time, "time", return_value=now + compute_lease_ttl(worker_b._ownership_config) + 1):
        worker_b._reconcile_orphans()

    assert "crashed1" in worker_b._warm_pool
    assert shared.owner("crashed1") == "worker-b"


# ── Ownership store rework (#4206): fail-closed publish, renewal independence ──


def test_acquire_fails_closed_when_ownership_cannot_be_published():
    """Establishment is fail-closed: never hand out a sandbox we could not own.

    The provider used to swallow the lease-write error and return the sandbox id
    on the next line, so a store outage silently disabled the only cross-instance
    exclusion while the sandbox was handed out as usable — peers then saw an
    unowned live container and reaped it.
    """
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership = MagicMock()
    worker._ownership.take.side_effect = OwnershipBackendError("store down")

    info = SandboxInfo(
        sandbox_id="new001",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-new001",
        created_at=time.time(),
    )

    with pytest.raises(OwnershipBackendError):
        worker._register_created_sandbox("t1", "new001", info, user_id="u1")

    # The just-created container must not be leaked as an unowned orphan.
    worker._backend.destroy.assert_called_once_with(info)
    assert "new001" not in worker._sandboxes


def test_reuse_fails_closed_when_ownership_cannot_be_published():
    """Same fail-closed rule on the in-process reuse path."""
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    info = SandboxInfo(
        sandbox_id="sb1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-sb1",
        created_at=time.time(),
    )
    worker._sandboxes["sb1"] = MagicMock()
    worker._sandbox_infos["sb1"] = info
    worker._thread_sandboxes[("u1", "t1")] = "sb1"
    worker._check_tracked_sandbox_alive = MagicMock(return_value=True)
    worker._ownership = MagicMock()
    worker._ownership.take.side_effect = OwnershipBackendError("store down")

    with pytest.raises(OwnershipBackendError):
        worker._reuse_in_process_sandbox("t1", user_id="u1")


def test_destroy_fails_closed_when_ownership_unknown():
    """A store that cannot answer must not be read as 'container is free'."""
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership = MagicMock()
    worker._ownership.claim.side_effect = OwnershipBackendError("store down")

    info = SandboxInfo(
        sandbox_id="unknown1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-unknown1",
        created_at=time.time() - 50,
    )

    worker._destroy_warm_entry("unknown1", info, reason="idle_timeout")

    worker._backend.destroy.assert_not_called()


def test_reconcile_fails_closed_when_ownership_unknown():
    """A store outage must not turn every peer container into an adoptable orphan."""
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-b")
    worker._ownership = MagicMock()
    # Configure what the adoption grace reads, or it short-circuits before the
    # claim: a bare MagicMock answers `owner()` with a truthy mock, which reads
    # as "peer-owned" and defers — so the assertion below would pass without the
    # fail-closed branch ever running (it did exactly that until this was fixed).
    worker._ownership.supports_cross_process = True
    worker._ownership.owner.return_value = None
    worker._ownership.claim.side_effect = OwnershipBackendError("store down")
    info = SandboxInfo(
        sandbox_id="unknown2",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-unknown2",
        created_at=time.time() - 50,
    )
    worker._backend.list_running.return_value = [info]

    # Unowned for a full grace, so the container is adoptable and the only thing
    # left standing between it and the warm pool is the claim.
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    now = time.time()
    with patch.object(aio_mod.time, "time", return_value=now):
        worker._reconcile_orphans()
    with patch.object(aio_mod.time, "time", return_value=now + compute_lease_ttl(worker._ownership_config) + 1):
        worker._reconcile_orphans()

    assert worker._ownership.claim.called, "the fail-closed claim branch was never reached; this test guards nothing"
    assert "unknown2" not in worker._warm_pool
    worker._backend.destroy.assert_not_called()


@pytest.mark.parametrize("idle_timeout", [0, 600])
def test_init_always_starts_lease_renewal(monkeypatch, idle_timeout):
    """Renewal liveness must not ride on the idle checker's switch.

    ``_renew_active_leases`` used to have exactly one caller — ``_cleanup_idle_resources``
    — and ``__init__`` only starts the idle checker when ``idle_timeout > 0``.
    ``idle_timeout: 0`` is a supported config (``config.example.yaml`` documents it
    as "keep warm VMs until shutdown"), so on that config nothing ever refreshed a
    lease and #4206 returned one TTL later.

    This drives ``__init__`` on purpose: the defect is in *who starts renewal*, so
    a test that calls ``_start_lease_renewal()`` directly passes on the broken code
    and guards nothing.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")

    started: list[str] = []
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_load_config", lambda self: {"idle_timeout": idle_timeout, "replicas": 3, "ownership": None})
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_create_backend", lambda self: MagicMock())
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_reconcile_orphans", lambda self: None)
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_register_signal_handlers", lambda self: None)
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_start_lease_renewal", lambda self: started.append("renewal"))
    monkeypatch.setattr(aio_mod.AioSandboxProvider, "_start_idle_checker", lambda self: started.append("idle"))
    monkeypatch.setattr(aio_mod.atexit, "register", lambda *a, **k: None)

    aio_mod.AioSandboxProvider()

    assert "renewal" in started, f"renewal must start at idle_timeout={idle_timeout}; ownership liveness cannot depend on the idle reaper"
    assert ("idle" in started) is (idle_timeout > 0)


def test_renewal_keeps_the_sandbox_when_the_store_cannot_answer():
    """The one deliberate exception to fail-closed, and it had no test.

    Everywhere else an unanswerable store means "not ours". Renewal is the
    opposite on purpose: `_refresh_ownership` returns True on an
    `OwnershipBackendError` because unknown is not lost, and the TTL still bounds
    how long a genuinely dead owner holds the lease. Invert it and a Redis outage
    makes every instance drop every active and warm sandbox at once — the same
    fleet-wide eviction the LAPSED/LOST split exists to prevent, which is pinned
    only for the flushed-store path, never for a raising one.
    """
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership = MagicMock()
    worker._ownership.renew.side_effect = OwnershipBackendError("store down")
    info = SandboxInfo(
        sandbox_id="live02",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-live02",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker._sandboxes["live02"] = sandbox
    worker._sandbox_infos["live02"] = info
    worker._thread_sandboxes[("u1", "t1")] = "live02"
    worker._warm_pool["warm02"] = (info, time.time())

    worker._renew_owned_leases()

    assert worker._ownership.renew.called, "renewal never reached the store; this test guards nothing"
    assert "live02" in worker._sandboxes, "a store outage evicted a live sandbox nobody had taken"
    assert ("u1", "t1") in worker._thread_sandboxes
    assert "warm02" in worker._warm_pool, "a store outage dropped a warm entry nobody had taken"
    sandbox.close.assert_not_called()
    worker._backend.destroy.assert_not_called()


def test_load_config_carries_the_stream_bridge_section():
    """Hop 1 of the "no extra config for multi-instance" promise.

    The redis inference reads `app_config.stream_bridge`, so `_load_config` has to
    carry it. Nothing pinned this: the only test that drives `__init__`
    monkeypatches `_load_config` wholesale and omits the key entirely, so deleting
    it here left every test green while every config.yaml-native multi-instance
    deployment silently fell back to `memory` — #4206 reopened on exactly the
    deployments the inference exists for.
    """
    from deerflow.config.stream_bridge_config import StreamBridgeConfig

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    provider = aio_mod.AioSandboxProvider.__new__(aio_mod.AioSandboxProvider)

    bridge = StreamBridgeConfig(type="redis", redis_url="redis://bridge:6379/0")
    app_config = MagicMock()
    app_config.stream_bridge = bridge
    app_config.sandbox = MagicMock(ownership=None, image=None, port=None, container_prefix=None, idle_timeout=600, replicas=3, mounts=[], environment={})

    with patch.object(aio_mod, "get_app_config", return_value=app_config):
        loaded = provider._load_config()

    assert loaded["stream_bridge"] is bridge, "_load_config dropped the stream_bridge section the redis inference reads"


def test_init_infers_redis_ownership_from_a_redis_stream_bridge():
    """Hop 2: `__init__` must actually feed the bridge into the resolver.

    Drives the real `__init__` against a real `AppConfig`-shaped object rather
    than stubbing `_load_config`, because the defect would be in the wiring
    between them — the same reason `test_init_always_starts_lease_renewal` drives
    `__init__` instead of calling `_start_lease_renewal` directly.
    """
    from deerflow.config.stream_bridge_config import StreamBridgeConfig

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")

    app_config = MagicMock()
    app_config.stream_bridge = StreamBridgeConfig(type="redis", redis_url="redis://bridge:6379/0")
    # No sandbox.ownership section at all: the deployment never configured one.
    app_config.sandbox = MagicMock(ownership=None, image=None, port=None, container_prefix=None, idle_timeout=600, replicas=3, mounts=[], environment={})

    built: list = []

    def fake_store(config, *, owner_id=None):
        built.append(config)
        store = MagicMock()
        store.supports_cross_process = True
        return store

    with (
        patch.object(aio_mod, "get_app_config", return_value=app_config),
        patch.object(aio_mod, "make_sandbox_ownership_store", side_effect=fake_store),
        patch.object(aio_mod.AioSandboxProvider, "_create_backend", lambda self: MagicMock()),
        patch.object(aio_mod.AioSandboxProvider, "_reconcile_orphans", lambda self: None),
        patch.object(aio_mod.AioSandboxProvider, "_register_signal_handlers", lambda self: None),
        patch.object(aio_mod.AioSandboxProvider, "_start_lease_renewal", lambda self: None),
        patch.object(aio_mod.AioSandboxProvider, "_start_idle_checker", lambda self: None),
        patch.object(aio_mod.atexit, "register", lambda *a, **k: None),
    ):
        aio_mod.AioSandboxProvider()

    assert len(built) == 1
    assert built[0].type == "redis", "a redis stream bridge did not infer a redis ownership store; multi-instance deployments silently fall back to memory"
    assert built[0].redis_url == "redis://bridge:6379/0"


def test_renewal_loop_refreshes_owned_leases():
    """The renewal thread actually renews (the loop body, not just its wiring)."""
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.05)
    worker._sandboxes["sb1"] = MagicMock()
    worker._publish_ownership("sb1")

    renewed: list[str] = []
    real_renew = worker._ownership.renew

    def counting_renew(sandbox_id):
        renewed.append(sandbox_id)
        return real_renew(sandbox_id)

    worker._ownership.renew = counting_renew

    worker._start_lease_renewal()
    try:
        deadline = time.time() + 3
        while not renewed and time.time() < deadline:
            time.sleep(0.02)
    finally:
        worker._stop_lease_renewal()

    assert renewed == ["sb1"] or renewed[0] == "sb1"


def test_renewal_covers_warm_entries_not_just_active():
    """A warm container is still ours; letting its lease lapse invites adoption."""
    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    info = SandboxInfo(
        sandbox_id="warm01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-warm01",
        created_at=time.time(),
    )
    worker._sandboxes["active01"] = MagicMock()
    worker._warm_pool["warm01"] = (info, time.time())
    worker._publish_ownership("active01")
    worker._publish_ownership("warm01")

    renewed: list[str] = []
    worker._ownership = MagicMock()
    worker._ownership.renew.side_effect = lambda sid: renewed.append(sid) or True

    worker._renew_owned_leases()

    assert set(renewed) == {"active01", "warm01"}


def test_lost_lease_drops_sandbox_without_destroying_container():
    """Losing the lease means the container is someone else's — drop it, don't kill it.

    Destroying here would be the exact cross-instance kill the store exists to
    prevent, just triggered from the renewal path instead of the reaper. Only our
    host-side handle goes away, and it must be closed rather than leaked (#2872).
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="moved01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-moved01",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker_a._sandboxes["moved01"] = sandbox
    worker_a._sandbox_infos["moved01"] = info
    worker_a._thread_sandboxes[("u1", "t1")] = "moved01"
    worker_a._last_activity["moved01"] = time.time()
    worker_a._publish_ownership("moved01")

    # The thread's next turn routes to B, which takes over ownership.
    worker_b._publish_ownership("moved01")

    worker_a._renew_owned_leases()

    assert "moved01" not in worker_a._sandboxes
    assert "moved01" not in worker_a._sandbox_infos
    assert ("u1", "t1") not in worker_a._thread_sandboxes
    worker_a._backend.destroy.assert_not_called()
    sandbox.close.assert_called_once()
    assert shared.owner("moved01") == "worker-b"


def test_ownership_rollback_on_create_closes_the_client_it_drops():
    """The rollback destroys the container; its host-side client must not leak (#2872)."""
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership = MagicMock()
    worker._ownership.take.side_effect = OwnershipBackendError("store down")
    info = SandboxInfo(
        sandbox_id="new002",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-new002",
        created_at=time.time(),
    )

    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    created: list[MagicMock] = []

    def fake_aio_sandbox(**kwargs):
        sandbox = MagicMock()
        created.append(sandbox)
        return sandbox

    with patch.object(aio_mod, "AioSandbox", side_effect=fake_aio_sandbox):
        with pytest.raises(OwnershipBackendError):
            worker._register_created_sandbox("t1", "new002", info, user_id="u1")

    worker._backend.destroy.assert_called_once_with(info)
    assert created and created[0].close.call_count == 1


def test_acquire_takes_over_ownership_so_a_thread_can_move_instances():
    """A thread's next turn can land on another instance; it must not be stranded.

    Ownership answers "who reaps this", not "who may use it". A conditional claim
    here would refuse while the previous instance's lease was still live and break
    every load-balanced follow-up turn.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="thread01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-thread01",
        created_at=time.time(),
    )
    worker_a._publish_ownership("thread01")
    assert shared.owner("thread01") == "worker-a"

    # B serves the thread's next turn and discovers the existing container.
    assert worker_b._register_discovered_sandbox("t1", info, user_id="u1") == "thread01"
    assert shared.owner("thread01") == "worker-b"


def test_store_losing_all_state_does_not_evict_live_sandboxes():
    """A Redis restart must not drop every in-flight sandbox fleet-wide.

    `renew()` returns falsy for two very different situations: a peer took the
    lease, and the lease is simply absent. Treating them the same meant that when
    Redis restarted without persistence — every key gone, nobody holding
    anything — each instance evicted every sandbox it was actively serving.
    A lapsed lease must be re-established instead.
    """
    shared = _make_shared_ownership_store()
    worker = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    info = SandboxInfo(
        sandbox_id="live01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-live01",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker._sandboxes["live01"] = sandbox
    worker._sandbox_infos["live01"] = info
    worker._thread_sandboxes[("u1", "t1")] = "live01"
    worker._publish_ownership("live01")

    # The store loses everything, as a Redis restart without persistence does.
    shared._leases.clear()

    worker._renew_owned_leases()

    assert "live01" in worker._sandboxes, "a store restart evicted a live sandbox nobody had taken"
    assert ("u1", "t1") in worker._thread_sandboxes
    sandbox.close.assert_not_called()
    worker._backend.destroy.assert_not_called()
    # And it is ours again, so peers still cannot reap it.
    assert shared.owner("live01") == "worker-a"


def test_peer_reconcile_after_state_loss_does_not_steal_a_live_container():
    """The other half of the store-restart case: a peer must not adopt first.

    ``_refresh_ownership`` already refuses to read an absent lease as
    abandonment. Reconciliation must not contradict it on the other path: after
    the store loses every key, each live owner is still serving its containers
    and simply has not reached its next renewal tick. An instance reconciling in
    that window sees no lease and would adopt every one of them; the real owner's
    next renewal then reports LOST and it drops a sandbox mid-turn, which the
    adopter later idle-destroys — #4206 through the back door.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    info = SandboxInfo(
        sandbox_id="live01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-live01",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker_a._sandboxes["live01"] = sandbox
    worker_a._sandbox_infos["live01"] = info
    worker_a._thread_sandboxes[("u1", "t1")] = "live01"
    worker_a._publish_ownership("live01")

    # The store loses everything, as a Redis restart without persistence does.
    # Worker A is alive and still serving live01.
    shared._leases.clear()

    # A peer starts up and reconciles before A's renewal tick fires.
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    worker_b._backend.list_running.return_value = [info]
    worker_b._reconcile_orphans()

    assert "live01" not in worker_b._warm_pool, "a peer adopted a container whose owner is still alive and serving it"

    # A's renewal tick finally fires: it must still own and keep the sandbox.
    worker_a._renew_owned_leases()

    assert "live01" in worker_a._sandboxes, "a peer's reconcile evicted a live sandbox after the store lost its state"
    assert ("u1", "t1") in worker_a._thread_sandboxes
    sandbox.close.assert_not_called()
    worker_b._backend.destroy.assert_not_called()
    assert shared.owner("live01") == "worker-a"


def test_adoption_grace_expires_so_a_truly_orphaned_container_is_still_adopted():
    """The grace must delay adoption, not disable it.

    A container that stays unowned across a full lease TTL has no live owner —
    a surviving owner republishes within one renewal interval, which is shorter
    than the TTL by construction. Reconciliation must adopt it then, or a crashed
    instance's containers would leak forever.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    shared = _make_shared_ownership_store()
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    ttl = compute_lease_ttl(worker_b._ownership_config)
    info = SandboxInfo(
        sandbox_id="crashed1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-crashed1",
        created_at=time.time() - 50,
    )
    worker_b._backend.list_running.return_value = [info]

    now = time.time()
    with patch.object(aio_mod.time, "time", return_value=now):
        worker_b._reconcile_orphans()
    assert "crashed1" not in worker_b._warm_pool, "adopted a keyless container without waiting out the recovery grace"

    # Nobody republished the lease across a full TTL: the owner is really gone.
    with patch.object(aio_mod.time, "time", return_value=now + ttl + 1):
        worker_b._reconcile_orphans()

    assert "crashed1" in worker_b._warm_pool, "the grace never expired, so a crashed owner's container would leak forever"
    assert shared.owner("crashed1") == "worker-b"


def test_adoption_grace_restarts_when_a_live_owner_republishes():
    """A republished lease must reset the grace, not just pause it.

    Reset and pause only diverge on a **second** lapse. Pause leaves the original
    timestamp behind, so the next time the lease drops the grace is already spent
    and the adopter takes a live container with no wait at all. Stopping at "A
    republished, B defers" would prove nothing — a paused timer defers there too,
    because the container simply reads as owned. So the second lapse is the whole
    test; without it this passes with the reset deleted.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    ttl = compute_lease_ttl(worker_b._ownership_config)
    info = SandboxInfo(
        sandbox_id="live01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-live01",
        created_at=time.time(),
    )
    worker_b._backend.list_running.return_value = [info]

    now = time.time()
    # B starts its grace on a container that currently looks unowned.
    with patch.object(aio_mod.time, "time", return_value=now):
        worker_b._reconcile_orphans()

    # A republishes mid-grace (its renewal tick re-establishing a lapsed lease).
    worker_a._publish_ownership("live01")

    with patch.object(aio_mod.time, "time", return_value=now + ttl + 1):
        worker_b._reconcile_orphans()

    assert "live01" not in worker_b._warm_pool, "a stale grace expired over a lease a live owner had already republished"
    assert shared.owner("live01") == "worker-a"

    # The republish must have cleared B's timer, not merely paused it. A second
    # blip drops the key again: B has to serve a *fresh* full grace, which A's
    # next renewal tick will beat. A paused timer would still hold the original
    # start, so B would adopt A's live container instantly, with no grace at all.
    assert "live01" not in worker_b._unowned_since, "the republish left a stale grace timer behind"

    shared._leases.clear()
    with patch.object(aio_mod.time, "time", return_value=now + ttl + 2):
        worker_b._reconcile_orphans()

    assert "live01" not in worker_b._warm_pool, "a grace timer left over from before the republish expired instantly on the next lapse"


def test_acquire_refuses_a_container_a_peer_is_destroying():
    """#4206's last window: `take()` must not overrun a destroyer's claim.

    Sequence: B's reaper claims X for destroy and starts the (slow) container
    stop; a turn for X's thread routes to A. An unconditional takeover would hand
    A a sandbox that B's stop is about to kill mid-turn.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="dying01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-dying01",
        created_at=time.time(),
    )

    # B decides to reap it and marks the teardown, then its stop is in flight.
    assert worker_b._claim_ownership("dying01", for_destroy=True) is True

    # A's acquire must refuse rather than hand out a doomed container.
    with pytest.raises(SandboxBeingDestroyedError):
        worker_a._register_discovered_sandbox("t1", info, user_id="u1")

    assert "dying01" not in worker_a._sandboxes


def test_teardown_marker_is_held_for_a_stop_that_outlives_the_lease_ttl():
    """The `del:` state must not expire out from under an in-flight stop.

    `test_acquire_refuses_a_container_a_peer_is_destroying` above proves the
    marker refuses a takeover — but never lets it expire. `claim(for_destroy)`
    writes it with the ordinary lease TTL and nothing refreshes it: `renew()`
    only extends `own:` and reports a teardown as LOST, and the destroy paths
    drop the sandbox from the maps the renewal loop iterates. So a container
    stop that outlives the TTL let the marker lapse, a peer's `take()` then
    succeeded against the still-running container, and the stop landed on the
    turn that had just been handed it — the very window `del:` exists to close,
    reopened by its own expiry. The `flock` this replaced could not expire; a
    lease can, so it has to be held on purpose.
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    lease_ttl = 0.15
    shared = _make_shared_ownership_store(ttl_seconds=lease_ttl)
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    # A legal config: the schema bounds only renewal > 0 and multiplier >= 2.
    worker_a._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.05, ttl_multiplier=3.0)
    info = SandboxInfo(
        sandbox_id="doomed1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-doomed1",
        created_at=time.time(),
    )

    stop_entered = threading.Event()
    release_stop = threading.Event()

    def slow_destroy(entry):
        stop_entered.set()
        release_stop.wait(timeout=5)

    worker_a._backend.destroy = MagicMock(side_effect=slow_destroy)
    worker_a._warm_pool["doomed1"] = (info, time.time())

    reaper = threading.Thread(
        target=lambda: worker_a._destroy_warm_entry("doomed1", info, reason="idle_timeout"),
        daemon=True,
    )
    reaper.start()
    try:
        assert stop_entered.wait(timeout=5), "the reaper never reached the backend stop"

        # Across a span several times the lease TTL, a turn for this thread must
        # keep being refused — the container is still being stopped.
        deadline = time.time() + lease_ttl * 4
        while time.time() < deadline:
            assert not worker_b._ownership.take("doomed1"), "a peer took a container whose stop was still in flight"
            time.sleep(0.02)
    finally:
        release_stop.set()
        reaper.join(timeout=5)

    # Once the stop returns the marker is dropped, so the thread can cold-start.
    assert shared.owner("doomed1") is None, "the teardown marker outlived the stop that justified it"
    assert worker_b._ownership.take("doomed1") is True


def test_unhealthy_drop_holds_the_teardown_marker_for_its_stop():
    """The third `del:`-marked stop path needs the same hold as the other two.

    `_drop_unhealthy_sandbox` claims for destroy and then blocks on the backend
    stop exactly like `_destroy_warm_entry` and `destroy()`. Its sibling test
    `test_unhealthy_sandbox_owned_by_peer_is_not_destroyed` pins the *gate* — a
    peer-owned container is not stopped — but never lets the marker **expire**
    during an in-flight stop, which is the same blind spot that hid this window
    on the other two paths. It untracks before claiming, so `_renew_owned_leases`
    cannot see the id either: nothing refreshes the marker unless the stop holds
    it.
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    lease_ttl = 0.15
    shared = _make_shared_ownership_store(ttl_seconds=lease_ttl)
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    worker_a._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.05, ttl_multiplier=3.0)
    info = SandboxInfo(
        sandbox_id="sick01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-sick01",
        created_at=time.time(),
    )

    stop_entered = threading.Event()
    release_stop = threading.Event()

    def slow_destroy(entry):
        stop_entered.set()
        release_stop.wait(timeout=5)

    worker_a._backend.destroy = MagicMock(side_effect=slow_destroy)
    worker_a._sandboxes["sick01"] = MagicMock()
    worker_a._sandbox_infos["sick01"] = info

    dropper = threading.Thread(
        target=lambda: worker_a._drop_unhealthy_sandbox("sick01", "health check failed"),
        daemon=True,
    )
    dropper.start()
    try:
        assert stop_entered.wait(timeout=5), "the drop never reached the backend stop"

        deadline = time.time() + lease_ttl * 4
        while time.time() < deadline:
            assert not worker_b._ownership.take("sick01"), "a peer took a container whose unhealthy-drop stop was still in flight"
            time.sleep(0.02)
    finally:
        release_stop.set()
        dropper.join(timeout=5)

    assert shared.owner("sick01") is None, "the teardown marker outlived the stop that justified it"


def test_destroy_holds_the_teardown_marker_for_its_stop():
    """The third of the three `del:`-marked stops, and the one with no test.

    `_destroy_warm_entry` and `_drop_unhealthy_sandbox` each have a held-marker
    test; `destroy()` is wrapped but nothing pins the wrap, so deleting it goes
    unnoticed. "Every path does X" claims keep leaving exactly one sibling
    untested — this is that sibling.
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    lease_ttl = 0.15
    shared = _make_shared_ownership_store(ttl_seconds=lease_ttl)
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    worker_a._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.05, ttl_multiplier=3.0)
    info = SandboxInfo(
        sandbox_id="doomed3",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-doomed3",
        created_at=time.time(),
    )

    stop_entered = threading.Event()
    release_stop = threading.Event()

    def slow_destroy(entry):
        stop_entered.set()
        release_stop.wait(timeout=5)

    worker_a._backend.destroy = MagicMock(side_effect=slow_destroy)
    worker_a._sandboxes["doomed3"] = MagicMock()
    worker_a._sandbox_infos["doomed3"] = info

    destroyer = threading.Thread(target=lambda: worker_a.destroy("doomed3"), daemon=True)
    destroyer.start()
    try:
        assert stop_entered.wait(timeout=5), "destroy never reached the backend stop"

        deadline = time.time() + lease_ttl * 4
        while time.time() < deadline:
            assert not worker_b._ownership.take("doomed3"), "a peer took a container whose destroy() stop was still in flight"
            time.sleep(0.02)
    finally:
        release_stop.set()
        destroyer.join(timeout=5)

    assert shared.owner("doomed3") is None, "the teardown marker outlived the stop that justified it"


def test_evict_keeps_the_warm_entry_when_the_claim_is_refused():
    """Replica eviction must not pop before it knows the container is going away.

    The sibling of `test_refused_idle_destroy_keeps_the_warm_entry`, which pins
    the same rule for the idle path. Popping first on a refused claim loses the
    container: still running, owned by a peer, and no longer in any of our maps —
    so nothing here would ever reap or reclaim it.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="peer01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-peer01",
        created_at=time.time(),
    )
    worker_a._warm_pool["peer01"] = (info, time.time() - 5)
    # A peer owns it, so A's eviction claim is refused.
    worker_b._publish_ownership("peer01")

    assert worker_a._evict_oldest_warm() is None

    worker_a._backend.destroy.assert_not_called()
    assert "peer01" in worker_a._warm_pool, "evicting popped a container it was refused permission to destroy"
    assert shared.owner("peer01") == "worker-b"


def test_reclaim_drops_a_container_a_peer_is_destroying():
    """The warm-pool half of the acquire-side teardown refusal.

    `test_cached_sandbox_being_destroyed_is_dropped_not_reused` pins the
    in-process reuse path and `test_acquire_refuses_a_container_a_peer_is_destroying`
    the discover path; reclaim is the third and had no test. It must not raise
    (the caller falls through to a cold start) and must not leave the doomed
    container in the warm pool.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="dying02",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-dying02",
        created_at=time.time(),
    )
    worker_a._warm_pool["dying02"] = (info, time.time())
    worker_a._check_tracked_sandbox_alive = MagicMock(return_value=True)

    # B's reaper marks the teardown; its stop is in flight.
    assert worker_b._claim_ownership("dying02", for_destroy=True) is True

    reclaimed = worker_a._reclaim_warm_pool_sandbox("t1", "dying02", user_id="u1")

    assert reclaimed is None, "reclaimed a container a peer is tearing down"
    assert "dying02" not in worker_a._warm_pool
    assert "dying02" not in worker_a._sandboxes
    worker_a._backend.destroy.assert_not_called()


def test_created_sandbox_is_rolled_back_when_a_peer_is_destroying_its_id():
    """Rollback must cover a teardown marker, not just a store outage.

    `test_ownership_rollback_on_create_closes_the_client_it_drops` drives this
    path with `OwnershipBackendError` only. The comment says the teardown case is
    reachable too — a peer that died mid-stop leaves a `del:` marker until its
    TTL lapses — and without rollback the container we just started is leaked as
    an adoptable orphan.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="fresh01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-fresh01",
        created_at=time.time(),
    )
    # A peer's teardown marker is still on this id when we finish creating.
    assert worker_b._claim_ownership("fresh01", for_destroy=True) is True

    with pytest.raises(SandboxBeingDestroyedError):
        worker_a._register_created_sandbox("t1", "fresh01", info, user_id="u1")

    worker_a._backend.destroy.assert_called_once_with(info)
    assert "fresh01" not in worker_a._sandboxes, "a container we could not own was handed out anyway"


def test_shutdown_does_not_stop_a_peers_warm_container():
    """Shutdown is a reap path and must be gated like every other one.

    Nothing drove `shutdown()` with a non-empty warm pool, so a loop that called
    `_backend.destroy` directly — skipping the ownership claim — would go
    unnoticed. On a multi-instance gateway that is #4206 on the shutdown path:
    our exit stops a container a live peer is serving.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    mine = SandboxInfo(sandbox_id="mine01", sandbox_url="http://localhost:8080", container_name="c-mine01", created_at=time.time())
    theirs = SandboxInfo(sandbox_id="peer02", sandbox_url="http://localhost:8081", container_name="c-peer02", created_at=time.time())

    worker_a._warm_pool["mine01"] = (mine, time.time())
    worker_a._publish_ownership("mine01")
    worker_a._warm_pool["peer02"] = (theirs, time.time())
    worker_b._publish_ownership("peer02")  # a live peer owns this one

    worker_a.shutdown()

    destroyed = {call.args[0].sandbox_id for call in worker_a._backend.destroy.call_args_list}
    assert "mine01" in destroyed, "shutdown left our own warm container running"
    assert "peer02" not in destroyed, "shutdown stopped a container a live peer owns"
    assert shared.owner("peer02") == "worker-b"


def test_teardown_heartbeat_stops_when_the_stop_returns():
    """A finite TTL must survive the fix, or a crashed destroyer leaks forever.

    The heartbeat is what holds the exclusion, so it has to die with the stop:
    if it outlived the destroy the marker would be refreshed indefinitely and no
    peer could ever adopt or recreate the container.
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    shared = _make_shared_ownership_store(ttl_seconds=0.15)
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_a._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.05, ttl_multiplier=3.0)
    info = SandboxInfo(
        sandbox_id="doomed2",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-doomed2",
        created_at=time.time(),
    )
    worker_a._warm_pool["doomed2"] = (info, time.time())

    assert worker_a._destroy_warm_entry("doomed2", info, reason="idle_timeout") is True

    # Named rather than counted: threading.active_count() is global and other
    # tests' idle-checker/renewal threads make it noise, so a count comparison
    # here passes straight through a leak.
    assert [t for t in threading.enumerate() if t.name == "sandbox-teardown-lease"] == [], "a teardown heartbeat thread outlived its stop"

    # And nothing keeps refreshing the marker past its TTL.
    time.sleep(0.3)
    assert shared.owner("doomed2") is None


def test_cached_sandbox_being_destroyed_is_dropped_not_reused():
    """The same window on the warm/in-process reuse path falls through cleanly."""
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="dying02",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-dying02",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker_a._sandboxes["dying02"] = sandbox
    worker_a._sandbox_infos["dying02"] = info
    worker_a._thread_sandboxes[("u1", "t1")] = "dying02"
    worker_a._check_tracked_sandbox_alive = MagicMock(return_value=True)

    worker_b._claim_ownership("dying02", for_destroy=True)

    # Returns None (not the id, and not an exception) so acquire cold-starts.
    assert worker_a._reuse_in_process_sandbox("t1", user_id="u1") is None
    assert "dying02" not in worker_a._sandboxes
    worker_a._backend.destroy.assert_not_called()


def test_destroy_claims_before_untracking():
    """A refused claim must not lose the container from every map.

    Untracking first meant a peer-owned container was dropped from `_sandboxes`
    and `_warm_pool` and then not destroyed — still running, and now invisible to
    the instance that had been tracking it.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="peer01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-peer01",
        created_at=time.time(),
    )
    sandbox = MagicMock()
    worker_a._sandboxes["peer01"] = sandbox
    worker_a._sandbox_infos["peer01"] = info
    worker_b._publish_ownership("peer01")

    worker_a.destroy("peer01")

    worker_a._backend.destroy.assert_not_called()
    assert "peer01" in worker_a._sandboxes, "untracked a container it was refused permission to destroy"
    sandbox.close.assert_not_called()


def test_refused_idle_destroy_keeps_the_warm_entry():
    """Popping before deciding loses the container: running, tracked by nobody."""
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    worker_a._config["idle_timeout"] = 60
    info = SandboxInfo(
        sandbox_id="warmpeer",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-warmpeer",
        created_at=time.time(),
    )
    worker_a._warm_pool["warmpeer"] = (info, time.time() - 999)
    worker_b._publish_ownership("warmpeer")

    worker_a._reap_expired_warm(idle_timeout=60)

    worker_a._backend.destroy.assert_not_called()
    assert "warmpeer" in worker_a._warm_pool, "dropped a warm entry it did not actually destroy"


def test_unhealthy_sandbox_owned_by_peer_is_not_destroyed():
    """The one reap path that used to skip the ownership gate entirely."""
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = SandboxInfo(
        sandbox_id="sick01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-sick01",
        created_at=time.time(),
    )
    worker_a._sandboxes["sick01"] = MagicMock()
    worker_a._sandbox_infos["sick01"] = info
    worker_b._publish_ownership("sick01")

    worker_a._drop_unhealthy_sandbox("sick01", "failed health check")

    worker_a._backend.destroy.assert_not_called()
    assert shared.owner("sick01") == "worker-b"


def test_get_does_not_touch_ownership_store():
    """get() is a pure in-memory lookup — it must not do store IO.

    ``ensure_sandbox_initialized_async`` calls ``provider.get()`` directly on the
    event loop, so store IO here would be blocking filesystem or network IO on
    the hot path. Ownership is published on acquire and refreshed by the renewal
    thread instead.
    """
    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    sandbox = MagicMock()
    worker._sandboxes["sb1"] = sandbox
    worker._ownership = MagicMock()

    assert worker.get("sb1") is sandbox

    worker._ownership.take.assert_not_called()
    worker._ownership.claim.assert_not_called()
    worker._ownership.renew.assert_not_called()
    worker._ownership.owner.assert_not_called()


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
