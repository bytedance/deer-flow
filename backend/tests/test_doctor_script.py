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


class TestMemoryBackendConfigCheck:
    """check_memory_backend_config validates the selected backend statically."""

    @pytest.fixture
    def doctor(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("doctor_module", REPO_ROOT / "scripts" / "doctor.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _config(manager_class: str, backend_config: dict | None = None, enabled: bool = True):
        from types import SimpleNamespace

        return SimpleNamespace(
            memory=SimpleNamespace(
                enabled=enabled,
                manager_class=manager_class,
                backend_config=backend_config or {},
            )
        )

    def test_stale_deermem_field_fails_and_names_the_key(self, doctor):
        result = doctor._check_memory_backend_config(self._config("openviking", {"debounce_seconds": 30}))

        assert result.status == "fail"
        assert "debounce_seconds" in result.detail
        assert result.fix

    def test_valid_config_passes(self, doctor, monkeypatch):
        monkeypatch.setenv("OPENVIKING_API_KEY", "test-key")
        config = self._config("openviking", {"base_url": "http://127.0.0.1:1933", "owner_user_id": "user-1"})

        assert doctor._check_memory_backend_config(config).status == "ok"

    def test_other_backends_are_skipped(self, doctor):
        result = doctor._check_memory_backend_config(self._config("deermem", {"debounce_seconds": 30}))

        assert result.status == "skip"

    def test_disabled_memory_is_skipped(self, doctor):
        result = doctor._check_memory_backend_config(self._config("openviking", {"debounce_seconds": 30}, enabled=False))

        assert result.status == "skip"

    def test_custom_openviking_subclass_path_is_skipped(self, doctor):
        # A user-defined subclass owns its backend_config shape; the built-in
        # validator must not reject it.
        result = doctor._check_memory_backend_config(self._config("myapp.memory.CustomOpenVikingManager", {"anything": True}))

        assert result.status == "skip"

    def test_dotted_manager_path_is_validated(self, doctor):
        result = doctor._check_memory_backend_config(
            self._config(
                "deerflow.agents.memory.backends.openviking.openviking_manager.OpenVikingMemoryManager",
                {"debounce_seconds": 30},
            )
        )

        assert result.status == "fail"

    def test_missing_api_key_advises_dotenv(self, doctor, monkeypatch):
        monkeypatch.delenv("OPENVIKING_API_KEY", raising=False)
        config = self._config("openviking", {"base_url": "http://127.0.0.1:1933", "owner_user_id": "user-1"})

        result = doctor._check_memory_backend_config(config)

        assert result.status == "fail"
        assert "USER API key is missing" in result.detail
        assert result.fix == "Add OPENVIKING_API_KEY=<your-key> to your .env file"


def test_memory_backend_config_failure_is_reported_end_to_end(doctor_checkout: Path):
    (doctor_checkout / "config.yaml").write_text(
        "config_version: 5\nmodels: []\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\nmemory:\n  enabled: true\n  manager_class: openviking\n  backend_config:\n    debounce_seconds: 30\n",
        encoding="utf-8",
    )

    # This check needs the harness importable in the subprocess, so unlike the
    # disposable-checkout runs above, point PYTHONPATH at the repo's backend
    # packages (the harness is path-installed, not pip-installed).
    repo_packages = REPO_ROOT / "backend" / "packages"
    separator = ";" if os.name == "nt" else ":"
    env = {name: value for name, value in os.environ.items() if not name.startswith("DEER_FLOW_") and name not in {"PYTHONHOME"}}
    env["PYTHONPATH"] = separator.join([str(repo_packages / "harness"), str(repo_packages / "extension-api"), str(REPO_ROOT / "backend")])
    result = subprocess.run(
        [sys.executable, str(doctor_checkout / "scripts" / "doctor.py")],
        cwd=doctor_checkout,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )

    assert result.returncode == 1, result.stderr
    assert "memory backend config (openviking)" in result.stdout
    assert "Unknown OpenViking backend_config fields: debounce_seconds" in result.stdout
    assert "Remove the fields named in the error" in result.stdout
