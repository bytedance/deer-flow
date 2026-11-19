"""Offline coverage for the Compose client gate used by real rendering tests."""

from __future__ import annotations

import subprocess

import pytest
from support import compose

DOCKER = "/fake/docker"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda name: DOCKER)

    def detect(stdout: str, *, returncode: int = 0):
        def run(command, **kwargs):
            return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")

        monkeypatch.setattr(compose.subprocess, "run", run)
        return compose.find_docker_compose()

    return detect


@pytest.mark.parametrize("version", ["2.24.0", "v2.24.0", "2.24.0-desktop.1", "2.24.7+vendor.1", "2.25.0", "3.0.0", "5.1.4"])
def test_supported_compose_client_is_available(version, probe):
    assert probe(f"{version}\n") == (DOCKER, "")


@pytest.mark.parametrize("version", ["2.23.3", "v2.9.9", "1.29.2"])
def test_old_compose_client_is_skipped_with_its_version(version, probe):
    assert probe(f"{version}\n") == (None, f"Compose 2.24+ required, found {version}")


def test_probe_requests_the_short_version(monkeypatch):
    commands = []
    monkeypatch.setattr(compose.shutil, "which", lambda name: DOCKER)

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="2.24.0\n", stderr="")

    monkeypatch.setattr(compose.subprocess, "run", run)

    assert compose.find_docker_compose() == (DOCKER, "")
    assert commands == [[DOCKER, "compose", "version", "--short"]]


@pytest.mark.parametrize("output", ["", "garbage", "Docker Compose version v2.24.0", "2"])
def test_unreadable_compose_version_is_skipped(output, probe):
    docker, reason = probe(output)

    assert docker is None
    assert "Compose 2.24+ required" in reason
    assert "could not determine version" in reason


def test_missing_docker_is_skipped_without_probing(monkeypatch):
    monkeypatch.setattr(compose.shutil, "which", lambda name: None)
    monkeypatch.setattr(compose.subprocess, "run", lambda *args, **kwargs: pytest.fail("missing Docker must not be executed"))

    assert compose.find_docker_compose() == (None, "no docker compose client installed")


def test_missing_compose_plugin_is_skipped(probe):
    assert probe("", returncode=1) == (None, "no docker compose client installed")


@pytest.mark.parametrize("error", [OSError("cannot execute docker"), subprocess.TimeoutExpired([DOCKER, "compose", "version", "--short"], 60)])
def test_unavailable_compose_probe_is_skipped(monkeypatch, error):
    monkeypatch.setattr(compose.shutil, "which", lambda name: DOCKER)

    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr(compose.subprocess, "run", run)

    assert compose.find_docker_compose() == (None, "no docker compose client installed")
