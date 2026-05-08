"""Regression tests for postgres extra detection in scripts/serve.sh."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from shutil import which

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "lib" / "uv-extras.sh"
BASH_CANDIDATES = [
    Path(r"C:\Program Files\Git\bin\bash.exe"),
    Path(which("bash")) if which("bash") else None,
]
BASH_EXECUTABLE = next(
    (str(path) for path in BASH_CANDIDATES if path is not None and path.exists() and "WindowsApps" not in str(path)),
    None,
)

if BASH_EXECUTABLE is None:
    pytestmark = pytest.mark.skip(reason="bash is required for serve.sh detection tests")


def _detect_uv_extras(config_content: str, *, nested_backend_config: bool = False) -> str:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        config_path = tmp_root / ("backend/config.yaml" if nested_backend_config else "config.yaml")
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_content, encoding="utf-8")

        command = f"cd '{tmp_root}' && source '{SCRIPT_PATH}' && detect_uv_extras"

        return subprocess.check_output(
            [BASH_EXECUTABLE, "-lc", command],
            text=True,
            encoding="utf-8",
        ).strip()


def test_detect_uv_extras_empty_when_database_backend_is_sqlite():
    config = """
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
""".strip()

    assert _detect_uv_extras(config) == ""


def test_detect_uv_extras_returns_postgres_for_repo_root_config():
    config = """
database:
  backend: postgres
  postgres_url: $DATABASE_URL
""".strip()

    assert _detect_uv_extras(config) == "postgres"


def test_detect_uv_extras_returns_postgres_for_backend_config():
    config = """
database:
  backend: postgres
  postgres_url: $DATABASE_URL
""".strip()

    assert _detect_uv_extras(config, nested_backend_config=True) == "postgres"
