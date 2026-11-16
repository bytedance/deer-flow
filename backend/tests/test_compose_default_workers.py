"""Regression test for the Docker Compose default Gateway worker count.

The Gateway holds run state (RunManager and the stream bridge) in process, so
the default deployment must run a single Uvicorn worker. Running more than one
worker without a shared cross-worker stream bridge breaks run cancellation, SSE
reconnects, request de-duplication, and IM channels (nginx has no sticky
sessions, so requests scatter across workers that each keep their own run
state). This test pins the safe default so it cannot silently regress to a
multi-worker default, while still allowing operators to override it once a
shared stream bridge exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from _gateway_shutdown_budget import HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT, lifespan_shutdown_seconds

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"
DEV_COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose-dev.yaml"
DEV_ENTRYPOINT_PATH = REPO_ROOT / "docker" / "dev-entrypoint.sh"
GATEWAY_APP_PATH = REPO_ROOT / "backend" / "app" / "gateway" / "app.py"


def _gateway_command() -> str:
    """Return the gateway service command as a single string."""
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    command = compose["services"]["gateway"]["command"]
    # ``command`` may load as a scalar string or a list depending on YAML style.
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    return command


def test_gateway_defaults_to_single_worker():
    """With GATEWAY_WORKERS unset, the worker count must default to 1."""
    command = _gateway_command()
    match = re.search(r"GATEWAY_WORKERS:-(\d+)", command)
    assert match is not None, f"gateway command must set a GATEWAY_WORKERS default; got: {command}"
    assert match.group(1) == "1", f"default Gateway worker count must be 1, got {match.group(1)}"


def test_gateway_worker_count_remains_overridable():
    """The worker count must stay configurable, not hard-coded to 1."""
    command = _gateway_command()
    assert "${GATEWAY_WORKERS:-1}" in command, f"worker count must use ${{GATEWAY_WORKERS:-1}} so operators can override it; got: {command}"


def _graceful_shutdown_bound(launch: str) -> int:
    """Return uvicorn's ``--timeout-graceful-shutdown`` bound from a launch command or script."""
    match = re.search(r"--timeout-graceful-shutdown (\d+)", launch)
    assert match is not None, f"uvicorn launch must bound its graceful shutdown; got: {launch}"
    return int(match.group(1))


def _stop_grace_seconds(compose_path: Path) -> int:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    grace = compose["services"]["gateway"]["stop_grace_period"]
    match = re.fullmatch(r"(\d+)s", str(grace))
    assert match is not None, f"stop_grace_period must be expressed in seconds, got {grace!r}"
    return int(match.group(1))


def test_gateway_bounds_uvicorn_graceful_shutdown():
    """Open SSE connections must not hold lifespan shutdown (bounded hooks, run drain, memory flush) past the stop grace period."""
    assert _graceful_shutdown_bound(_gateway_command()) <= 30


def test_gateway_stop_grace_period_covers_the_shutdown_work():
    """Docker's 10s default SIGKILLed the 30s memory queue flush on every restart."""
    assert _stop_grace_seconds(COMPOSE_PATH) >= _graceful_shutdown_bound(_gateway_command()) + lifespan_shutdown_seconds()


def test_dev_gateway_bounds_uvicorn_graceful_shutdown_and_covers_it():
    """The dev stack launches uvicorn from dev-entrypoint.sh and is restarted far more often."""
    bound = _graceful_shutdown_bound(DEV_ENTRYPOINT_PATH.read_text(encoding="utf-8"))
    assert bound <= 30
    assert _stop_grace_seconds(DEV_COMPOSE_PATH) >= bound + lifespan_shutdown_seconds()


def test_shutdown_budget_models_every_bounded_lifespan_hook():
    """Each ``wait_for(..., timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS)`` in the lifespan is a sequential 5s worst case the grace periods must cover."""
    source = GATEWAY_APP_PATH.read_text(encoding="utf-8")
    bounded_sites = source.count("timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS")
    assert bounded_sites == len(HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT), (
        f"app.gateway.app bounds {bounded_sites} teardown hook(s) with _SHUTDOWN_HOOK_TIMEOUT_SECONDS but "
        f"_gateway_shutdown_budget models {len(HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT)}; update HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT "
        "so the chart and compose grace periods keep covering the worst case"
    )
