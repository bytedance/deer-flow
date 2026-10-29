from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_checkout(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (tmp_path / "frontend").mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "configure.py", scripts_dir / "configure.py")
    for template in ("config.example.yaml", ".env.example", "frontend/.env.example"):
        (tmp_path / template).write_text(f"template: {template}\n", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("encoding", ["ascii", "cp1252", "cp936", "utf-8"])
def test_configure_succeeds_with_restricted_stdout_encoding(config_checkout: Path, encoding: str):
    result = subprocess.run(
        [sys.executable, str(config_checkout / "scripts" / "configure.py")],
        env={**os.environ, "PYTHONIOENCODING": encoding},
        capture_output=True,
        text=True,
        encoding=encoding,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "Configuration files generated" in result.stdout
    assert result.stderr == ""
    for template, generated in (
        ("config.example.yaml", "config.yaml"),
        (".env.example", ".env"),
        ("frontend/.env.example", "frontend/.env"),
    ):
        assert (config_checkout / generated).read_bytes() == (config_checkout / template).read_bytes()


@pytest.mark.parametrize("config_name", ["config.yaml", "config.yml", "configure.yml"])
def test_configure_preserves_existing_configuration(config_checkout: Path, config_name: str):
    config_path = config_checkout / config_name
    config_path.write_text("existing: true\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(config_checkout / "scripts" / "configure.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 1
    assert "configuration file already exists" in result.stdout
    assert config_path.read_text(encoding="utf-8") == "existing: true\n"
    assert not (config_checkout / ".env").exists()
    assert not (config_checkout / "frontend" / ".env").exists()


def test_configure_help_prints_usage_without_generating_files(config_checkout: Path):
    result = subprocess.run(
        [sys.executable, str(config_checkout / "scripts" / "configure.py"), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "usage: configure.py" in result.stdout
    assert "Cross-platform config bootstrap script for DeerFlow." in result.stdout
    assert not (config_checkout / "config.yaml").exists()
    assert not (config_checkout / ".env").exists()
    assert not (config_checkout / "frontend" / ".env").exists()


def test_configure_rejects_unknown_flags_without_generating_files(config_checkout: Path):
    result = subprocess.run(
        [sys.executable, str(config_checkout / "scripts" / "configure.py"), "--not-a-real-flag"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert not (config_checkout / "config.yaml").exists()
    assert not (config_checkout / ".env").exists()
    assert not (config_checkout / "frontend" / ".env").exists()
