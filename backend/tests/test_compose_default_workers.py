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

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"


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
