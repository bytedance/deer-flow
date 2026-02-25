"""Regression tests for docker sandbox mode detection logic."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "docker.sh"


def _detect_mode_with_config(config_content: str) -> str:
    """Write config content into a temp project root and execute detect_sandbox_mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_root = Path(tmpdir)
        (tmp_root / "config.yaml").write_text(config_content)

        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmp_root}' && detect_sandbox_mode"

        output = subprocess.check_output(
            ["bash", "-lc", command],
            text=True,
        ).strip()

        return output


def test_detect_mode_defaults_to_local_when_config_missing():
    """No config file should default to local mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        command = f"source '{SCRIPT_PATH}' && PROJECT_ROOT='{tmpdir}' && detect_sandbox_mode"
        output = subprocess.check_output(["bash", "-lc", command], text=True).strip()

    assert output == "local"


def test_detect_mode_local_provider():
    """Local sandbox provider should map to local mode."""
    config = """
sandbox:
  use: src.sandbox.local:LocalSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"


def test_detect_mode_aio_without_provisioner_url():
    """AIO sandbox without provisioner_url should map to aio mode."""
    config = """
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_provisioner_with_url():
    """AIO sandbox with provisioner_url should map to provisioner mode."""
    config = """
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
  provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "provisioner"


def test_detect_mode_ignores_commented_provisioner_url():
    """Commented provisioner_url should not activate provisioner mode."""
    config = """
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
  # provisioner_url: http://provisioner:8002
""".strip()

    assert _detect_mode_with_config(config) == "aio"


def test_detect_mode_unknown_provider_falls_back_to_local():
    """Unknown sandbox provider should default to local mode."""
    config = """
sandbox:
  use: custom.module:UnknownProvider
""".strip()

    assert _detect_mode_with_config(config) == "local"
