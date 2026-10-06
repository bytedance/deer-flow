"""`make clean` says what it deletes and refuses while the Gateway container runs.

The target deletes ``backend/.deer-flow`` -- the database, users, threads,
uploads, and secrets -- but ``make help`` described it as cleaning up
"temporary files". Both Docker stacks mount that directory into the
``deer-flow-gateway`` container, and ``make stop`` only stops local services,
so ``make clean`` used to delete the data under a running Gateway.

These tests run the real ``make clean`` from the real Makefile and guard script
in a scratch checkout. ``scripts/serve.sh`` is a stub that records the stop
call, so nothing touches the host's processes or containers, and ``docker`` is
a fake on a PATH limited to the tools the recipe needs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    os.name == "nt" or shutil.which("make") is None or shutil.which("bash") is None,
    reason="runs the POSIX make recipe",
)

_TOOLS = ("make", "bash", "sh", "rm", "grep", "tr")


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "Makefile", root / "Makefile")
    shutil.copy2(REPO_ROOT / "scripts" / "check-data-not-in-use.sh", root / "scripts" / "check-data-not-in-use.sh")
    (root / "scripts" / "serve.sh").write_text('#!/usr/bin/env bash\necho "$@" >> stop-calls\n', encoding="utf-8")
    data = root / "backend" / ".deer-flow" / "data"
    data.mkdir(parents=True)
    (data / "deerflow.db").write_text("db", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "gateway.log").write_text("log", encoding="utf-8")
    return root


def _bin(tmp_path: Path, docker: str | None) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in _TOOLS:
        found = shutil.which(tool)
        assert found, tool
        (bin_dir / tool).symlink_to(found)
    if docker is not None:
        fake = bin_dir / "docker"
        fake.write_text(f"#!/bin/sh\n{docker}\n", encoding="utf-8")
        fake.chmod(0o755)
    return bin_dir


def _make(root: Path, bin_dir: Path, target: str = "clean") -> subprocess.CompletedProcess[str]:
    env = {"PATH": str(bin_dir), "HOME": str(root)}
    return subprocess.run(["make", "-s", target], cwd=root, env=env, capture_output=True, text=True, timeout=60)


def test_help_says_clean_deletes_runtime_data(tmp_path: Path) -> None:
    root = _checkout(tmp_path)

    help_line = next(line for line in _make(root, _bin(tmp_path, None), "help").stdout.splitlines() if "make clean" in line)

    assert "temporary files" not in help_line
    assert "DELETE" in help_line and "backend/.deer-flow" in help_line


@pytest.mark.parametrize(
    "names",
    ["deer-flow-gateway", "deer-flow-redis\ndeer-flow-gateway", "deer-flow-gateway\r"],
    ids=["gateway", "whole-stack", "crlf"],
)
def test_clean_refuses_while_the_gateway_container_runs(tmp_path: Path, names: str) -> None:
    root = _checkout(tmp_path)
    listing = names.replace("\n", "\\n").replace("\r", "\\r")

    result = _make(root, _bin(tmp_path, f"printf '{listing}\\n'"))

    assert result.returncode != 0
    assert "deer-flow-gateway container is running" in result.stderr
    assert (root / "backend" / ".deer-flow" / "data" / "deerflow.db").exists()
    assert (root / "logs" / "gateway.log").exists()
    # The guard runs before stop, which would stop the stack's sandboxes.
    assert not (root / "stop-calls").exists()


@pytest.mark.parametrize(
    "docker",
    [None, "exit 1", "printf 'deer-flow-gateway-old\\nmy-deer-flow-gateway\\ndeer-flow-sandbox-1\\n'"],
    ids=["no-docker", "daemon-down", "other-containers"],
)
def test_clean_deletes_runtime_data_when_no_gateway_container_runs(tmp_path: Path, docker: str | None) -> None:
    root = _checkout(tmp_path)

    result = _make(root, _bin(tmp_path, docker))

    assert result.returncode == 0, result.stderr
    assert "Deleting local runtime data in backend/.deer-flow" in result.stdout
    assert not (root / "backend" / ".deer-flow").exists()
    assert not (root / "logs" / "gateway.log").exists()
    assert (root / "stop-calls").read_text(encoding="utf-8").split() == ["--stop"]
