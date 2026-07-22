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
    """View of a shared store as seen by one instance (rebinds ``owner_id``).

    Rebinding is a test-only trick to model two instances against one store, and
    it is only sound while one thread at a time is inside the shared store. The
    heartbeat-hold tests deliberately run a main-thread ``take`` as worker-b
    concurrently with a heartbeat-thread ``claim`` as worker-a, so the rebind has
    to be serialized with the call it applies to: otherwise a ``claim`` can
    execute under worker-b's id, read worker-a's ``del:`` lease as a peer's,
    return ``False``, and kill the heartbeat — after which the marker lapses and
    the next ``take`` succeeds spuriously. The GIL makes that window small, not
    absent, so the tests flake rather than fail.
    """

    # Serializes owner_id rebind + call across every view of one shared store.
    # A class-level lock is deliberate: each worker gets its own view object, and
    # the thing being guarded is the single shared store they both mutate.
    _rebind_lock = threading.Lock()

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
        with self._rebind_lock:
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
    provider._local_teardown = set()
    provider._acquire_epoch = {}
    provider._acquire_epoch_counter = 0
    provider._acquire_inflight = {}
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

    worker._destroy_warm_entry("unknown1", info, reason="idle_timeout", still_reapable=lambda: True)

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


def test_renewal_keeps_the_sandbox_when_lapsed_reclaim_cannot_answer():
    """A store outage after LAPSED is still unknown, not proof of a peer.

    ``renew()`` and the follow-up ``claim()`` are separate store round trips. A
    key can be observed absent and the store can then become unreachable before
    the claim. Renewal must keep the sandbox and retry rather than route the
    claim through the ordinary fail-closed reap helper and evict a live entry.
    """
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError, RenewOutcome

    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    worker._ownership = MagicMock()
    worker._ownership.renew.return_value = RenewOutcome.LAPSED
    worker._ownership.claim.side_effect = OwnershipBackendError("store down after lapsed renew")
    info = _info("live03")
    sandbox = MagicMock()
    worker._sandboxes["live03"] = sandbox
    worker._sandbox_infos["live03"] = info
    worker._thread_sandboxes[("u1", "t1")] = "live03"

    worker._renew_owned_leases()

    worker._ownership.claim.assert_called_once_with("live03")
    assert "live03" in worker._sandboxes, "a failed LAPSED re-claim evicted a live sandbox nobody had taken"
    assert worker._thread_sandboxes[("u1", "t1")] == "live03"
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


def test_renewal_does_not_forget_a_warm_entry_mid_teardown():
    """Renewal must not pop the warm entry retained by an in-flight stop.

    A warm teardown deliberately leaves the entry visible until the backend stop
    succeeds. Its ``del:us`` marker makes ordinary ``renew()`` report LOST, but
    that is local teardown state rather than a peer takeover. If the stop then
    fails, the warm entry must still be present for retry or reclaim.
    """
    worker = _make_provider_for_reconciliation(worker_id="worker-a")
    info = SandboxInfo(
        sandbox_id="warm-stop",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-warm-stop",
        created_at=time.time(),
    )
    worker._warm_pool["warm-stop"] = (info, time.time())
    worker._publish_ownership("warm-stop")

    stop_started = threading.Event()
    let_stop_fail = threading.Event()

    def failing_stop(_entry):
        stop_started.set()
        assert let_stop_fail.wait(timeout=5), "the test never released the backend stop"
        raise RuntimeError("stop failed")

    worker._backend.destroy.side_effect = failing_stop
    result = {}
    reaper = threading.Thread(
        target=lambda: result.update(
            destroyed=worker._destroy_warm_entry(
                "warm-stop",
                info,
                reason="idle_timeout",
                still_reapable=lambda: True,
            )
        ),
        daemon=True,
    )
    reaper.start()
    try:
        assert stop_started.wait(timeout=5), "the warm teardown never reached the backend stop"
        assert "warm-stop" in worker._local_teardown, "precondition: the local teardown reservation is not held"

        worker._renew_owned_leases()

        assert "warm-stop" in worker._warm_pool, "renewal forgot a warm entry while this instance was stopping it"
    finally:
        let_stop_fail.set()
        reaper.join(timeout=5)

    assert not reaper.is_alive(), "the failed warm teardown did not finish"
    assert result.get("destroyed") is False
    assert "warm-stop" in worker._warm_pool, "a failed stop lost the warm entry it promised to retain"


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
        target=lambda: worker_a._destroy_warm_entry("doomed1", info, reason="idle_timeout", still_reapable=lambda: True),
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


def test_destroy_releases_the_teardown_marker_when_the_stop_fails():
    """A failed stop must not strand the id under a `del:` marker.

    `_destroy_warm_entry` releases on both outcomes and says why: the container is
    still up, so leaving it marked would block its thread from ever re-acquiring
    it. `destroy()` had no such guard — a raising backend propagated straight past
    the release, and `take()` stays refused against `del:`, so the thread could not
    acquire until the TTL lapsed. Fails safe rather than fatal (nobody stops a live
    container), but the three stop paths must agree on this.

    The error still propagates: `shutdown()` logs per sandbox off it, so releasing
    must not turn into swallowing.
    """
    shared = _make_shared_ownership_store()
    worker = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    info = SandboxInfo(
        sandbox_id="boom01",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-boom01",
        created_at=time.time(),
    )
    worker._sandboxes["boom01"] = MagicMock()
    worker._sandbox_infos["boom01"] = info
    worker._backend.destroy = MagicMock(side_effect=RuntimeError("docker daemon is unreachable"))

    with pytest.raises(RuntimeError, match="docker daemon is unreachable"):
        worker.destroy("boom01")

    assert shared.owner("boom01") is None, "a failed stop left the id stranded under a teardown marker"
    # The container may well still be running, so its thread must be able to take
    # it back rather than wait out the TTL.
    assert worker._ownership.take("boom01") is True


class _BlockHeartbeatClaim:
    """Store view whose heartbeat *refresh* claim blocks until released.

    ``claim(for_destroy=True)`` is issued twice per teardown: once by the
    caller's gate (``_claim_ownership``) and then repeatedly by the heartbeat.
    This lets the gate through and blocks from the second onward, so a refresh
    can be held in flight while the context manager exits — the interleaving the
    release-ordering fix has to survive.
    """

    def __init__(self, inner):
        self._inner = inner
        self._for_destroy_claims = 0
        self._lock = threading.Lock()
        self.heartbeat_blocked = threading.Event()
        self.unblock = threading.Event()
        self.refresh_completed = threading.Event()

    @property
    def owner_id(self):
        return self._inner.owner_id

    @property
    def supports_cross_process(self):
        return self._inner.supports_cross_process

    def take(self, sandbox_id):
        return self._inner.take(sandbox_id)

    def renew(self, sandbox_id):
        return self._inner.renew(sandbox_id)

    def release(self, sandbox_id):
        return self._inner.release(sandbox_id)

    def owner(self, sandbox_id):
        return self._inner.owner(sandbox_id)

    def close(self):
        pass

    def claim(self, sandbox_id, *, for_destroy: bool = False):
        if for_destroy:
            with self._lock:
                self._for_destroy_claims += 1
                nth = self._for_destroy_claims
            if nth >= 2:  # the heartbeat refresh, not the caller's gate claim
                self.heartbeat_blocked.set()
                self.unblock.wait(timeout=10)
                result = self._inner.claim(sandbox_id, for_destroy=for_destroy)
                # The refresh has now rewritten `del:`. Signalling only after it
                # lands lets the test settle on the final state instead of racing
                # the transient window between a caller-side release and this write.
                self.refresh_completed.set()
                return result
        return self._inner.claim(sandbox_id, for_destroy=for_destroy)


def test_teardown_join_budget_covers_refresh_and_final_release():
    """A normally timing-out refresh plus release must fit before deferral.

    Redis bounds each store operation at five seconds. Context exit can catch
    the heartbeat in a refresh and must then wait for its final release, so the
    join budget needs to exceed both sequential operation bounds rather than
    only one of them.
    """
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    store_operation_timeout_seconds = 5.0

    assert aio_mod.AioSandboxProvider._TEARDOWN_JOIN_TIMEOUT_SECONDS > 2 * store_operation_timeout_seconds


def test_teardown_release_waits_for_the_heartbeat_to_exit():
    """A refresh still in flight when the stop finishes must not resurrect `del:`.

    The `del:` marker's final release is the heartbeat's own last act, not the
    caller's. If the caller cleared it, a refresh `claim` still blocked in the
    store (redis has no infinitely-patient call, but it can be mid-round-trip)
    would land *after* that release and rewrite `del:` on a container whose stop
    already completed — refusing a fresh `take()` (or rolling back a fresh
    create) until the TTL. Owning the release inside the heartbeat sequences it
    strictly after the last refresh. (fancyboi999, PR #4221)
    """
    from deerflow.config.sandbox_config import SandboxOwnershipConfig

    # Long store TTL so nothing lapses via TTL during the test — the only thing
    # that may clear the marker is a real release.
    shared = _make_shared_ownership_store(ttl_seconds=30)
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    worker_a._ownership_config = SandboxOwnershipConfig(renewal_interval_seconds=0.02, ttl_multiplier=2.0)
    # Give up on the join while the heartbeat is still blocked, so the context
    # returns with a refresh genuinely in flight.
    worker_a._TEARDOWN_JOIN_TIMEOUT_SECONDS = 0.1
    blocking = _BlockHeartbeatClaim(worker_a._ownership)
    worker_a._ownership = blocking

    info = SandboxInfo(
        sandbox_id="defer1",
        sandbox_url="http://localhost:8080",
        container_name="deer-flow-sandbox-defer1",
        created_at=time.time(),
    )

    def slow_destroy(entry):
        # Return only once the heartbeat has entered (and blocked in) a refresh,
        # so the context exit runs its bounded join against an in-flight claim.
        assert blocking.heartbeat_blocked.wait(timeout=5), "the heartbeat never issued a refresh claim"

    worker_a._backend.destroy = MagicMock(side_effect=slow_destroy)
    worker_a._warm_pool["defer1"] = (info, time.time())

    reaper = threading.Thread(
        target=lambda: worker_a._destroy_warm_entry("defer1", info, reason="idle_timeout", still_reapable=lambda: True),
        daemon=True,
    )
    reaper.start()
    # The join times out (heartbeat blocked), so the destroy path returns while
    # the refresh is still in flight — exactly where the old caller-side release ran.
    reaper.join(timeout=10)
    assert not reaper.is_alive(), "the destroy path never returned while the heartbeat was blocked"

    # Let the in-flight refresh complete: it rewrites `del:`. Wait until it has
    # actually landed, so the assertion reads the settled state rather than the
    # transient window between a caller-side release and this write. Only a
    # heartbeat-owned release, sequenced after the refresh, can leave the id clean.
    blocking.unblock.set()
    assert blocking.refresh_completed.wait(timeout=5), "the in-flight refresh never completed"

    deadline = time.time() + 5
    while time.time() < deadline and shared.owner("defer1") is not None:
        time.sleep(0.02)
    assert shared.owner("defer1") is None, "a refresh that landed after the release stranded the id under a `del:` marker"
    assert worker_b._ownership.take("defer1") is True


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

    assert worker_a._destroy_warm_entry("doomed2", info, reason="idle_timeout", still_reapable=lambda: True) is True

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


# ── Same-process reap vs. promote ────────────────────────────────────────────
#
# The ownership store excludes peers and nothing else: `claim()` and `take()`
# both succeed against our *own* lease by design. So between this instance's
# reaper threads and its own acquire path there is no store-level exclusion at
# all, and every reaper decides outside `_lock` (a store round trip must not be
# held under the lock that guards every acquire).
#
# Each test below blocks its reaper inside the store round trip — where the
# window actually lives — lets a promote path run, then reads the SETTLED state
# after both threads have finished. The assertion is never on a transient.


def _active_sandbox(provider, sandbox_id, info, *, thread_key=("u", "t1")):
    """Track *info* as an active sandbox on *provider*."""
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

    provider._sandboxes[sandbox_id] = AioSandbox(id=sandbox_id, base_url=info.sandbox_url)
    provider._sandbox_infos[sandbox_id] = info
    provider._last_activity[sandbox_id] = time.time()
    provider._thread_sandboxes[thread_key] = sandbox_id
    provider._backend.is_alive.return_value = True


def _info(sandbox_id, *, created_at=None):
    return SandboxInfo(
        sandbox_id=sandbox_id,
        sandbox_url="http://localhost:8080",
        container_name=f"deer-flow-sandbox-{sandbox_id}",
        created_at=time.time() if created_at is None else created_at,
    )


class _GateOnClaim:
    """Store view that holds the first ``claim`` until released.

    Models the Redis round trip the reaper makes outside ``_lock`` — the window
    a same-process acquire slips through.
    """

    def __init__(self, inner):
        self._inner = inner
        self.entered = threading.Event()
        # Not named `release`: __getattr__ forwards everything else to the real
        # store, and an attribute by that name would shadow `store.release()`.
        self.let_through = threading.Event()
        self._armed = True

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def supports_cross_process(self):
        return True

    def claim(self, sandbox_id, *, for_destroy=False):
        if self._armed:
            self._armed = False
            self.entered.set()
            assert self.let_through.wait(timeout=5), "the test never released the gated claim"
        return self._inner.claim(sandbox_id, for_destroy=for_destroy)


def _run_reap_vs_promote(provider, gate, reap, promote):
    """Run *reap* until it blocks in the store, then *promote*; settle and return."""
    reaper = threading.Thread(target=reap, daemon=True)
    reaper.start()
    try:
        assert gate.entered.wait(timeout=5), "the reaper never reached the ownership store"
        handed_out = promote()
    finally:
        gate.let_through.set()
        reaper.join(timeout=5)
    assert not reaper.is_alive(), "the reaper never finished"
    return handed_out


@pytest.mark.parametrize(
    ("reason", "reap_name"),
    [("replica_enforcement", "_evict_oldest_warm"), ("idle_timeout", "_reap_expired_warm")],
)
def test_warm_reaper_does_not_stop_a_container_this_instance_just_reclaimed(reason, reap_name):
    """Both warm reapers defer the pop, so both need the same reservation.

    The deferred pop is deliberate — popping first loses the container on a
    refused claim — but it leaves the entry visible in `_warm_pool` for the whole
    stop, so `_reclaim_warm_pool_sandbox` can promote it and hand it to an agent
    while the stop is in flight. `claim(for_destroy=True)` does not refuse this:
    the lease is already `own:us`, and a claim only refuses *peers*.

    On `main` neither reaper could hit this — `WarmPoolLifecycleMixin` popped the
    entry under the lock before destroying — so this is a regression these
    overrides introduce, not a pre-existing gap.
    """
    provider = _make_provider_for_reconciliation()
    gate = _GateOnClaim(provider._ownership)
    provider._ownership = gate
    info = _info("warm1")
    # Old enough for the idle reaper; the only entry, so also the eviction pick.
    provider._warm_pool["warm1"] = (info, time.time() - 10_000)
    provider._ownership._inner.take("warm1")

    reap = provider._evict_oldest_warm if reap_name == "_evict_oldest_warm" else lambda: provider._reap_expired_warm(600)
    handed_out = _run_reap_vs_promote(
        provider,
        gate,
        reap,
        lambda: provider._reclaim_warm_pool_sandbox("t1", "warm1", user_id="u"),
    )

    assert handed_out is None, f"{reap_name} let a turn reclaim a container it was stopping ({reason})"
    assert "warm1" not in provider._sandboxes, "the reclaimed sandbox was promoted into active tracking"


def test_idle_destroy_does_not_stop_a_container_this_instance_just_reused():
    """The idle checker's "still idle?" re-check must gate the reservation, not precede it.

    `_cleanup_idle_sandboxes` re-verified idleness under the lock and then called
    `destroy()`, which claims ownership *before* untracking — so the re-check and
    the act are separated by a store round trip. A turn that reuses the sandbox
    in that window gets its container stopped mid-turn.

    The window is pre-existing in shape (main re-checks and destroys the same
    way) but this PR widened it from a few instructions to a network round trip
    by adding the ownership claim, so it is in scope here.
    """
    provider = _make_provider_for_reconciliation()
    gate = _GateOnClaim(provider._ownership)
    provider._ownership = gate
    info = _info("idle1")
    _active_sandbox(provider, "idle1", info)
    provider._last_activity["idle1"] = 0.0  # long idle
    provider._ownership._inner.take("idle1")

    handed_out = _run_reap_vs_promote(
        provider,
        gate,
        lambda: provider._cleanup_idle_sandboxes(600),
        lambda: provider._reuse_in_process_sandbox("t1", user_id="u"),
    )

    assert handed_out is None, "a turn reused a sandbox whose container the idle checker was stopping"


def test_reuse_does_not_return_a_sandbox_reserved_during_its_health_check():
    """A teardown that wins during reuse's unlocked health check must stay won.

    Reuse checks the local teardown reservation before calling ``is_alive``, but
    that backend call runs outside ``_lock``.  The idle reaper can reserve the id
    in that gap and then pause in its ownership claim while reuse publishes a
    fresh ``own:`` lease.  Map membership alone is not a safe final check: the
    reaper deliberately keeps the active entry tracked until its claim succeeds.
    """
    provider = _make_provider_for_reconciliation()
    gate = _GateOnClaim(provider._ownership)
    provider._ownership = gate
    info = _info("idlerace")
    _active_sandbox(provider, "idlerace", info)
    provider._last_activity["idlerace"] = 0.0
    provider._ownership._inner.take("idlerace")

    health_started, let_health_finish = threading.Event(), threading.Event()

    def gated_health(_info):
        health_started.set()
        assert let_health_finish.wait(timeout=5), "the test never released the health check"
        return True

    provider._backend.is_alive.side_effect = gated_health
    result = {}
    acquire = threading.Thread(target=lambda: result.update(id=provider._reuse_in_process_sandbox("t1", user_id="u")), daemon=True)
    reaper = threading.Thread(target=lambda: provider._cleanup_idle_sandboxes(600), daemon=True)

    acquire.start()
    try:
        assert health_started.wait(timeout=5), "reuse never reached its unlocked health check"
        reaper.start()
        assert gate.entered.wait(timeout=5), "the idle reaper never reserved the sandbox and reached its ownership claim"
        assert "idlerace" in provider._local_teardown, "precondition: the idle reaper must hold the local reservation"

        let_health_finish.set()
        acquire.join(timeout=5)
        assert not acquire.is_alive(), "reuse never completed"
        handed_out = result.get("id")
    finally:
        let_health_finish.set()
        gate.let_through.set()
        acquire.join(timeout=5)
        reaper.join(timeout=5)

    assert not reaper.is_alive(), "the idle reaper never finished"
    assert handed_out is None, "reuse returned a sandbox whose local teardown reservation had already won"
    provider._backend.destroy.assert_called_once_with(info)
    assert provider.get("idlerace") is None


def test_discovery_does_not_install_a_sandbox_reserved_while_publishing():
    """Discovery must re-check the local reservation after its store round trip."""
    provider = _make_provider_for_reconciliation()
    info = _info("discoverrace")
    published, let_install = threading.Event(), threading.Event()
    real_publish = provider._publish_ownership

    def gated_publish(sandbox_id):
        result = real_publish(sandbox_id)
        published.set()
        assert let_install.wait(timeout=5), "the test never released discovery after publish"
        return result

    provider._publish_ownership = gated_publish
    result = {}

    def register():
        try:
            result["id"] = provider._register_discovered_sandbox("t1", info, user_id="u")
        except Exception as e:
            result["error"] = e

    registrar = threading.Thread(target=register, daemon=True)
    registrar.start()
    try:
        assert published.wait(timeout=5), "discovery never published ownership"
        assert provider._reserve_local_teardown("discoverrace", lambda: True), "the test could not reserve the discovered sandbox"
        let_install.set()
        registrar.join(timeout=5)
    finally:
        let_install.set()
        registrar.join(timeout=5)
        provider._finish_local_teardown("discoverrace")

    assert not registrar.is_alive(), "discovery never completed"
    assert isinstance(result.get("error"), SandboxBeingDestroyedError)
    assert result.get("id") is None
    assert "discoverrace" not in provider._sandboxes
    assert provider.get("discoverrace") is None


def test_unhealthy_drop_refuses_discovery_of_the_container_it_is_stopping():
    """`_drop_unhealthy_sandbox` untracks first, so discovery is its open window.

    Once the maps are cleared, an acquire misses both caches and falls through to
    backend discovery, which finds the still-running container. `take()` only
    refuses a `del:` lease, and this path's claim has not run yet — so without a
    local reservation the acquire is handed a container this instance is about
    to stop.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("sick1")
    _active_sandbox(provider, "sick1", info)
    provider._ownership.take("sick1")
    # Block at the claim, not at the stop: after the claim the `del:` marker is
    # already published and the store refuses the take by itself, so gating any
    # later would pass without the reservation existing at all. The window that
    # needs the reservation is untrack -> claim, where the lease still says
    # `own:us` and `take()` succeeds.
    gate = _GateOnClaim(provider._ownership)
    provider._ownership = gate

    reaper = threading.Thread(target=lambda: provider._drop_unhealthy_sandbox("sick1", "failed health check"), daemon=True)
    reaper.start()
    try:
        assert gate.entered.wait(timeout=5), "the drop never reached the ownership claim"
        assert provider._ownership._inner.owner("sick1") == provider._owner_id, "precondition: the lease must still read as ours, not a teardown"
        with pytest.raises(SandboxBeingDestroyedError):
            provider._register_discovered_sandbox("t1", info, user_id="u")
    finally:
        gate.let_through.set()
        reaper.join(timeout=5)

    assert "sick1" not in provider._sandboxes


def test_renewal_does_not_drop_a_sandbox_this_instance_re_acquired():
    """A `LOST` verdict is stale the moment an acquire takes the lease back.

    `_renew_owned_leases` calls `renew()` outside `_lock`; between that answer
    and `_forget_lost_sandbox`'s pop, this instance's own acquire can `take()`
    the lease back and hand the sandbox to a turn. The reuse path hands out the
    **same** tracked `AioSandbox`, so an object-identity check would not notice —
    the pop then closes a client mid-turn and the agent's tool calls fail until
    the next turn re-discovers.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = _info("moved1")
    _active_sandbox(worker_a, "moved1", info)
    worker_b._ownership.take("moved1")  # peer holds it -> renew() will report LOST

    entered = threading.Event()
    release = threading.Event()
    original_forget = worker_a._forget_lost_sandbox

    def gated_forget(sandbox_id, **kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return original_forget(sandbox_id, **kwargs)

    worker_a._forget_lost_sandbox = gated_forget

    reaper = threading.Thread(target=worker_a._renew_owned_leases, daemon=True)
    reaper.start()
    try:
        assert entered.wait(timeout=5), "renewal never decided the lease was lost"
        assert worker_a._reuse_in_process_sandbox("t1", user_id="u") == "moved1"
    finally:
        release.set()
        reaper.join(timeout=5)

    assert shared.owner("moved1") == "worker-a", "the acquire should have taken the lease back"
    assert "moved1" in worker_a._sandboxes, "renewal dropped a sandbox this instance owns again"


def test_release_does_not_drop_a_warm_entry_this_instance_re_acquired():
    """`release()` refreshes ownership outside the lock and has the same staleness.

    Sibling of the renewal path: the turn ends, `release()` parks the entry warm
    and refreshes its lease, and the thread's *next* turn can reclaim it while
    that round trip is in flight.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = _info("parked1")
    _active_sandbox(worker_a, "parked1", info)
    worker_b._ownership.take("parked1")  # peer holds it -> refresh reports LOST

    entered = threading.Event()
    release_gate = threading.Event()
    original_forget = worker_a._forget_lost_sandbox

    def gated_forget(sandbox_id, **kwargs):
        entered.set()
        assert release_gate.wait(timeout=5)
        return original_forget(sandbox_id, **kwargs)

    worker_a._forget_lost_sandbox = gated_forget

    reaper = threading.Thread(target=lambda: worker_a.release("parked1"), daemon=True)
    reaper.start()
    try:
        assert entered.wait(timeout=5), "release never decided the lease was lost"
        assert worker_a._reclaim_warm_pool_sandbox("t1", "parked1", user_id="u") == "parked1"
    finally:
        release_gate.set()
        reaper.join(timeout=5)

    assert shared.owner("parked1") == "worker-a"
    assert "parked1" in worker_a._sandboxes, "release dropped a warm entry this instance re-acquired"


def test_discovered_sandbox_client_is_closed_when_ownership_publish_fails():
    """The discover path owns a host-side client even though it owns no container.

    "Nothing to roll back" is true of the container — we did not create it — but
    not of the `AioSandbox` HTTP client constructed before the publish. The
    sibling create path already closes it on the same failure.
    """
    from deerflow.community.aio_sandbox.ownership import OwnershipBackendError

    provider = _make_provider_for_reconciliation()
    provider._ownership = MagicMock()
    provider._ownership.take.side_effect = OwnershipBackendError("store down")

    created = []
    aio_mod = importlib.import_module("deerflow.community.aio_sandbox.aio_sandbox_provider")
    real_sandbox_cls = aio_mod.AioSandbox

    def tracking_sandbox(**kwargs):
        sandbox = real_sandbox_cls(**kwargs)
        sandbox.close = MagicMock(side_effect=sandbox.close)
        created.append(sandbox)
        return sandbox

    with patch.object(aio_mod, "AioSandbox", side_effect=tracking_sandbox):
        with pytest.raises(OwnershipBackendError):
            provider._register_discovered_sandbox("t1", _info("found1"), user_id="u")

    assert len(created) == 1, "the discover path should have constructed exactly one client"
    created[0].close.assert_called_once()
    assert "found1" not in provider._sandboxes


def test_idle_destroy_skips_a_sandbox_re_acquired_after_the_idle_snapshot():
    """The idle predicate must read live activity, not just gate the reservation.

    `_cleanup_idle_sandboxes` snapshots idle candidates under the lock and acts
    on them one at a time; a turn landing in between makes the snapshot wrong.
    The reservation alone does not catch this — nothing is being torn down yet —
    so the "still idle?" check has to travel with it as a live predicate.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("idle2")
    _active_sandbox(provider, "idle2", info)
    provider._last_activity["idle2"] = 0.0
    provider._ownership.take("idle2")

    real_destroy_tracked = provider._destroy_tracked

    def turn_lands_first(sandbox_id, **kwargs):
        # A turn arrives between the idle snapshot and the reservation.
        provider._last_activity[sandbox_id] = time.time()
        return real_destroy_tracked(sandbox_id, **kwargs)

    provider._destroy_tracked = turn_lands_first
    provider._cleanup_idle_sandboxes(600)

    provider._backend.destroy.assert_not_called()
    assert "idle2" in provider._sandboxes, "idle cleanup destroyed a sandbox that was re-acquired after the snapshot"


# ── Guard visibility vs. the transition it guards ────────────────────────────
#
# A guard must become visible no later than the state transition it guards. The
# epoch alone cannot satisfy that for `take()`: the takeover is durable before
# `take()` returns (redis has committed the SET while the reply is in flight),
# and the epoch can only be written after it returns. So the acquire path
# publishes an *intent* mark before the round trip, and the epoch covers the
# other half — "an acquire completed since you decided".


class _TakeCommitsThenPauses:
    """Store view whose ``take`` performs the real write, then pauses.

    Not an artificial injection point: on redis the server has committed the
    takeover while the reply is still travelling back, so `own:us` is externally
    visible before the caller resumes.
    """

    def __init__(self, inner):
        self._inner = inner
        self.committed = threading.Event()
        self.let_return = threading.Event()
        self._armed = True

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def supports_cross_process(self):
        return True

    def take(self, sandbox_id):
        result = self._inner.take(sandbox_id)
        if self._armed:
            self._armed = False
            self.committed.set()
            assert self.let_return.wait(timeout=5), "the test never released take()"
        return result


def _hold_forget(provider):
    """Park *provider*'s next `_forget_lost_sandbox` and return its two events."""
    ready, release = threading.Event(), threading.Event()
    original = provider._forget_lost_sandbox

    def gated(sandbox_id, **kwargs):
        ready.set()
        assert release.wait(timeout=5), "the test never released the forget"
        return original(sandbox_id, **kwargs)

    provider._forget_lost_sandbox = gated
    return ready, release


def test_renewal_does_not_drop_a_sandbox_whose_takeover_is_mid_flight():
    """The epoch is written after `take()` returns; the takeover is durable before it.

    In that interval the store already says the container is ours while the
    epoch still reads as it did when the renewal decided `LOST`. Without a guard
    established *before* the round trip, the stale forget walks through, drops
    the maps and closes the client — and the acquire path then returns an id the
    provider no longer tracks, so `get()` answers `None` for the rest of the turn.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = _info("midtake")
    _active_sandbox(worker_a, "midtake", info)
    worker_b._ownership.take("midtake")  # peer holds it -> renew() reports LOST

    ready, release = _hold_forget(worker_a)
    renewal = threading.Thread(target=worker_a._renew_owned_leases, daemon=True)
    renewal.start()
    assert ready.wait(timeout=5), "renewal never decided the lease was lost"

    gate = _TakeCommitsThenPauses(worker_a._ownership)
    worker_a._ownership = gate
    result = {}
    acquire = threading.Thread(target=lambda: result.update(id=worker_a._reuse_in_process_sandbox("t1", user_id="u")), daemon=True)
    acquire.start()
    try:
        assert gate.committed.wait(timeout=5), "take() never committed the takeover"
        assert shared.owner("midtake") == "worker-a", "precondition: the takeover must already be durable"
        release.set()
        renewal.join(timeout=5)
    finally:
        gate.let_return.set()
        acquire.join(timeout=5)

    assert result.get("id") == "midtake"
    assert "midtake" in worker_a._sandboxes, "a stale LOST dropped a sandbox whose takeover was already committed"
    assert worker_a.get("midtake") is not None, "acquire returned an id whose get() is None"


def test_reuse_falls_through_when_its_entry_is_dropped_while_publishing():
    """Before the intent mark is set, a `LOST` forget is both current and correct.

    Distinct from the mid-flight window: here nothing is wrong with the forget —
    the peer really does hold the lease and no acquire has taken it back yet, so
    the epoch matches and no intent is registered. The bug is on the other side:
    reuse decided to hand out a tracked entry, and must not return that decision
    once the entry is gone. Falling through re-discovers and builds a fresh
    client; returning the id would hand back a sandbox whose `get()` is `None`.
    """
    shared = _make_shared_ownership_store()
    worker_a = _make_provider_for_reconciliation(worker_id="worker-a", store=shared)
    worker_b = _make_provider_for_reconciliation(worker_id="worker-b", store=shared)
    info = _info("prepub")
    _active_sandbox(worker_a, "prepub", info)
    worker_b._ownership.take("prepub")

    ready, release = _hold_forget(worker_a)
    renewal = threading.Thread(target=worker_a._renew_owned_leases, daemon=True)
    renewal.start()
    assert ready.wait(timeout=5), "renewal never decided the lease was lost"

    # Park reuse in the gap between its map re-check and the intent mark.
    at_publish, let_publish = threading.Event(), threading.Event()
    real_publish = worker_a._publish_ownership

    def gated_publish(sandbox_id):
        at_publish.set()
        assert let_publish.wait(timeout=5)
        return real_publish(sandbox_id)

    worker_a._publish_ownership = gated_publish
    result = {}
    acquire = threading.Thread(target=lambda: result.update(id=worker_a._reuse_in_process_sandbox("t1", user_id="u")), daemon=True)
    acquire.start()
    try:
        assert at_publish.wait(timeout=5), "reuse never reached the ownership publish"
        release.set()
        renewal.join(timeout=5)
    finally:
        let_publish.set()
        acquire.join(timeout=5)

    assert result.get("id") is None, "reuse returned an id it no longer tracks"


def test_reconcile_does_not_adopt_a_container_this_instance_is_tearing_down():
    """Adoption is a promote, so it needs the same reservation check as the rest.

    `_drop_unhealthy_sandbox` untracks before it claims, so in that window the
    container is running, untracked, and still carries our own `own:` lease —
    exactly the shape this loop adopts. Neither guard in the loop excludes it:
    the claim succeeds because the lease is ours, and on the `memory` store the
    recovery grace is skipped outright (`supports_cross_process = False`), so
    nothing stands in the way at all. Adopting parks a container in the warm pool
    moments before its stop lands, leaving a dead entry for the next reclaim.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("reap1")
    _active_sandbox(provider, "reap1", info)
    provider._ownership.take("reap1")
    provider._backend.list_running.return_value = [info]

    at_claim, let_claim = threading.Event(), threading.Event()
    real_claim = provider._claim_ownership

    def gated_claim(sandbox_id, *, for_destroy=False):
        if for_destroy:
            at_claim.set()
            assert let_claim.wait(timeout=5)
        return real_claim(sandbox_id, for_destroy=for_destroy)

    provider._claim_ownership = gated_claim
    reaper = threading.Thread(target=lambda: provider._drop_unhealthy_sandbox("reap1", "failed health check"), daemon=True)
    reaper.start()
    try:
        assert at_claim.wait(timeout=5), "the drop never reached its claim"
        # Untracked, still running, and the `del:` marker is not written yet.
        provider._reconcile_orphans()
        assert "reap1" not in provider._warm_pool, "reconcile adopted a container this instance is stopping"
    finally:
        let_claim.set()
        reaper.join(timeout=5)


def test_teardown_reservation_is_cleared_once_the_stop_returns():
    """The reservation must not outlive the stop it guards.

    Release ordering is the mirror of acquire ordering: the heartbeat drops the
    `del:` lease before `_finish_local_teardown` clears the local mark. That
    direction is the safe one — the mark only refuses *our* promotes, and the
    container is gone anyway — but a mark left behind would keep refusing this
    thread's cold-start until the process restarts.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("cleared")
    provider._warm_pool["cleared"] = (info, time.time() - 10_000)
    provider._ownership.take("cleared")

    assert provider._destroy_warm_entry("cleared", info, reason="idle_timeout", still_reapable=lambda: True) is True
    assert provider._local_teardown == set(), "a teardown reservation outlived the stop it guarded"
    assert provider._acquire_inflight == {}, "an acquire intent mark leaked"


def test_reclaim_does_not_hand_out_a_container_a_reaper_is_stopping():
    """Reclaim's reservation check runs before its round trip, so it must run again.

    A reaper can reserve *after* that first check — the warm entry is still
    there, since the pop is deferred so a refused stop cannot lose the container
    — and then claim `del:`, which succeeds because reclaim's own `take()` just
    made the lease ours. With the reaper parked inside the container stop, the
    entry is still in `_warm_pool` and still reserved, so only the re-check
    stands between reclaim and installing a client for a dying container.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("handout")
    provider._warm_pool["handout"] = (info, time.time() - 10_000)
    provider._ownership.take("handout")

    # Park reclaim between its `take()` and its install.
    published, let_install = threading.Event(), threading.Event()
    real_publish = provider._publish_ownership

    def gated_publish(sandbox_id):
        result = real_publish(sandbox_id)
        published.set()
        assert let_install.wait(timeout=5)
        return result

    provider._publish_ownership = gated_publish
    out = {}
    reclaim = threading.Thread(target=lambda: out.update(id=provider._reclaim_warm_pool_sandbox("t1", "handout", user_id="u")), daemon=True)
    reclaim.start()
    assert published.wait(timeout=5), "reclaim never published ownership"

    # Reaper reserves and enters the stop, then parks there -- so when reclaim
    # resumes the entry is still in `_warm_pool` and the reservation is held.
    in_stop, let_stop_finish = threading.Event(), threading.Event()
    provider._backend.destroy = MagicMock(side_effect=lambda entry: (in_stop.set(), let_stop_finish.wait(timeout=5)))
    reaper = threading.Thread(target=lambda: provider._reap_expired_warm(600), daemon=True)
    reaper.start()
    try:
        assert in_stop.wait(timeout=5), "the reaper never reached the container stop"
        assert "handout" in provider._warm_pool, "precondition: the pop must still be pending"
        let_install.set()
        reclaim.join(timeout=5)
    finally:
        let_stop_finish.set()
        reaper.join(timeout=5)

    assert out.get("id") is None, "reclaim handed out a container a reaper was stopping"
    assert "handout" not in provider._sandboxes


def test_warm_entry_is_removed_before_its_teardown_reservation_is_released():
    """Removal must happen under the reservation, not after it.

    The reservation is what keeps promotes off the entry. If it is released when
    the stop returns and the entry is removed afterwards, there is a gap in which
    the container is already stopped, the entry is still in `_warm_pool`, and
    nothing marks it — so a reclaim in that gap re-checks the reservation, finds
    it clear, and hands out a dead container. Ordering is the guarantee, so the
    assertion is on the ordering rather than on one interleaving.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("ordered")
    provider._warm_pool["ordered"] = (info, time.time() - 10_000)
    provider._ownership.take("ordered")

    observed = {}
    real_finish = provider._finish_local_teardown

    def spy(sandbox_id):
        observed["warm_at_release"] = sandbox_id in provider._warm_pool
        return real_finish(sandbox_id)

    provider._finish_local_teardown = spy
    assert provider._destroy_warm_entry("ordered", info, reason="idle_timeout", still_reapable=lambda: True) is True

    assert observed["warm_at_release"] is False, "the warm entry outlived the reservation that protected it"
    assert "ordered" not in provider._warm_pool


def test_reclaim_short_circuits_a_reserved_entry_without_touching_the_backend():
    """The pre-round-trip reservation check earns its keep as an early-out.

    Correctness is covered by the re-check after the publish, so this first check
    is not what makes reclaim safe. What it does is refuse a doomed entry before
    spending a container health check and an ownership round trip on it, so that
    is what this pins — otherwise the clause is unanchored and a later edit can
    drop it silently.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("shortcut")
    provider._warm_pool["shortcut"] = (info, time.time())
    provider._ownership = MagicMock(wraps=provider._ownership)
    with provider._lock:
        provider._local_teardown.add("shortcut")

    assert provider._reclaim_warm_pool_sandbox("t1", "shortcut", user_id="u") is None
    provider._backend.is_alive.assert_not_called()
    provider._ownership.take.assert_not_called()


def test_forget_without_an_epoch_still_refuses_an_id_being_acquired():
    """ "No epoch supplied" must not read as "no guard at all".

    The epoch-less callers are the two `SandboxBeingDestroyedError` handlers,
    which cannot collide with a publish for the same id today. This pins the
    primitive's contract rather than that reachability argument: an id whose
    acquire is mid-publish is never dropped, whoever asks.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("guarded")
    _active_sandbox(provider, "guarded", info)
    with provider._lock:
        provider._acquire_inflight["guarded"] = 1

    provider._forget_lost_sandbox("guarded")

    assert "guarded" in provider._sandboxes, "an id being acquired was dropped by an epoch-less forget"


@pytest.mark.parametrize("register", ["discovered", "created"])
def test_registering_a_sandbox_clears_any_stale_warm_entry(register):
    """Active and warm are exclusive states, and only register can violate it.

    Reconciliation adopts an untracked-but-running container into the warm pool,
    and on the `memory` store that happens on sight — `_adoptable_after_grace`
    short-circuits when `supports_cross_process` is False, so an id carrying this
    process's *own* lease is treated as adoptable. That is reachable during the
    publish → track window of either register path, which this branch introduced
    (on `main` the track was a single locked insert with nothing before it).

    Leaving both entries gives one container two reapers: `_reap_expired_warm`
    judges it by the warm timestamp and never consults `_last_activity`, so it
    stops a container an agent is using while `_sandboxes` still hands out its
    client — #4206's symptom on the default backend.

    The exclusivity is what actually fixes this, so it is asserted directly and
    on both register paths rather than through one interleaving.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("stale")
    provider._warm_pool["stale"] = (info, time.time())

    if register == "discovered":
        provider._register_discovered_sandbox("t1", info, user_id="u")
    else:
        provider._register_created_sandbox("t1", "stale", info, user_id="u")

    assert "stale" in provider._sandboxes
    assert "stale" not in provider._warm_pool, "a stale warm entry survived the id becoming active"


def test_a_container_adopted_during_register_is_not_reaped_from_the_warm_pool():
    """The end-to-end harm the exclusivity rule removes.

    Reconcile runs inside the register's publish → track window and adopts the
    container; once tracking lands, the warm entry must be gone, otherwise warm
    expiry stops the container this turn is holding.
    """
    provider = _make_provider_for_reconciliation()
    info = _info("adopted")
    provider._backend.list_running.return_value = [info]
    provider._backend.is_alive.return_value = True

    at_gap, go = threading.Event(), threading.Event()
    real_publish = provider._publish_ownership

    def gated_publish(sandbox_id):
        result = real_publish(sandbox_id)
        at_gap.set()
        assert go.wait(timeout=5)
        return result

    provider._publish_ownership = gated_publish
    out = {}
    registrar = threading.Thread(target=lambda: out.update(id=provider._register_discovered_sandbox("t1", info, user_id="u")), daemon=True)
    registrar.start()
    try:
        assert at_gap.wait(timeout=5), "register never reached the publish → track window"
        provider._reconcile_orphans()
    finally:
        go.set()
        registrar.join(timeout=5)

    assert out.get("id") == "adopted"
    assert "adopted" not in provider._warm_pool, "the adopted entry survived, giving the container two reapers"

    time.sleep(0.02)
    provider._reap_expired_warm(0.01)
    provider._backend.destroy.assert_not_called()
    assert provider.get("adopted") is not None, "warm expiry stopped a container this turn is holding"
