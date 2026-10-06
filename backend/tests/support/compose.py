"""Locate a Docker CLI whose Compose plugin can render the repo's compose files.

Tests that hand a compose file to the real client prove what Compose itself
accepts, which a YAML-shape assertion cannot. They skip on hosts without one.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


def find_docker_compose() -> str | None:
    """Return the ``docker`` executable when ``docker compose`` answers, or ``None``."""
    docker = shutil.which("docker")
    if docker is None:
        return None
    try:
        probe = subprocess.run([docker, "compose", "version"], capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return docker if probe.returncode == 0 else None


DOCKER = find_docker_compose()
requires_docker_compose = pytest.mark.skipif(DOCKER is None, reason="no docker compose client installed")
