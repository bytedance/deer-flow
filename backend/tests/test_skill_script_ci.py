"""Keep the root public-skill regression suite covered by Skill Review CI."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _workflow() -> dict:
    # BaseLoader preserves GitHub Actions' `on` key rather than treating it as
    # YAML 1.1's boolean True.
    return yaml.load((REPO_ROOT / ".github/workflows/skill-review-ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


@pytest.mark.parametrize("event", ["push", "pull_request"])
def test_skill_script_changes_trigger_skill_review_ci(event: str) -> None:
    paths = _workflow()["on"][event]["paths"]
    assert "tests/skills/**" in paths
    assert "skills/public/**" in paths


def test_skill_ci_collects_every_root_skill_test_module() -> None:
    workflow = _workflow()
    job = workflow["jobs"].get("skill-tests")
    assert job is not None, "Skill Review CI must run public-skill script tests independently of package review"
    assert not job.get("needs"), "package review failures must not skip the script tests"
    assert job["if"] == workflow["jobs"]["skill-review"]["if"]
    step = next(step for step in job["steps"] if "python -m pytest" in step.get("run", ""))
    command = next(shlex.split(line) for line in step["run"].splitlines() if "python -m pytest" in line)
    assert command[:6] == ["uv", "run", "--locked", "python", "-m", "pytest"]
    working_directory = REPO_ROOT / step.get("working-directory", job.get("defaults", {}).get("run", {}).get("working-directory", "."))
    selection = [argument for argument in command[6:] if not argument.startswith("-")]
    assert len(selection) == 1
    assert (working_directory / selection[0]).resolve() == REPO_ROOT / "tests/skills"

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *command[6:], "--collect-only", "-p", "no:cacheprovider"],
        cwd=working_directory,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    collected = {Path(line.split("::", 1)[0]).name for line in result.stdout.splitlines() if "::" in line}
    expected = {path.name for path in (REPO_ROOT / "tests/skills").glob("test_*.py")}
    assert expected
    assert collected == expected, output
