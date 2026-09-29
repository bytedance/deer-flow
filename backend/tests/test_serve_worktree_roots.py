"""``scripts/serve.sh`` must discover every deer-flow worktree root verbatim.

``DEERFLOW_ROOTS`` is the set of checkout roots whose dev-port holders
``make stop`` / ``make dev`` may reclaim. It is built from
``git worktree list --porcelain``, whose ``worktree <path>`` lines are not
quoted, so a root containing whitespace must be taken as the whole remainder
of the line — ``awk '{print $2}'`` keeps only the first word, and a sibling
worktree at ``.../deer flow two`` was recorded as ``.../deer``, which
``_is_deerflow_pid`` can never match.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVE_SH = REPO_ROOT / "scripts" / "serve.sh"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="exercises git worktree paths through a POSIX shell")


def _extract_deerflow_roots_block() -> str:
    text = SERVE_SH.read_text(encoding="utf-8")
    start = text.index('DEERFLOW_ROOTS="$(')
    chunks: list[str] = []
    for line in text[start:].splitlines(keepends=True):
        chunks.append(line)
        if line.rstrip("\n") == ')"':
            return "".join(chunks)
    raise AssertionError("Could not extract the DEERFLOW_ROOTS block from serve.sh")


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull})


def _repo_with_spaced_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "deer-flow"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    linked = tmp_path / "deer flow two"
    _git("worktree", "add", "-q", str(linked), "-b", "wt-two", cwd=main)
    return main.resolve(), linked.resolve()


def _deerflow_roots(repo_root: Path) -> list[str]:
    bash = require_script_bash()
    script = f"""
REPO_ROOT={shlex.quote(str(repo_root))}
{_extract_deerflow_roots_block()}
printf '%s\\n' "$DEERFLOW_ROOTS"
"""
    result = subprocess.run([bash, "-c", script], check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line]


def test_worktree_root_with_spaces_is_kept_whole(tmp_path):
    main, linked = _repo_with_spaced_worktree(tmp_path)

    roots = _deerflow_roots(main)

    assert str(linked) in roots
    assert all(Path(root).is_dir() for root in roots), roots  # no truncated fragment such as ".../deer"
    assert sorted(roots, key=len, reverse=True) == roots  # most-specific (longest) root first


def test_repo_root_with_spaces_is_listed_once(tmp_path):
    main, linked = _repo_with_spaced_worktree(tmp_path)

    roots = _deerflow_roots(linked)  # the checkout we run from is itself the spaced path

    assert roots.count(str(linked)) == 1
    assert set(roots) == {str(main), str(linked)}  # and no truncated fragment alongside them
