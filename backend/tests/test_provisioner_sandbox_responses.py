"""Regression tests for provisioner lark conflict markers and Terminating handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _pod(*, phase: str = "Running", deletion_timestamp=None, broker: bool = False) -> SimpleNamespace:
    containers = [SimpleNamespace(name="lark-cli-broker")] if broker else []
    init_containers = [SimpleNamespace(name="lark-cli-shim-init")] if broker else []
    return SimpleNamespace(
        metadata=SimpleNamespace(uid="pod-generation", deletion_timestamp=deletion_timestamp),
        status=SimpleNamespace(phase=phase),
        spec=SimpleNamespace(containers=containers, init_containers=init_containers),
    )


@pytest.mark.parametrize(
    "broker_image, runtime, broker, expected_status",
    [
        ("", False, True, 503),  # broker requested but the image is not configured
        ("broker-image", True, False, 409),  # broker configured but the request says non-broker
    ],
)
def test_lark_provisioning_conflicts_carry_capability_refresh_marker(monkeypatch, provisioner_module, broker_image, runtime, broker, expected_status):
    """Both lark config conflicts tell the Gateway to drop its cached capability."""
    monkeypatch.setattr(provisioner_module, "LARK_CLI_BROKER_IMAGE", broker_image)

    with pytest.raises(provisioner_module.HTTPException) as error:
        provisioner_module._validate_lark_provisioning_request(runtime, broker)

    assert error.value.status_code == expected_status
    assert error.value.headers[provisioner_module.CAPABILITY_REFRESH_HEADER] == "lark-broker"


def test_lark_provisioning_request_without_conflict_passes(monkeypatch, provisioner_module):
    monkeypatch.setattr(provisioner_module, "LARK_CLI_BROKER_IMAGE", "broker-image")
    provisioner_module._validate_lark_provisioning_request(True, True)
    provisioner_module._validate_lark_provisioning_request(False, False)


@pytest.mark.parametrize(
    "requirements",
    [
        {"required_broker": False},
        {"required_broker": True},
        {"required_capacity": 5},
    ],
)
def test_sandbox_response_rejects_terminating_pod_when_create_requirements_present(monkeypatch, provisioner_module, requirements):
    """A create coordination request must not settle on a Terminating Pod."""
    # The Pod must satisfy the requested mode, or the pre-existing mode check
    # fires first; this test pins the Terminating check specifically.
    pod = _pod(deletion_timestamp="2026-10-07T00:00:00Z", broker=requirements.get("required_broker") is True)
    core = MagicMock()
    core.read_namespaced_pod.return_value = pod
    monkeypatch.setattr(provisioner_module, "core_v1", core)

    with pytest.raises(provisioner_module.HTTPException) as error:
        provisioner_module._sandbox_response("sandbox-1", "http://sandbox", **requirements)

    assert error.value.status_code == 409
    assert "terminating" in error.value.detail


def test_sandbox_response_reports_terminating_status_without_requirements(monkeypatch, provisioner_module):
    """get/list pass no requirements: the phase is data, not an error."""
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(deletion_timestamp="2026-10-07T00:00:00Z")
    monkeypatch.setattr(provisioner_module, "core_v1", core)

    response = provisioner_module._sandbox_response("sandbox-1", "http://sandbox")

    assert response.status == "Terminating"
    assert response.sandbox_url == "http://sandbox"


def test_list_sandboxes_keeps_terminating_entries_visible(monkeypatch, provisioner_module):
    """One Terminating Pod must not fail or empty the whole fleet listing."""
    core = MagicMock()

    def read_pod(name, namespace):
        assert namespace == provisioner_module.K8S_NAMESPACE
        if name == "sandbox-sandbox-terminating":
            return _pod(deletion_timestamp="2026-10-07T00:00:00Z")
        return _pod(phase="Running")

    core.read_namespaced_pod.side_effect = read_pod
    core.list_namespaced_service.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(
                metadata=SimpleNamespace(labels={"sandbox-id": "sandbox-terminating"}),
                spec=SimpleNamespace(ports=[SimpleNamespace(name="http", node_port=31001)]),
            ),
            SimpleNamespace(
                metadata=SimpleNamespace(labels={"sandbox-id": "sandbox-running"}),
                spec=SimpleNamespace(ports=[SimpleNamespace(name="http", node_port=31002)]),
            ),
        ]
    )
    monkeypatch.setattr(provisioner_module, "core_v1", core)

    payload = provisioner_module.list_sandboxes()

    assert payload["count"] == 2
    statuses = {entry.sandbox_id: entry.status for entry in payload["sandboxes"]}
    assert statuses == {"sandbox-terminating": "Terminating", "sandbox-running": "Running"}


def test_sandbox_response_running_pod_without_broker_requirement_still_succeeds(monkeypatch, provisioner_module):
    core = MagicMock()
    core.read_namespaced_pod.return_value = _pod(phase="Running")
    monkeypatch.setattr(provisioner_module, "core_v1", core)

    response = provisioner_module._sandbox_response("sandbox-1", "http://sandbox")

    assert response.status == "Running"
    assert response.sandbox_url == "http://sandbox"
