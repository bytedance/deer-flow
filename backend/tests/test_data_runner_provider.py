"""Tests for provider env injection in data_runner (task 2.2.7 / 2.2.10).

Verifies that ``run_script`` injects ``USE_PLATFORM=true`` (or
``USE_PROVIDER=<value>``) into the subprocess environment based on the
``provider`` field of the DSL data step.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def data_runner():
    fake_lg = types.ModuleType("langgraph")
    fake_config = types.ModuleType("langgraph.config")
    fake_config.get_config = lambda: {}
    fake_config.get_stream_writer = lambda: (lambda *a, **k: None)
    sys.modules.setdefault("langgraph", fake_lg)
    sys.modules.setdefault("langgraph.config", fake_config)
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "backend" / "packages" / "harness"))

    from deerflow.report_templates.runtime import data_runner as dr  # type: ignore

    return dr


def _make_descriptor():
    """Build a minimal ScriptDescriptor for run_script."""
    desc = MagicMock()
    desc.entry_path = Path("/fake/entry.py")
    desc.timeout_seconds = 30
    desc.max_output_bytes = 10_000_000
    desc.args_schema = {}
    desc.output_files = []
    desc.skill_dir = "/fake"
    desc.args_aliases = {}
    return desc


def _make_registry(descriptor):
    reg = MagicMock()
    reg.get.return_value = descriptor
    return reg


# ---------------------------------------------------------------------------
# provider → env var injection
# ---------------------------------------------------------------------------


class TestProviderEnvInjection:
    def test_platform_injects_use_platform(self, data_runner, tmp_path):
        """provider='platform' sets USE_PLATFORM=true in subprocess env."""
        desc = _make_descriptor()
        reg = _make_registry(desc)

        captured_env = {}

        def mock_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "{}"
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            try:
                data_runner.run_script(
                    step_id="s1",
                    script_qualified_name="daily-report/query_daily",
                    args={},
                    registry=reg,
                    run_output_dir=tmp_path,
                    context={},
                    provider="platform",
                )
            except Exception:
                pass  # descriptor is a mock; we only care about the env

        assert captured_env.get("USE_PLATFORM") == "true"

    def test_ins_injects_use_provider(self, data_runner, tmp_path):
        """provider='ins' sets USE_PROVIDER=ins in subprocess env."""
        desc = _make_descriptor()
        reg = _make_registry(desc)

        captured_env = {}

        def mock_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "{}"
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            try:
                data_runner.run_script(
                    step_id="s1",
                    script_qualified_name="daily-report/query_daily",
                    args={},
                    registry=reg,
                    run_output_dir=tmp_path,
                    context={},
                    provider="ins",
                )
            except Exception:
                pass

        assert captured_env.get("USE_PROVIDER") == "ins"

    def test_no_provider_no_env(self, data_runner, tmp_path):
        """provider=None (default) does not inject USE_PLATFORM or USE_PROVIDER."""
        desc = _make_descriptor()
        reg = _make_registry(desc)

        captured_env = {}

        def mock_run(cmd, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            result = MagicMock()
            result.returncode = 0
            result.stdout = "{}"
            result.stderr = ""
            return result

        with patch("subprocess.run", side_effect=mock_run):
            try:
                data_runner.run_script(
                    step_id="s1",
                    script_qualified_name="daily-report/query_daily",
                    args={},
                    registry=reg,
                    run_output_dir=tmp_path,
                    context={},
                )
            except Exception:
                pass

        assert "USE_PLATFORM" not in captured_env
        assert "USE_PROVIDER" not in captured_env


# ---------------------------------------------------------------------------
# run_data_steps_and_transforms passes provider through
# ---------------------------------------------------------------------------


class TestRunDataStepsProviderPassthrough:
    def test_passes_provider_from_step(self, data_runner, tmp_path):
        """run_data_steps_and_transforms extracts provider from step dict."""
        desc = _make_descriptor()
        reg = _make_registry(desc)

        captured_providers = []

        original_run_script = data_runner.run_script

        def spy_run_script(**kwargs):
            captured_providers.append(kwargs.get("provider"))
            result = MagicMock()
            result.outputs = {}
            return result

        dsl = {
            "data_steps": [
                {
                    "id": "s1",
                    "kind": "script",
                    "name": "daily-report/query_daily",
                    "args": {},
                    "provider": "platform",
                },
                {
                    "id": "s2",
                    "kind": "script",
                    "name": "daily-report/query_weekly",
                    "args": {},
                },
            ],
            "transforms": [],
        }

        with patch.object(data_runner, "run_script", side_effect=spy_run_script):
            data_runner.run_data_steps_and_transforms(
                dsl=dsl,
                registry=reg,
                run_output_dir=tmp_path,
                context={},
            )

        assert captured_providers == ["platform", None]
