"""Regression tests for provisioner request-path K8s IO threading."""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from blockbuster import BlockBuster
from kubernetes.client.rest import ApiException


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
        return SimpleNamespace(status=SimpleNamespace(phase="Running"))

    def create_namespaced_pod(self, _namespace: str, pod) -> None:
        self._record_k8s_call()
        sandbox_id = pod.metadata.labels["sandbox-id"]
        self.created_pods.append(sandbox_id)
        self.created_pod_specs[sandbox_id] = pod

    def create_namespaced_service(self, _namespace: str, service) -> None:
        self._record_k8s_call()
        sandbox_id = service.metadata.labels["sandbox-id"]
        self.created_services.append(sandbox_id)
        self.service_sandboxes.add(sandbox_id)

    def delete_namespaced_service(self, _name: str, _namespace: str) -> None:
        self._record_k8s_call()

    def delete_namespaced_pod(self, _name: str, _namespace: str) -> None:
        self._record_k8s_call()

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

    with _detect_provisioner_blocking_io(provisioner_module):
        transport = httpx.ASGITransport(app=provisioner_module.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            if json_body is None:
                response = await client.request(method, path)
            else:
                response = await client.request(method, path, json=json_body)

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
            ["skills-public", "skills-custom", "user-data"],
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
