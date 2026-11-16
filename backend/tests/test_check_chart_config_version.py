"""Exercise the Helm chart config-version check in an isolated checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from support.shell import require_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_check(tmp_path: Path, example: str, chart: str) -> subprocess.CompletedProcess[str]:
    bash = require_script_bash()
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    script = scripts / "check_config_version.sh"
    shutil.copy2(REPO_ROOT / "scripts" / script.name, script)

    values = checkout / "deploy" / "helm" / "deer-flow" / "values.yaml"
    values.parent.mkdir(parents=True)
    (checkout / "config.example.yaml").write_text(f"config_version: {example}\n", encoding="utf-8", newline="")
    values.write_text(f"config: |\n  config_version: {chart}\n", encoding="utf-8", newline="")

    env = os.environ.copy()
    env.pop("BASH_ENV", None)
    env.pop("ENV", None)
    return subprocess.run(
        [bash, str(script)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=env,
    )


@pytest.mark.parametrize(
    ("example", "chart"),
    [
        ("66", "66oops"),
        ("66oops", "66"),
        ("66", "9999999999999999999"),
    ],
)
def test_invalid_version_fails_with_both_operands(tmp_path: Path, example: str, chart: str) -> None:
    result = run_check(tmp_path, example, chart)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "config_version must be a decimal integer of at most 18 digits" in result.stderr
    assert f"config.example.yaml: {example}" in result.stderr
    assert f"values.yaml: {chart}" in result.stderr
    assert "OK -" not in result.stdout


@pytest.mark.parametrize(
    ("example", "chart", "expected"),
    [
        ("66", "66", 0),
        ("66", "67", 0),
        ("66", "65", 1),
        ("1", "999999999999999999", 0),
    ],
)
def test_version_comparison(tmp_path: Path, example: str, chart: str, expected: int) -> None:
    result = run_check(tmp_path, example, chart)

    assert result.returncode == expected, result.stdout + result.stderr
