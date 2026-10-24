"""The opt-in config-upgrade wrapper must isolate the suite from the host's uv indexes.

`scripts/test-config-version.sh` exists so a host whose `uv` points at a mirror
that blocks dependencies can still run `tests/test_config_version.py`. Nothing
pins that contract today: dropping one `unset`, or moving the `export` above it,
silently restores the failure it was added for. These tests run the real script
with a stand-in `uv` and assert what that child actually received.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "test-config-version.sh"

BASH = shutil.which("bash")
pytestmark = pytest.mark.skipif(BASH is None, reason="requires bash")

STUB = """#!/usr/bin/env bash
{
  printf 'UV_INDEX=%s\\n' "${UV_INDEX-<unset>}"
  printf 'UV_EXTRA_INDEX_URL=%s\\n' "${UV_EXTRA_INDEX_URL-<unset>}"
  printf 'UV_INDEX_URL=%s\\n' "${UV_INDEX_URL-<unset>}"
  printf 'UV_DEFAULT_INDEX=%s\\n' "${UV_DEFAULT_INDEX-<unset>}"
  printf 'ARGS=%s\\n' "$*"
} > "$STUB_OUT"
exit 0
"""


def _posix(path: Path) -> str:
    """Return the path spelling bash needs for PATH on this host."""
    if os.name != "nt":
        return str(path)
    converted = subprocess.run(
        [BASH or "bash", "-c", 'cygpath -u "$1"', "cygpath", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return converted.stdout.strip()


def _run_wrapper(tmp_path: Path, extra_env: dict[str, str]) -> dict[str, str]:
    assert SCRIPT.is_file(), f"{SCRIPT} must exist"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "uv"
    stub.write_text(STUB, encoding="utf-8", newline="")
    stub.chmod(0o755)

    captured = tmp_path / "captured.env"
    env = {key: value for key, value in os.environ.items() if not key.startswith("UV_")}
    env.update(extra_env)
    env["STUB_OUT"] = _posix(captured)
    env["PATH"] = f"{_posix(bin_dir)}{os.pathsep}{env.get('PATH', '')}"

    result = subprocess.run(
        [BASH or "bash", str(SCRIPT), "--deselect", "sentinel"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"wrapper failed: {result.stdout}\n{result.stderr}"
    assert captured.is_file(), f"the stand-in uv never ran: {result.stdout}\n{result.stderr}"

    return dict(line.split("=", 1) for line in captured.read_text(encoding="utf-8").splitlines() if "=" in line)


def test_wrapper_clears_host_indexes_and_selects_public_pypi(tmp_path):
    captured = _run_wrapper(
        tmp_path,
        {
            "UV_INDEX": "https://mirror.invalid/simple",
            "UV_EXTRA_INDEX_URL": "https://extra.invalid/simple",
            "UV_INDEX_URL": "https://legacy.invalid/simple",
        },
    )

    assert captured["UV_INDEX"] == "<unset>"
    assert captured["UV_EXTRA_INDEX_URL"] == "<unset>"
    assert captured["UV_INDEX_URL"] == "<unset>"
    assert captured["UV_DEFAULT_INDEX"] == "https://pypi.org/simple"


def test_wrapper_runs_the_config_version_suite_and_forwards_arguments(tmp_path):
    captured = _run_wrapper(tmp_path, {})

    assert captured["ARGS"].startswith("run --locked pytest -q tests/test_config_version.py")
    assert "--deselect sentinel" in captured["ARGS"]
