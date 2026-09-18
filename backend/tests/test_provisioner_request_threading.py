"""Regression tests for provisioner request-path K8s IO threading."""

from __future__ import annotations

import asyncio
import inspect
import json
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import requests
from blockbuster import BlockBuster
from kubernetes.client.rest import ApiException


def test_provisioner_thread_id_pattern_matches_gateway_contract(provisioner_module) -> None:
    from deerflow.utils.thread_id import THREAD_ID_PATTERN

    assert provisioner_module.SAFE_THREAD_ID_PATTERN == THREAD_ID_PATTERN


@pytest.mark.parametrize("thread_id", ["", "thread.with.dot", "../escape", "x" * 65])
def test_provisioner_rejects_noncanonical_thread_ids(provisioner_module, thread_id: str) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-validation",
            thread_id=thread_id,
        )


@pytest.mark.parametrize("thread_id", ["a", "A1_b-2", "x" * 64])
def test_provisioner_accepts_canonical_thread_ids(provisioner_module, thread_id: str) -> None:
    request = provisioner_module.CreateSandboxRequest(
        sandbox_id="sandbox-validation",
        thread_id=thread_id,
    )

    assert request.thread_id == thread_id


def test_provisioner_request_defaults_skills_container_path(provisioner_module) -> None:
    request = provisioner_module.CreateSandboxRequest(
        sandbox_id="sandbox-validation",
    )

    assert request.skills_container_path == "/mnt/skills"
    assert request.max_shell_sessions is None


def test_provisioner_threads_shell_capacity_into_sandbox_pod(
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(
        event_loop_thread_id=-1,
        ready_after_service_reads={"sandbox-capacity": 1},
    )
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)

    response = provisioner_module.create_sandbox(
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-capacity",
            thread_id="thread-1",
            max_shell_sessions=13,
        )
    )

    assert response.status == "Running"
    pod = fake_core_v1.created_pod_specs["sandbox-capacity"]
    env = {item.name: item.value for item in (pod.spec.containers[0].env or [])}
    assert env["MAX_SHELL_SESSIONS"] == "13"


def test_provisioner_rejects_insufficient_capacity_without_replacing_existing_pod(
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(event_loop_thread_id=-1)
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)
    with pytest.raises(provisioner_module.HTTPException) as error:
        provisioner_module.create_sandbox(
            provisioner_module.CreateSandboxRequest(
                sandbox_id="sandbox-existing",
                thread_id="thread-1",
                max_shell_sessions=13,
            )
        )

    assert error.value.status_code == 409
    assert "capacity" in error.value.detail
    assert fake_core_v1.created_pods == []
    assert fake_core_v1.pod_shell_capacities["sandbox-existing"] == 10
    assert "sandbox-existing" in fake_core_v1.service_sandboxes


def test_capacity_replacement_recovers_when_service_outlives_old_pod(monkeypatch, provisioner_module):
    """A create racing asynchronous deletion can leave a Service without a Pod."""
    core = _RecordingCoreV1(event_loop_thread_id=-1)
    core.pod_shell_capacities.pop("sandbox-existing")
    monkeypatch.setattr(provisioner_module, "core_v1", core)

    def existing_service(*_args):
        raise ApiException(status=409)

    monkeypatch.setattr(core, "create_namespaced_service", existing_service)
    result = provisioner_module.create_sandbox(provisioner_module.CreateSandboxRequest(sandbox_id="sandbox-existing", thread_id="thread-a", max_shell_sessions=13))
    assert result.max_shell_sessions == 13
    assert core.created_pods == ["sandbox-existing"]
    assert "sandbox-existing" in core.service_sandboxes


@pytest.mark.parametrize("failure", [ApiException(status=403), ApiException(status=503), RuntimeError("invalid persisted capacity")])
def test_capacity_read_failure_does_not_authorize_creation(monkeypatch, provisioner_module, failure):
    core = _RecordingCoreV1(event_loop_thread_id=-1)
    monkeypatch.setattr(provisioner_module, "core_v1", core)
    monkeypatch.setattr(provisioner_module, "_get_pod_shell_capacity", MagicMock(side_effect=failure))

    with pytest.raises(provisioner_module.HTTPException) as error:
        provisioner_module.create_sandbox(provisioner_module.CreateSandboxRequest(sandbox_id="sandbox-existing", max_shell_sessions=13))

    assert error.value.status_code == 500
    assert core.created_pods == []
    assert core.pod_shell_capacities["sandbox-existing"] == 10
    assert "sandbox-existing" in core.service_sandboxes


def test_list_sandboxes_skips_invalid_capacity_metadata(
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(event_loop_thread_id=-1)
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)

    def invalid_capacity(_sandbox_id: str) -> int:
        raise RuntimeError("invalid capacity")

    monkeypatch.setattr(
        provisioner_module,
        "_get_pod_shell_capacity",
        invalid_capacity,
    )

    response = provisioner_module.list_sandboxes()

    assert response == {"sandboxes": [], "count": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("async_acquire", [False, True], ids=["sync", "async"])
async def test_capacity_upgrade_preserves_peer_pod_after_discovery_error(monkeypatch, tmp_path, provisioner_module, async_acquire):
    """Discovery failure must not bypass ownership; a later safe retry replaces."""
    from test_sandbox_orphan_reconciliation import _make_provider_for_reconciliation, _make_shared_ownership_store

    from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_mod
    from deerflow.community.aio_sandbox import remote_backend as remote_mod
    from deerflow.community.aio_sandbox.ownership import compute_lease_ttl
    from deerflow.config.paths import Paths

    shared = _make_shared_ownership_store()
    old = _make_provider_for_reconciliation(worker_id="old-gateway", store=shared)
    new = _make_provider_for_reconciliation(worker_id="new-gateway", store=shared)
    sid = "sandbox-existing"
    old._publish_ownership(sid)
    new._backend = remote_mod.RemoteSandboxBackend("http://provisioner:8002", max_shell_sessions=13)
    core = _RecordingCoreV1(event_loop_thread_id=threading.get_ident())
    monkeypatch.setattr(provisioner_module, "core_v1", core)
    deleted_under_lease = []
    discovery_failed = False

    def response(status, payload):
        result = requests.Response()
        result.status_code = status
        result._content = json.dumps(payload).encode()
        return result

    def get(_url, **_kwargs):
        nonlocal discovery_failed
        if not discovery_failed:
            discovery_failed = True
            return response(503, {"detail": "temporarily unavailable"})
        return response(200, provisioner_module.get_sandbox(sid).model_dump())

    def post(_url, *, json, **_kwargs):
        try:
            result = provisioner_module.create_sandbox(provisioner_module.CreateSandboxRequest(**json))
        except provisioner_module.HTTPException as exc:
            return response(exc.status_code, {"detail": exc.detail})
        return response(200, result.model_dump())

    def delete(_url, **_kwargs):
        deleted_under_lease.append((shared.owner(sid), old._ownership.claim(sid)))
        return response(200, provisioner_module.destroy_sandbox(sid))

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "delete", delete)
    monkeypatch.setattr(remote_mod, "user_should_see_legacy_skills", lambda _uid: False)
    monkeypatch.setattr(provider_mod, "get_paths", lambda: Paths(base_dir=tmp_path))
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", lambda *_a, **_kw: True)
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready_async", AsyncMock(return_value=True))
    monkeypatch.setattr(provider_mod, "AioSandbox", MagicMock())
    monkeypatch.setattr(new, "_get_extra_mounts", lambda *_a, **_kw: [])
    monkeypatch.setattr(new, "_lark_integration_active", lambda *_a: False)
    monkeypatch.setattr(new, "_lark_broker_active", lambda *_a: False)

    async def acquire():
        if async_acquire:
            return await new._discover_or_create_with_lock_async("thread-a", sid, user_id="user-a")
        return await asyncio.to_thread(new._discover_or_create_with_lock, "thread-a", sid, user_id="user-a")

    try:
        with pytest.raises(RuntimeError, match="409"):
            await acquire()
        assert core.pod_shell_capacities[sid] == 10
        assert core.created_pods == []
        assert sid in core.service_sandboxes
        assert shared.owner(sid) == "old-gateway"

        with pytest.raises(provider_mod.SandboxPolicyReplacementDeferredError):
            await acquire()
        old._ownership.release(sid)
        with pytest.raises(provider_mod.SandboxPolicyReplacementDeferredError):
            await acquire()
        assert deleted_under_lease == []

        new._unowned_since[sid] = time.time() - compute_lease_ttl(new._ownership_config) - 1
        assert await acquire() == sid
        assert deleted_under_lease == [("new-gateway", False)]
        assert core.created_pods == [sid]
        assert core.pod_shell_capacities[sid] == 13
        assert shared.owner(sid) == "new-gateway"
    finally:
        old._acquire_serializer.close()
        new._acquire_serializer.close()


class _RecordingCoreV1:
    def __init__(
        self,
        *,
        event_loop_thread_id: int,
        ready_after_service_reads: dict[str, int] | None = None,
        service_read_failures: dict[str, list[int]] | None = None,
    ) -> None:
        self.event_loop_thread_id = event_loop_thread_id
        self.thread_ids: list[int] = []
        self.service_sandboxes: set[str] = {"sandbox-existing"}
        self.pod_shell_capacities: dict[str, int] = {
            "sandbox-existing": 10,
            "sandbox-listed": 10,
        }
        self.ready_after_service_reads = ready_after_service_reads or {}
        self.service_read_failures = service_read_failures or {}
        self.service_read_counts: dict[str, int] = {}
        self.created_pods: list[str] = []
        self.created_pod_specs: dict[str, object] = {}
        self.created_services: list[str] = []

    def _record_k8s_call(self) -> None:
        thread_id = threading.get_ident()
        self.thread_ids.append(thread_id)
        time.sleep(0)
        if thread_id == self.event_loop_thread_id:
            raise AssertionError("Kubernetes client call ran on the ASGI event-loop thread")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise AssertionError("Kubernetes client call ran inside an asyncio event loop")

    def read_namespaced_service(self, _name: str, _namespace: str):
        self._record_k8s_call()
        sandbox_id = _sandbox_id_from_service_name(_name)
        self.service_read_counts[sandbox_id] = self.service_read_counts.get(sandbox_id, 0) + 1
        failures = self.service_read_failures.get(sandbox_id) or []
        if failures:
            raise ApiException(status=failures.pop(0))
        ready_after_reads = self.ready_after_service_reads.get(sandbox_id, 1)
        if sandbox_id not in self.service_sandboxes or self.service_read_counts[sandbox_id] < ready_after_reads:
            raise ApiException(status=404)
        return _node_port_service(sandbox_id)

    def read_namespaced_pod(self, _name: str, _namespace: str):
        self._record_k8s_call()
        sandbox_id = _name[len("sandbox-") :]
        capacity = self.pod_shell_capacities.get(sandbox_id)
        if capacity is None:
            raise ApiException(status=404)
        return SimpleNamespace(
            status=SimpleNamespace(phase="Running"),
            spec=SimpleNamespace(
                containers=[
                    SimpleNamespace(
                        name="sandbox",
                        env=[SimpleNamespace(name="MAX_SHELL_SESSIONS", value=str(capacity))],
                    )
                ]
            ),
        )

    def create_namespaced_pod(self, _namespace: str, pod) -> None:
        self._record_k8s_call()
        sandbox_id = pod.metadata.labels["sandbox-id"]
        self.created_pods.append(sandbox_id)
        self.created_pod_specs[sandbox_id] = pod
        env = {item.name: item.value for item in (pod.spec.containers[0].env or [])}
        self.pod_shell_capacities[sandbox_id] = int(env.get("MAX_SHELL_SESSIONS", "10"))

    def create_namespaced_service(self, _namespace: str, service) -> None:
        self._record_k8s_call()
        sandbox_id = service.metadata.labels["sandbox-id"]
        self.created_services.append(sandbox_id)
        self.service_sandboxes.add(sandbox_id)

    def delete_namespaced_service(self, _name: str, _namespace: str) -> None:
        self._record_k8s_call()
        self.service_sandboxes.discard(_sandbox_id_from_service_name(_name))

    def delete_namespaced_pod(self, _name: str, _namespace: str) -> None:
        self._record_k8s_call()
        self.pod_shell_capacities.pop(_name[len("sandbox-") :], None)

    def list_namespaced_service(self, _namespace: str, *, label_selector: str):
        self._record_k8s_call()
        assert label_selector == "app=deer-flow-sandbox"
        return SimpleNamespace(items=[_node_port_service("sandbox-listed")])


def _node_port_service(sandbox_id: str):
    return SimpleNamespace(
        metadata=SimpleNamespace(labels={"sandbox-id": sandbox_id}),
        spec=SimpleNamespace(ports=[SimpleNamespace(name="http", port=8080, node_port=32123)]),
    )


def _sandbox_id_from_service_name(name: str) -> str:
    assert name.startswith("sandbox-")
    assert name.endswith("-svc")
    return name[len("sandbox-") : -len("-svc")]


@contextmanager
def _detect_provisioner_blocking_io(provisioner_module):
    detector = BlockBuster(scanned_modules=[provisioner_module.__name__])
    detector.activate()
    try:
        yield
    finally:
        detector.deactivate()


def test_sandbox_business_route_handlers_are_sync(provisioner_module) -> None:
    """FastAPI runs sync handlers in its worker pool, away from the event loop."""
    for handler in (
        provisioner_module.create_sandbox,
        provisioner_module.destroy_sandbox,
        provisioner_module.get_sandbox,
        provisioner_module.list_sandboxes,
    ):
        assert not inspect.iscoroutinefunction(handler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "json_body", "expected_created_sandbox"),
    [
        ("POST", "/api/sandboxes", {"sandbox_id": "sandbox-existing", "thread_id": "thread-1", "user_id": "user-1"}, None),
        ("POST", "/api/sandboxes", {"sandbox_id": "sandbox-new", "thread_id": "thread-1", "user_id": "user-1"}, "sandbox-new"),
        ("DELETE", "/api/sandboxes/sandbox-existing", None, None),
        ("GET", "/api/sandboxes/sandbox-existing", None, None),
        ("GET", "/api/sandboxes", None, None),
    ],
    ids=["create-existing", "create-new", "destroy", "get", "list"],
)
async def test_sandbox_business_routes_run_k8s_client_off_event_loop_thread(
    method: str,
    path: str,
    json_body: dict[str, str] | None,
    expected_created_sandbox: str | None,
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(
        event_loop_thread_id=threading.get_ident(),
        ready_after_service_reads={"sandbox-new": 3},
    )
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)
    monkeypatch.setattr(provisioner_module, "PROVISIONER_API_KEY", "test-secret")

    with _detect_provisioner_blocking_io(provisioner_module):
        transport = httpx.ASGITransport(app=provisioner_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            headers = {"X-API-Key": "test-secret"}
            if json_body is None:
                response = await client.request(method, path, headers=headers)
            else:
                response = await client.request(method, path, json=json_body, headers=headers)

    assert response.status_code == 200
    assert fake_core_v1.thread_ids
    if expected_created_sandbox is not None:
        assert fake_core_v1.created_pods == [expected_created_sandbox]
        assert fake_core_v1.created_services == [expected_created_sandbox]


@pytest.mark.parametrize(
    ("include_legacy_skills", "expected_mount_names"),
    [
        (
            False,
            ["skills-public", "skills-custom", "skills-legacy", "user-data"],
        ),
        (
            True,
            ["skills-public", "skills-custom", "skills-legacy", "user-data"],
        ),
    ],
    ids=["without-legacy", "with-legacy"],
)
def test_create_sandbox_route_builds_expected_skills_mount_layout(
    include_legacy_skills: bool,
    expected_mount_names: list[str],
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(
        event_loop_thread_id=-1,
        ready_after_service_reads={"sandbox-layout": 1},
    )
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)

    response = provisioner_module.create_sandbox(
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-layout",
            thread_id="thread-1",
            user_id="user-1",
            include_legacy_skills=include_legacy_skills,
        )
    )

    assert response.status == "Running"
    pod = fake_core_v1.created_pod_specs["sandbox-layout"]
    volume_names = [volume.name for volume in pod.spec.volumes]
    mount_names = [mount.name for mount in pod.spec.containers[0].volume_mounts]
    assert volume_names == expected_mount_names
    assert mount_names == expected_mount_names


def test_create_sandbox_route_threads_custom_skills_root_into_pod(
    monkeypatch: pytest.MonkeyPatch,
    provisioner_module,
) -> None:
    fake_core_v1 = _RecordingCoreV1(
        event_loop_thread_id=-1,
        ready_after_service_reads={"sandbox-custom-skills": 1},
    )
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)
    categories = ("public", "custom", "legacy", "integrations")

    response = provisioner_module.create_sandbox(
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-custom-skills",
            thread_id="thread-1",
            user_id="alice",
            skills_container_path="/custom-skills",
            extra_mounts=[
                provisioner_module.ExtraMount(
                    host_path=(f"/.deer-flow/users/alice/threads/thread-1/skills_view/{category}"),
                    container_path=f"/custom-skills/{category}",
                    read_only=True,
                )
                for category in categories
            ],
        )
    )

    assert response.status == "Running"
    pod = fake_core_v1.created_pod_specs["sandbox-custom-skills"]
    mount_paths = {mount.mount_path for mount in pod.spec.containers[0].volume_mounts}
    assert not any(path.startswith("/mnt/skills") for path in mount_paths)
    assert {f"/custom-skills/{category}" for category in categories} <= mount_paths


def test_create_sandbox_retries_transient_service_read_errors(monkeypatch: pytest.MonkeyPatch, provisioner_module) -> None:
    fake_core_v1 = _RecordingCoreV1(
        event_loop_thread_id=-1,
        ready_after_service_reads={"sandbox-transient": 3},
        service_read_failures={"sandbox-transient": [503, 429]},
    )
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)
    monkeypatch.setattr(provisioner_module.time, "sleep", lambda _seconds: None)

    response = provisioner_module.create_sandbox(
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-transient",
            thread_id="thread-1",
            user_id="user-1",
        )
    )

    assert response.status == "Running"
    assert response.sandbox_url == provisioner_module._sandbox_url("sandbox-transient", node_port=32123)
    assert fake_core_v1.service_read_counts["sandbox-transient"] == 3


def test_sandbox_service_defaults_to_node_port_with_node_host_url(provisioner_module) -> None:
    provisioner_module.K8S_NAMESPACE = "mdv-sit"
    provisioner_module.SANDBOX_CONTAINER_PORT = 8080
    provisioner_module.SANDBOX_SERVICE_TYPE = "NodePort"
    provisioner_module.NODE_HOST = "node.example"

    service = provisioner_module._build_service("abc123")

    assert service.spec.type == "NodePort"
    assert service.spec.ports[0].port == 8080
    assert service.spec.ports[0].target_port == 8080
    assert provisioner_module._sandbox_url("abc123", node_port=32123) == "http://node.example:32123"


def test_sandbox_service_supports_cluster_ip_with_dns_url(provisioner_module) -> None:
    provisioner_module.K8S_NAMESPACE = "mdv-sit"
    provisioner_module.SANDBOX_CONTAINER_PORT = 8080
    provisioner_module.SANDBOX_SERVICE_TYPE = "ClusterIP"

    service = provisioner_module._build_service("abc123")

    assert service.spec.type == "ClusterIP"
    assert service.spec.ports[0].port == 8080
    assert service.spec.ports[0].target_port == 8080
    assert provisioner_module._sandbox_url("abc123") == ("http://sandbox-abc123-svc.mdv-sit.svc.cluster.local:8080")


@pytest.mark.asyncio
async def test_auth_middleware(monkeypatch: pytest.MonkeyPatch, provisioner_module) -> None:
    """Verify the X-API-Key middleware: /health is open; /api/* requires a correct key."""
    monkeypatch.setattr(provisioner_module, "PROVISIONER_API_KEY", "test-secret")
    fake_core_v1 = _RecordingCoreV1(event_loop_thread_id=-1)
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)

    transport = httpx.ASGITransport(app=provisioner_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # /health is always open — no key needed
        r = await client.get("/health")
        assert r.status_code == 200

        # /api/* with no header → 401
        r = await client.get("/api/sandboxes")
        assert r.status_code == 401

        # /api/* with wrong key → 401
        r = await client.get("/api/sandboxes", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

        # /api/* with correct key → not 401 (auth passed; handler runs with the K8s mock)
        r = await client.get("/api/sandboxes", headers={"X-API-Key": "test-secret"})
        assert r.status_code != 401


@pytest.mark.asyncio
async def test_auth_middleware_unset_key(monkeypatch: pytest.MonkeyPatch, provisioner_module) -> None:
    """When PROVISIONER_API_KEY is unset/empty, all /api/* routes return 401."""
    monkeypatch.setattr(provisioner_module, "PROVISIONER_API_KEY", "")
    fake_core_v1 = _RecordingCoreV1(event_loop_thread_id=-1)
    monkeypatch.setattr(provisioner_module, "core_v1", fake_core_v1)

    transport = httpx.ASGITransport(app=provisioner_module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # /health is always open even when key is unset
        r = await client.get("/health")
        assert r.status_code == 200

        # /api/* is always 401 when key is unset — even with a header
        r = await client.get("/api/sandboxes")
        assert r.status_code == 401

        r = await client.get("/api/sandboxes", headers={"X-API-Key": "anything"})
        assert r.status_code == 401
