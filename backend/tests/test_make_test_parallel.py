"""Exercise the backend test scheduler with offline worker doubles."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")
pytestmark = pytest.mark.skipif(MAKE is None or os.name == "nt", reason="requires POSIX make")


@pytest.fixture
def test_project(tmp_path: Path) -> Path:
    project = tmp_path / "backend"
    project.mkdir()
    shutil.copyfile(BACKEND_ROOT / "Makefile", project / "Makefile")
    (project / ".test_durations").write_text("{}\n", encoding="utf-8")
    bin_dir = project / "bin"
    bin_dir.mkdir()
    worker = project / "worker.py"
    worker.write_text(
        """import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
group = args[args.index('--group') + 1] if '--group' in args else '0'
Path(f'{group}.started').write_text(json.dumps(args), encoding='utf-8')
if group == '0':
    sys.exit(0)
if os.environ.get('EXPECT_PARALLEL') == '1':
    deadline = time.monotonic() + 10
    while not all(Path(f'{other}.started').exists() for other in range(1, 5)):
        if time.monotonic() > deadline:
            sys.exit('workers did not start concurrently')
        time.sleep(0.01)
Path(f'{group}.finished').write_text('done', encoding='utf-8')
sys.exit(7 if group == os.environ.get('FAIL_GROUP') else 0)
""",
        encoding="utf-8",
    )
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\nexec "$TEST_WORKER_PYTHON" "$TEST_WORKER_SCRIPT" "$@"\n', encoding="utf-8")
    uv.chmod(0o755)
    return project


def run_make(project: Path, *args: str, fail_group: str = "", parallel: bool = True) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": str(project / "bin") + os.pathsep + os.environ.get("PATH", ""),
        "TEST_WORKER_PYTHON": sys.executable,
        "TEST_WORKER_SCRIPT": str(project / "worker.py"),
        "EXPECT_PARALLEL": "1" if parallel else "0",
        "FAIL_GROUP": fail_group,
    }
    env.pop("MAKEFLAGS", None)
    env.pop("MFLAGS", None)
    env.pop("MAKELEVEL", None)
    return subprocess.run([MAKE, *args], cwd=project, env=env, capture_output=True, text=True, encoding="utf-8", check=False, timeout=30)


@pytest.mark.parametrize("fail_group", ["", "1"])
def test_make_test_runs_all_four_shards_and_reports_any_failure(test_project: Path, fail_group: str) -> None:
    result = run_make(test_project, "test", fail_group=fail_group)

    assert (result.returncode == 0) == (not fail_group), result.stdout + result.stderr
    assert {path.stem for path in test_project.glob("*.finished")} == {"1", "2", "3", "4"}
    for group in range(1, 5):
        args = json.loads((test_project / f"{group}.started").read_text(encoding="utf-8"))
        assert args[:3] == ["run", "pytest", "-m"]
        assert args[args.index("-m") + 1] == "not live"
        assert "--ignore=tests/blocking_io" in args
        assert args[args.index("--splits") + 1] == "4"
        assert args[args.index("--group") + 1] == str(group)
        assert args[args.index("--splitting-algorithm") + 1] == "least_duration"
        assert "--store-durations" not in args


def test_ci_can_still_run_one_shard(test_project: Path) -> None:
    result = run_make(test_project, "test-shard", "SPLITS=4", "GROUP=2", parallel=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.stem for path in test_project.glob("*.finished")} == {"2"}


def test_make_test_can_limit_concurrency(test_project: Path) -> None:
    result = run_make(test_project, "test", "TEST_JOBS=1", parallel=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert {path.stem for path in test_project.glob("*.finished")} == {"1", "2", "3", "4"}


def test_make_test_reports_missing_durations(test_project: Path) -> None:
    (test_project / ".test_durations").unlink()

    result = run_make(test_project, "test")

    assert result.returncode != 0
    assert "make test-shard-durations" in result.stdout + result.stderr
    assert not list(test_project.glob("*.started"))
