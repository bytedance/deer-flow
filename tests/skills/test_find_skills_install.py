"""Verify find-skills install-skill.sh host-root guard and failure diagnostics."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SCRIPT = REPO_ROOT / "skills/public/find-skills/scripts/install-skill.sh"


def _to_bash_path(path: Path) -> str:
    if shutil.which("bash") is None:
        pytest.skip("bash is required")
    posix = path.as_posix()
    if len(posix) >= 2 and posix[1] == ":":
        drive = posix[0].lower()
        rest = posix[2:]
        for root in ("/mnt", ""):
            probe = f"{root}/{drive}{rest}"
            check = subprocess.run(["bash", "-c", f'test -e "{probe}"'], check=False)
            if check.returncode == 0:
                return probe
        return f"/mnt/{drive}{rest}"
    return posix


def _run_install_script(cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if shutil.which("bash") is None:
        pytest.skip("bash is required")
    script_path = _to_bash_path(INSTALL_SCRIPT)
    cwd_path = _to_bash_path(cwd)
    return subprocess.run(
        ["bash", "-c", f'cd "{cwd_path}" && bash "{script_path}" example/repo@example-skill'],
        check=False,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=15,
    )


def test_install_skill_rejects_missing_project_root(tmp_path: Path) -> None:
    workspace = tmp_path / "isolated-workspace"
    workspace.mkdir()

    env = {**os.environ}
    result = _run_install_script(workspace, env)

    assert result.returncode == 1
    assert result.stdout == ""
    assert "deer-flow.code-workspace" in result.stderr


def test_install_skill_reaches_npx_when_project_root_exists(tmp_path: Path) -> None:
    project_root = tmp_path / "host-repo"
    project_root.mkdir()
    (project_root / "deer-flow.code-workspace").write_text("{}", encoding="utf-8")
    nested = project_root / "nested" / "dir"
    nested.mkdir(parents=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    npx_stub = bin_dir / "npx"
    npx_stub.write_bytes(b"#!/bin/sh\nexit 77\n")
    npx_stub.chmod(0o755)

    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    result = _run_install_script(nested, env)

    assert result.returncode == 77, result.stderr
