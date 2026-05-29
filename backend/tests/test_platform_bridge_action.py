"""Unit tests for _platform_bridge.py call_action helper (Task 5.3).

Tests the action mode subprocess invocation that calls adapter-internal
pure functions (KPI aggregation, point selection).
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Load _platform_bridge from the scripts directory
_SCRIPTS_PATH = Path(__file__).parent.parent.parent / "skills" / "custom" / "data-analyst" / "scripts"
_PLATFORM_BRIDGE_FILE = _SCRIPTS_PATH / "_platform_bridge.py"

_spec = importlib.util.spec_from_file_location("_platform_bridge", _PLATFORM_BRIDGE_FILE)
_platform_bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_platform_bridge)

PlatformBridgeError = _platform_bridge.PlatformBridgeError
_build_action_command = _platform_bridge._build_action_command
call_action = _platform_bridge.call_action


class TestBuildActionCommand:
    """Tests for _build_action_command helper."""

    def test_builds_correct_argv(self):
        """Command includes --action, --adapter, and all required flags."""
        cmd = _build_action_command(
            action="aggregate_kpi",
            adapter="ins_prod",
            tenant_id="tenant-1",
            user_id="user-1",
            params={"kpi_keys": ["runtime_rate"]},
            python_executable="/usr/bin/python3",
        )

        assert cmd[0] == "/usr/bin/python3"
        assert "-m" in cmd
        assert "deerflow.integrations.cli" in cmd
        assert "--action" in cmd
        assert "aggregate_kpi" in cmd
        assert "--adapter" in cmd
        assert "ins_prod" in cmd
        assert "--tenant-id" in cmd
        assert "tenant-1" in cmd
        assert "--user-id" in cmd
        assert "user-1" in cmd
        assert "--params" in cmd

    def test_serializes_params_to_json(self):
        """Params dict is JSON-serialized in the command."""
        params = {
            "trend_data": {"EQ1": [{"time_ms": 1000, "values": {"speed": 100}}]},
            "kpi_keys": ["runtime_rate", "alarm_count"],
        }
        cmd = _build_action_command(
            action="aggregate_kpi",
            adapter="ins_prod",
            tenant_id="t1",
            user_id="u1",
            params=params,
        )

        params_idx = cmd.index("--params")
        params_json = cmd[params_idx + 1]
        parsed = json.loads(params_json)
        assert parsed == params

    def test_uses_sys_executable_by_default(self):
        """Defaults to sys.executable when python_executable not provided."""
        cmd = _build_action_command(
            action="select_points",
            adapter="ins_prod",
            tenant_id="t1",
            user_id="u1",
            params={},
        )
        assert cmd[0] == sys.executable


class TestCallAction:
    """Tests for call_action function."""

    def test_constructs_correct_subprocess_command(self):
        """call_action builds the right command and parses JSON output."""
        mock_completed = MagicMock()
        mock_completed.stdout = json.dumps({
            "ok": True,
            "data": {"kpis": {"EQ1": {"runtime_rate": 0.75}}},
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        })
        mock_completed.stderr = ""
        mock_completed.returncode = 0

        with patch("subprocess.run", return_value=mock_completed) as mock_run:
            result = call_action(
                action="aggregate_kpi",
                adapter="ins_prod",
                params={"trend_data": {}, "kpi_keys": ["runtime_rate"]},
                tenant_id="test-tenant",
                user_id="test-user",
            )

        # Verify subprocess was called with correct command
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "--action" in cmd
        assert "aggregate_kpi" in cmd
        assert "--adapter" in cmd
        assert "ins_prod" in cmd

        # Verify result is parsed correctly
        assert result["ok"] is True
        assert result["data"]["kpis"]["EQ1"]["runtime_rate"] == 0.75
        assert result["adapter"] == "ins_prod"
        assert result["action"] == "aggregate_kpi"

    def test_raises_on_subprocess_failure(self):
        """Raises PlatformBridgeError when subprocess returns ok: false."""
        mock_completed = MagicMock()
        mock_completed.stdout = json.dumps({
            "ok": False,
            "error": "trend_data and kpi_keys are required",
            "error_type": "ValueError",
            "adapter": "ins_prod",
            "action": "aggregate_kpi",
        })
        mock_completed.stderr = ""
        mock_completed.returncode = 1

        with patch("subprocess.run", return_value=mock_completed):
            with pytest.raises(PlatformBridgeError) as exc_info:
                call_action(
                    action="aggregate_kpi",
                    adapter="ins_prod",
                    params={},
                    tenant_id="t1",
                    user_id="u1",
                )

        assert "trend_data and kpi_keys are required" in str(exc_info.value)
        assert "ValueError" in str(exc_info.value)

    def test_raises_on_timeout(self):
        """Raises PlatformBridgeError on subprocess timeout."""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 300)):
            with pytest.raises(PlatformBridgeError) as exc_info:
                call_action(
                    action="aggregate_kpi",
                    adapter="ins_prod",
                    params={},
                    tenant_id="t1",
                    user_id="u1",
                    timeout=300.0,
                )

        assert "timed out after 300" in str(exc_info.value)

    def test_raises_on_invalid_json(self):
        """Raises PlatformBridgeError when subprocess returns invalid JSON."""
        mock_completed = MagicMock()
        mock_completed.stdout = "not valid json"
        mock_completed.stderr = ""
        mock_completed.returncode = 0

        with patch("subprocess.run", return_value=mock_completed):
            with pytest.raises(PlatformBridgeError) as exc_info:
                call_action(
                    action="select_points",
                    adapter="ins_prod",
                    params={},
                    tenant_id="t1",
                    user_id="u1",
                )

        assert "invalid JSON" in str(exc_info.value)

    def test_uses_env_vars_by_default(self):
        """Falls back to environment variables for tenant_id and user_id."""
        mock_completed = MagicMock()
        mock_completed.stdout = json.dumps({"ok": True, "data": {}})
        mock_completed.stderr = ""
        mock_completed.returncode = 0

        with (
            patch.dict(os.environ, {
                "DEER_FLOW_TENANT_ID": "env-tenant",
                "DEER_FLOW_EFFECTIVE_USER_ID": "env-user",
            }),
            patch("subprocess.run", return_value=mock_completed) as mock_run,
        ):
            call_action(
                action="aggregate_kpi",
                adapter="ins_prod",
                params={},
            )

        cmd = mock_run.call_args[0][0]
        assert "env-tenant" in cmd
        assert "env-user" in cmd

    def test_select_points_action(self):
        """select_points action returns filtered point list."""
        mock_completed = MagicMock()
        mock_completed.stdout = json.dumps({
            "ok": True,
            "data": [
                {"id": "p1", "endpoint_series": "8k", "position_type": 81},
                {"id": "p2", "endpoint_series": "8k", "position_type": 82},
            ],
            "adapter": "ins_prod",
            "action": "select_points",
        })
        mock_completed.stderr = ""
        mock_completed.returncode = 0

        with patch("subprocess.run", return_value=mock_completed):
            result = call_action(
                action="select_points",
                adapter="ins_prod",
                params={
                    "components": [],
                    "kpi_key": "vibration_level",
                    "eq_type": "rotating_machinery",
                },
                tenant_id="t1",
                user_id="u1",
            )

        assert result["ok"] is True
        assert len(result["data"]) == 2
        assert result["data"][0]["id"] == "p1"


class TestCallActionIntegration:
    """Integration tests for call_action with real subprocess (optional)."""

    @pytest.mark.skipif(
        not os.environ.get("RUN_INTEGRATION_TESTS"),
        reason="Set RUN_INTEGRATION_TESTS=1 to enable",
    )
    def test_real_subprocess_aggregate_kpi(self):
        """End-to-end test with real CLI subprocess."""
        result = call_action(
            action="aggregate_kpi",
            adapter="ins_prod",
            params={
                "trend_data": {
                    "EQ1": [
                        {"time_ms": 1000, "values": {"speed": 100}},
                        {"time_ms": 2000, "values": {"speed": 0}},
                        {"time_ms": 3000, "values": {"speed": 100}},
                    ]
                },
                "kpi_keys": ["runtime_rate"],
            },
            tenant_id="test",
            user_id="test",
            timeout=30.0,
        )

        assert result["ok"] is True
        assert "kpis" in result["data"]
        assert "EQ1" in result["data"]["kpis"]
        # 2 out of 3 samples have speed > 0
        assert result["data"]["kpis"]["EQ1"]["runtime_rate"] == pytest.approx(0.6667, rel=1e-3)
