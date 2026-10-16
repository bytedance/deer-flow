"""The Gateway must receive the stop signal in every production launch path (#6835).

Container runtimes signal PID 1. A ``sh -c "cd backend && … uv run …"`` command
forks uv and leaves the shell as PID 1 with no SIGTERM handler, so the kernel
drops the signal: uvicorn never runs its lifespan teardown and every stop ends
in SIGKILL after the grace period. Each production launch path must therefore
``exec`` the server, and the compose gateway must also run an init process:
``exec`` removes the orphan reaping the shell provided as a side effect.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"
DOCKERFILE_PATH = REPO_ROOT / "backend" / "Dockerfile"
HELM_GATEWAY_PATH = REPO_ROOT / "deploy" / "helm" / "deer-flow" / "templates" / "gateway-deployment.yaml"
DEV_ENTRYPOINT_PATH = REPO_ROOT / "docker" / "dev-entrypoint.sh"

# ``exec`` makes uv replace the shell as PID 1, so the runtime's stop signal
# reaches uvicorn instead of being dropped.
EXEC_SERVER = "exec uv run --no-sync uvicorn app.gateway.app:app"


def _compose_gateway() -> dict:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    return compose["services"]["gateway"]


def test_compose_gateway_execs_the_server() -> None:
    """A forked server under ``sh -c`` never sees ``docker stop``'s SIGTERM (#6835)."""
    command = _compose_gateway()["command"]
    # ``command`` may load as a scalar string or a list depending on YAML style.
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    assert EXEC_SERVER in command, f"docker/docker-compose.yaml must exec the Gateway so SIGTERM reaches uvicorn (#6835); got: {command}"


def test_compose_gateway_runs_an_init_process() -> None:
    """With the shell replaced, orphaned sandbox children need Docker's init to reap them (#6835)."""
    init = _compose_gateway().get("init")
    assert init is True, f"docker/docker-compose.yaml must set init: true so orphaned grandchildren are still reaped (#6835); got: {init!r}"


def test_dockerfile_cmds_exec_the_server() -> None:
    """Both image stages are launch paths: a bare ``sh -c`` makes ``docker stop`` wait out the grace period (#6835)."""
    lines = DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
    cmds = [line for line in lines if line.startswith("CMD") and "uvicorn app.gateway.app:app" in line]
    assert len(cmds) == 2, f"backend/Dockerfile must keep one Gateway CMD per stage (#6835); got {len(cmds)}: {cmds}"
    for line in cmds:
        assert EXEC_SERVER in line, f"backend/Dockerfile CMD must exec the Gateway so SIGTERM reaches uvicorn (#6835); got: {line}"


def test_helm_gateway_args_exec_the_server() -> None:
    """Without ``exec`` the kubelet's SIGTERM is dropped and the chart's graceful-shutdown budget never starts (#6835)."""
    lines = HELM_GATEWAY_PATH.read_text(encoding="utf-8").splitlines()
    launches = [line for line in lines if "uv run --no-sync uvicorn app.gateway.app:app" in line]
    assert len(launches) == 1, f"expected exactly one Gateway launch in the Helm chart (#6835); got {len(launches)}: {launches}"
    assert EXEC_SERVER in launches[0], f"deploy/helm/deer-flow/templates/gateway-deployment.yaml must exec the Gateway so the kubelet's SIGTERM reaches uvicorn (#6835); got: {launches[0]}"


def test_dev_entrypoint_execs_the_server() -> None:
    """The dev entrypoint already execs; a regression reintroduces the dropped SIGTERM on every dev-container restart (#6835)."""
    entrypoint = DEV_ENTRYPOINT_PATH.read_text(encoding="utf-8")
    assert f"PYTHONPATH=. {EXEC_SERVER}" in entrypoint, "docker/dev-entrypoint.sh must exec the Gateway so the container's stop signal reaches uvicorn (#6835)"
