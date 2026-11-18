"""Cover the provisioner's sandbox environment passthrough for AIO tuning."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

RESERVED_ENVIRONMENT_KEYS = (
    "AIO_BASH_MAX_SESSIONS",
    "MAX_SHELL_SESSIONS",
    "DEERFLOW_LARK_BROKER_URL",
)


def pod_environment(pod) -> dict[str, str]:
    return {item.name: item.value for item in (pod.spec.containers[0].env or [])}


def test_pod_forwards_operator_environment(provisioner_module) -> None:
    pod = provisioner_module._build_pod(
        "sandbox-env",
        "thread-env",
        environment={"DISABLE_JUPYTER": "true", "DISABLE_CODE_SERVER": "true"},
    )

    env = pod_environment(pod)
    assert env["DISABLE_JUPYTER"] == "true"
    assert env["DISABLE_CODE_SERVER"] == "true"


def test_pod_keeps_reserved_settings_from_dedicated_request_fields(provisioner_module) -> None:
    environment = {name: "spoofed" for name in RESERVED_ENVIRONMENT_KEYS}
    environment["DISABLE_VNC"] = "true"

    pod = provisioner_module._build_pod(
        "sandbox-env",
        "thread-env",
        max_bash_sessions=10,
        environment=environment,
    )

    env = pod_environment(pod)
    assert env["AIO_BASH_MAX_SESSIONS"] == "10"
    assert "MAX_SHELL_SESSIONS" not in env
    assert "DEERFLOW_LARK_BROKER_URL" not in env
    assert env["DISABLE_VNC"] == "true"


def test_request_accepts_operator_environment(provisioner_module) -> None:
    request = provisioner_module.CreateSandboxRequest(
        sandbox_id="sandbox-env",
        environment={"DISABLE_JUPYTER": "true"},
    )

    assert request.environment == {"DISABLE_JUPYTER": "true"}


@pytest.mark.parametrize("name", ["DISABLE JUPYTER", "1DISABLE", "DISABLE-YUP", "D" * 65])
def test_request_rejects_malformed_environment_keys(provisioner_module, name: str) -> None:
    with pytest.raises(ValidationError):
        provisioner_module.CreateSandboxRequest(sandbox_id="sandbox-env", environment={name: "true"})


def test_request_rejects_too_many_environment_entries(provisioner_module) -> None:
    with pytest.raises(ValidationError):
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-env",
            environment={f"KEY_{index}": "true" for index in range(33)},
        )


def test_request_rejects_oversized_environment_values(provisioner_module) -> None:
    with pytest.raises(ValidationError):
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-env",
            environment={"DISABLE_VNC": "x" * 1025},
        )


def test_request_rejects_nul_bytes_in_environment_values(provisioner_module) -> None:
    with pytest.raises(ValidationError):
        provisioner_module.CreateSandboxRequest(
            sandbox_id="sandbox-env",
            environment={"DISABLE_VNC": "true\x00"},
        )
