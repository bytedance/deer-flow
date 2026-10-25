"""CLI contract for scripts/doctor.py, exercised in a disposable checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def doctor_checkout(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    scripts_dir = checkout / "scripts"
    scripts_dir.mkdir(parents=True)
    (checkout / "frontend").mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "doctor.py", scripts_dir / "doctor.py")
    (checkout / "config.yaml").write_text("config_version: 5\nmodels: []\n", encoding="utf-8")
    return checkout


def _run_doctor(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {name: value for name, value in os.environ.items() if not name.startswith("DEER_FLOW_") and name not in {"PYTHONPATH", "PYTHONHOME"}}
    return subprocess.run(
        [sys.executable, str(checkout / "scripts" / "doctor.py"), *args],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
    )


def test_help_prints_usage_without_running_diagnostics(doctor_checkout: Path):
    result = _run_doctor(doctor_checkout, "--help")

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout
    assert "Status:" not in result.stdout
    assert "System Requirements" not in result.stdout


def test_unknown_flag_exits_2_with_usage_error(doctor_checkout: Path):
    result = _run_doctor(doctor_checkout, "--verbos")

    assert result.returncode == 2
    assert "unrecognized arguments: --verbos" in result.stderr
    assert "Status:" not in result.stdout
    assert "System Requirements" not in result.stdout


def test_no_arguments_still_runs_the_diagnostics(doctor_checkout: Path):
    result = _run_doctor(doctor_checkout)

    # Missing host tools or an incomplete fixture config may produce failures;
    # either exit code must still come with the normal diagnostic report.
    assert result.returncode in (0, 1), result.stderr
    assert "Status:" in result.stdout
    assert "System Requirements" in result.stdout


def test_no_arguments_ignores_inherited_runtime_configuration(doctor_checkout: Path, tmp_path: Path, monkeypatch):
    external_root = tmp_path / "external project"
    external_root.mkdir()
    external_config = external_root / "config.yaml"
    config_bytes = b"config_version: 5\nmodels:\n  - name: inherited-model\n"
    external_config.write_bytes(config_bytes)
    external_env = external_root / ".env"
    env_bytes = b"# unrelated developer environment\n"
    external_env.write_bytes(env_bytes)
    external_home = tmp_path / "external home"
    for name, value in {
        "DEER_FLOW_CONFIG_PATH": external_config,
        "DEER_FLOW_PROJECT_ROOT": external_root,
        "DEER_FLOW_ENV_FILE": external_env,
        "DEER_FLOW_HOME": external_home,
    }.items():
        monkeypatch.setenv(name, str(value))

    result = _run_doctor(doctor_checkout)

    assert result.returncode in (0, 1), result.stderr
    assert "Status:" in result.stdout
    assert "no models found" in result.stdout
    assert "1 model(s)" not in result.stdout
    assert external_config.read_bytes() == config_bytes
    assert external_env.read_bytes() == env_bytes
    assert not external_home.exists()
