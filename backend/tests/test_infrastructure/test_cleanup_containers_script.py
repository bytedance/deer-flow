"""Offline checks for the names selected by the sandbox cleanup helper."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "cleanup-containers.sh"


def _stub(path: Path, name: str, source: str) -> None:
    executable = path / name
    executable.write_text("#!/bin/sh\n" + source, encoding="utf-8", newline="\n")
    executable.chmod(0o755)


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable stubs")
def test_docker_cleanup_stops_only_sandbox_prefix(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stop_log = tmp_path / "stopped"
    _stub(
        bin_dir,
        "docker",
        'if [ "$1" = ps ]; then\n'
        '  printf "other-id not-deer-flow-sandbox Up 3 days\\nvalid-id deer-flow-sandbox-abc Up 1 hour\\nbackup-id deer-flow-sandboxbackup Up 2 days\\n"\n'
        'elif [ "$1" = stop ]; then\n'
        '  shift; printf "%s\\n" "$@" >> "$STOP_LOG"\n'
        "fi\n",
    )
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "STOP_LOG": str(stop_log)}
    result = subprocess.run(["bash", str(SCRIPT), "deer-flow-sandbox"], env=env, capture_output=True, text=True, timeout=5)

    assert result.returncode == 0, result.stderr
    assert stop_log.read_text(encoding="utf-8").splitlines() == ["valid-id"]
    assert "not-deer-flow-sandbox" not in result.stdout
    assert "deer-flow-sandbox-abc Up 1 hour" in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX executable stubs")
def test_apple_cleanup_ignores_unrelated_names_and_bad_entries(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stop_log = tmp_path / "stopped"
    entries = [
        {"configuration": None},
        {"configuration": {"id": "not-deer-flow-sandbox"}},
        {"configuration": {"id": "deer-flow-sandbox-abc"}},
    ]
    payload = tmp_path / "containers.json"
    payload.write_text(json.dumps(entries), encoding="utf-8")
    _stub(bin_dir, "container", 'if [ "$1" = list ]; then cat "$CONTAINERS_JSON"; elif [ "$1" = stop ]; then printf "%s\\n" "$2" >> "$STOP_LOG"; fi\n')
    env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin", "STOP_LOG": str(stop_log), "CONTAINERS_JSON": str(payload)}
    result = subprocess.run(["bash", str(SCRIPT), "deer-flow-sandbox"], env=env, capture_output=True, text=True, timeout=5)

    assert result.returncode == 0, result.stderr
    assert stop_log.read_text(encoding="utf-8").splitlines() == ["deer-flow-sandbox-abc"]
    assert "not-deer-flow-sandbox" not in result.stdout
