"""Regression coverage for #5179: on Windows/Git Bash the Microsoft Store
python alias stubs pass Bash's own PATH lookup but cannot be exec'd through
/usr/bin/env, so `make dev` never started the frontend."""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"


def _extract_shell_function(name: str) -> str:
    text = SERVE_SH.read_text(encoding="utf-8")
    marker = f"{name}() {{"
    start = text.index(marker)
    depth = 0
    chunks: list[str] = []

    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0:
            return "".join(chunks)

    raise AssertionError(f"Could not extract shell function {name}")


# Shells out to bash with a stub-only PATH plus an optional `env` override,
# exactly the split that broke Windows: the candidate stubs succeed when
# invoked directly, while the mocked `env` mimics /usr/bin/env resolving the
# WindowsApps alias (exit 127 = cannot exec).
_SCRIPT_TEMPLATE = r"""
set -u
BIN=__BIN__
mkdir -p "$BIN"
for name in __STUBS__; do
    printf '#!/bin/sh
exit 0
' > "$BIN/$name"
    chmod +x "$BIN/$name"
done
export PATH="$BIN:$PATH"

__ENV_MOCK__

__FUNCTION__

_pick_python
"""


def _to_bash_path(path: Path) -> str:
    """Return `path` in the form the target bash understands.

    MSYS/Git Bash needs an MSYS-style path (/c/...) on PATH: a drive-letter
    style segment (C:/...) is resolved inconsistently between bash's own
    lookup and /usr/bin/env. POSIX hosts pass through unchanged.
    """
    posix = path.resolve().as_posix()
    if len(posix) > 1 and posix[1] == ":":
        return "/" + posix[0].lower() + posix[2:]
    return posix


def _run_pick_python(tmp_path: Path, *, env_mock: str = "") -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to exercise serve.sh helpers")

    script = _SCRIPT_TEMPLATE.replace("__BIN__", shlex.quote(_to_bash_path(tmp_path / "bin"))).replace("__STUBS__", "python3 python py").replace("__ENV_MOCK__", env_mock).replace("__FUNCTION__", _extract_shell_function("_pick_python"))
    # errors="replace": bash's diagnostics may arrive in the console's code
    # page (GBK on a Chinese Windows host) while the selection output is ASCII.
    return subprocess.run(
        [bash, "-c", script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_pick_python_prefers_python3_when_env_agrees(tmp_path):
    # Real env: all stubs are ordinary executables, so python3 wins.
    result = _run_pick_python(tmp_path)

    assert result.returncode == 0
    assert result.stdout.strip() == "python3"


def test_pick_python_skips_candidate_that_env_cannot_exec(tmp_path):
    # Store-alias world: python3 execs fine directly but env fails on it;
    # python works through both paths. Must select python, not python3.
    env_mock = """
env() {
    case "$1" in
        python3) return 127 ;;
    esac
    return 0
}
"""
    result = _run_pick_python(tmp_path, env_mock=env_mock)

    assert result.returncode == 0
    assert result.stdout.strip() == "python"


def test_pick_python_fails_when_no_candidate_survives_env_probe(tmp_path):
    env_mock = """
env() { return 127; }
"""
    result = _run_pick_python(tmp_path, env_mock=env_mock)

    assert result.returncode == 1
    assert result.stdout.strip() == ""
