"""Regression test keeping repo shell scripts callable without the executable bit.

The root ``Makefile`` drives every shell script under ``scripts/`` through the
``RUN_SHELL_SCRIPT`` variable. On Windows that variable is the Git Bash shim; on
POSIX it used to expand to nothing, so recipes invoked the script directly::

    make: ./scripts/docker.sh: Permission denied
    make: *** [Makefile:181: docker-start] Error 127

Git tracks the executable bit, so a normal ``git clone`` is fine. It is lost in
the working tree whenever the checkout does not carry POSIX modes: source zip or
tarball downloads from the Releases/Code page, ``core.fileMode=false`` clones,
and non-POSIX filesystems (some Windows/WSL and network mounts). Nothing in the
repository can restore the bit for those users.

Naming the interpreter removes the dependency entirely -- ``bash ./x.sh`` ignores
the mode. Every script under ``scripts/`` uses ``#!/usr/bin/env bash``, so a
single ``$(BASH)`` default is correct for all of them, and the Windows branch is
untouched.

This test pins both halves of the invariant: no recipe may invoke a shell script
bare, and the POSIX definition of ``RUN_SHELL_SCRIPT`` must name an interpreter.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"

# A recipe line is a tab-indented command, optionally silenced with "@".
_RECIPE_SHELL_SCRIPT = re.compile(r"^\t@?(?P<command>.*\./scripts/[\w.-]+\.sh.*)$")


def _recipe_lines_invoking_shell_scripts() -> list[tuple[int, str]]:
    lines = MAKEFILE.read_text(encoding="utf-8").splitlines()
    found = []
    for number, line in enumerate(lines, start=1):
        match = _RECIPE_SHELL_SCRIPT.match(line)
        if match:
            found.append((number, match.group("command")))
    return found


def test_makefile_never_invokes_shell_scripts_bare() -> None:
    """Every ``scripts/*.sh`` recipe goes through an interpreter variable."""
    invocations = _recipe_lines_invoking_shell_scripts()
    assert invocations, "expected the Makefile to invoke scripts/*.sh somewhere"

    bare = [f"Makefile:{number}: {command}" for number, command in invocations if not command.startswith("$(RUN_SHELL_SCRIPT)")]
    assert not bare, "these recipes invoke a shell script without an interpreter, so they fail with 'Permission denied' in checkouts that lost the executable bit; prefix them with $(RUN_SHELL_SCRIPT):\n  " + "\n  ".join(bare)


def test_posix_run_shell_script_names_an_interpreter() -> None:
    """The non-Windows branch must expand to an interpreter, not to nothing."""
    text = MAKEFILE.read_text(encoding="utf-8")

    assert re.search(r"^BASH \?= bash$", text, re.MULTILINE), "expected 'BASH ?= bash' so operators can override the interpreter"

    assignments = re.findall(r"^\s*RUN_SHELL_SCRIPT\s*=\s*(.*)$", text, re.MULTILINE)
    assert len(assignments) == 2, f"expected one RUN_SHELL_SCRIPT definition per platform branch, got {assignments}"
    windows, posix = assignments
    assert "run-with-git-bash.cmd" in windows, windows
    assert posix.strip() == "$(BASH)", f"the POSIX branch must name an interpreter; an empty value makes recipes depend on the executable bit, got {posix!r}"


SCRIPTS_DIR = REPO_ROOT / "scripts"

# Any reference to a shell script, however the path is spelled: "./scripts/x.sh",
# "$REPO_ROOT/scripts/x.sh", "$SCRIPT_DIR/x.sh".
_SCRIPT_REFERENCE = re.compile(r"\S*[\w.-]+\.sh\b")

# A script name inside a usage string or hint is prose, not an invocation.
_MESSAGE_COMMAND = re.compile(r"\b(echo|printf|cat)\b")
_SERVE_MODE_FLAG = re.compile(r"--(?:dev|prod|daemon)\b")


def test_start_daemon_wrapper_uses_production_mode() -> None:
    """The compatibility wrapper must agree with the Makefile target."""
    makefile_text = MAKEFILE.read_text(encoding="utf-8")
    target = re.search(r"^start-daemon:\s*\n(?P<recipe>(?:\t.*\n)+)", makefile_text, re.MULTILINE)
    assert target is not None, "expected a start-daemon target in the Makefile"

    makefile_invocations = [line for line in target.group("recipe").splitlines() if "./scripts/serve.sh" in line]
    assert len(makefile_invocations) == 1, f"expected one serve.sh invocation in start-daemon, got {makefile_invocations}"

    wrapper_text = (SCRIPTS_DIR / "start-daemon.sh").read_text(encoding="utf-8")
    wrapper_invocations = [line for line in wrapper_text.splitlines() if not line.lstrip().startswith("#") and "scripts/serve.sh" in line]
    assert len(wrapper_invocations) == 1, f"expected one serve.sh invocation in start-daemon.sh, got {wrapper_invocations}"

    makefile_flags = _SERVE_MODE_FLAG.findall(makefile_invocations[0])
    wrapper_flags = _SERVE_MODE_FLAG.findall(wrapper_invocations[0])

    assert makefile_flags == ["--prod", "--daemon"], f"start-daemon must select production daemon mode, got {makefile_flags}"
    assert wrapper_flags == makefile_flags, f"start-daemon.sh mode {wrapper_flags} differs from the Makefile target {makefile_flags}"
    assert '"$@"' in wrapper_invocations[0], "the compatibility wrapper must pass optional arguments through to serve.sh"


def _sibling_script_invocations() -> list[tuple[str, int, str]]:
    """Every line in scripts/*.sh that actually runs another shell script."""
    found = []
    for script in sorted(SCRIPTS_DIR.glob("*.sh")):
        for number, raw in enumerate(script.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            for match in _SCRIPT_REFERENCE.finditer(line):
                reference = match.group(0)
                before = line[: match.start()]
                if "://" in reference:  # a download URL, not a local script
                    continue
                if reference.endswith(script.name):  # usage string / log prefix
                    continue
                if _MESSAGE_COMMAND.search(before):  # a hint printed to the user
                    continue
                if not re.search(r"\bbash\s+$", before):
                    found.append((script.name, number, line))
                    break
    return found


def test_scripts_never_invoke_sibling_scripts_bare() -> None:
    """A script calling another script must name the interpreter too.

    ``make docker-stop`` reaches ``scripts/cleanup-containers.sh`` through
    ``scripts/docker.sh``, so fixing only the Makefile would leave the same
    ``Permission denied`` failure one level deeper.
    """
    bare = [f"scripts/{name}:{number}: {line}" for name, number, line in _sibling_script_invocations()]
    assert not bare, "these lines run another shell script without an interpreter, so they fail with 'Permission denied' in checkouts that lost the executable bit; prefix them with 'bash':\n  " + "\n  ".join(bare)


# ---------- make clean portability ----------


def _clean_recipe() -> list[str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    target = re.search(r"^clean:\s*\n(?P<recipe>(?:\t[^\n]*\n?)+)", text, re.MULTILINE)
    assert target is not None, "expected a clean target in the Makefile"
    return [line.lstrip("\t").removeprefix("@").removeprefix("-") for line in target.group("recipe").splitlines()]


def test_clean_deletes_runtime_data_through_run_shell_script() -> None:
    """Deletion must not use bare ``rm`` recipes: they silently no-op on Windows.

    ``SHELL := cmd.exe`` under ``OS=Windows_NT`` means bare ``rm -rf ...
    2>/dev/null || true`` lines fail (no rm; ``2>/dev/null`` is not cmd
    redirection) while the ``-`` prefix swallows the error, so ``make clean``
    prints "✓ Cleanup complete" with ``backend/.deer-flow`` (database, users,
    threads, uploads, memory, secrets) and ``logs/*.log`` still on disk.
    """
    recipe = _clean_recipe()
    routed = [line for line in recipe if "clean_runtime_data.sh" in line]
    assert routed, "expected the clean recipe to route deletion through scripts/clean_runtime_data.sh"
    unrouted = [line for line in routed if not line.startswith("$(RUN_SHELL_SCRIPT)")]
    assert not unrouted, "these clean recipe lines invoke the cleanup script without $(RUN_SHELL_SCRIPT), which is absent under cmd.exe on Windows:\n  " + "\n  ".join(unrouted)
    bare_rm = [line for line in recipe if not line.startswith(("$(RUN_SHELL_SCRIPT)", "echo", "$(MAKE)")) and re.search(r"\brm\b", line)]
    assert not bare_rm, "these clean recipe lines call rm directly; under cmd.exe on Windows they silently no-op:\n  " + "\n  ".join(bare_rm)


def _stage_cleanup_script(tmp_path: Path) -> Path:
    script = tmp_path / "scripts" / "clean_runtime_data.sh"
    script.parent.mkdir()
    shutil.copyfile(SCRIPTS_DIR / "clean_runtime_data.sh", script)
    return script


def test_clean_runtime_data_script_deletes_runtime_tree_and_logs(tmp_path: Path) -> None:
    """The routed script must remove the runtime tree and service logs."""
    bash = require_script_bash()
    script = _stage_cleanup_script(tmp_path)
    secrets = tmp_path / "backend" / ".deer-flow" / "secrets"
    secrets.mkdir(parents=True)
    (secrets / "api.yaml").write_text("secret\n", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "gateway.log").write_text("log\n", encoding="utf-8")

    result = subprocess.run([bash, str(script)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "backend" / ".deer-flow").exists()
    assert not (logs / "gateway.log").exists()


def test_clean_runtime_data_script_removes_a_directory_named_like_a_log(tmp_path: Path) -> None:
    """The old ``rm -rf logs/*.log`` also removed matching directories; keep that scope.

    A stray ``logs/x.log/`` directory must not abort the script — with ``set -e``
    that would fail ``make clean`` after ``make stop`` has already stopped the
    stack.
    """
    bash = require_script_bash()
    script = _stage_cleanup_script(tmp_path)
    runtime = tmp_path / "backend" / ".deer-flow"
    runtime.mkdir(parents=True)
    logs = tmp_path / "logs"
    stray_directory = logs / "x.log"
    stray_directory.mkdir(parents=True)
    (stray_directory / "nested.txt").write_text("x\n", encoding="utf-8")

    result = subprocess.run([bash, str(script)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert not runtime.exists()
    assert not stray_directory.exists()


def test_clean_runtime_data_script_tolerates_a_missing_logs_directory(tmp_path: Path) -> None:
    """A fresh checkout may have no logs yet; the script must still succeed."""
    bash = require_script_bash()
    script = _stage_cleanup_script(tmp_path)
    runtime = tmp_path / "backend" / ".deer-flow"
    runtime.mkdir(parents=True)

    result = subprocess.run([bash, str(script)], capture_output=True, text=True, timeout=30)

    assert result.returncode == 0, result.stderr
    assert not runtime.exists()
