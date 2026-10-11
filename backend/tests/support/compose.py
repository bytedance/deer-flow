"""Locate a Docker CLI whose Compose plugin can render the repo's compose files.

Tests that hand a compose file to the real client prove what Compose itself
accepts, which a YAML-shape assertion cannot. They skip without a compatible client.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

MIN_COMPOSE_VERSION = (2, 24)


def find_docker_compose() -> tuple[str | None, str]:
    """Return a compatible ``docker`` executable and an empty or actionable skip reason."""
    docker = shutil.which("docker")
    if docker is None:
        return None, "no docker compose client installed"
    try:
        probe = subprocess.run([docker, "compose", "version", "--short"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None, "no docker compose client installed"
    if probe.returncode != 0:
        return None, "no docker compose client installed"

    version = probe.stdout.strip()
    requirement = f"Compose {MIN_COMPOSE_VERSION[0]}.{MIN_COMPOSE_VERSION[1]}+ required"
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.\d+)?(?:[-+][a-zA-Z0-9.-]+)?", version)
    if match is None:
        return None, f"{requirement}, could not determine version from {version!r}"
    if tuple(int(part) for part in match.groups()) < MIN_COMPOSE_VERSION:
        return None, f"{requirement}, found {version}"
    return docker, ""


DOCKER, _skip_reason = find_docker_compose()
requires_docker_compose = pytest.mark.skipif(DOCKER is None, reason=_skip_reason)
