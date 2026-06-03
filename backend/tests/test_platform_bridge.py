"""Unit tests for ``_platform_bridge.py`` and script USE_PLATFORM routing.

Covers tasks 2.2.4 / 2.2.5 / 2.2.9 of external-systems-integration:
- ``is_platform_mode()`` detects USE_PLATFORM env var
- ``call_capability()`` builds CLI command and parses JSON output
- ``call_capability()`` error handling (timeout, empty stdout, bad JSON, ok=false)
- Fallback: scripts catch PlatformBridgeError and fall through to legacy
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "skills" / "custom" / "data-analyst" / "scripts")
_DAILY_SCRIPTS_DIR = str(Path(__file__).resolve().parents[2] / "skills" / "custom" / "daily-report" / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import _platform_bridge as pb  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# is_platform_mode
# ---------------------------------------------------------------------------


class TestIsPlatformMode:
    def test_true_values(self, monkeypatch):
        for val in ("true", "1", "yes", "True", "YES"):
            monkeypatch.setenv("USE_PLATFORM", val)
            assert pb.is_platform_mode() is True, f"expected True for {val!r}"

    def test_false_values(self, monkeypatch):
        for val in ("false", "0", "no", ""):
            monkeypatch.setenv("USE_PLATFORM", val)
            assert pb.is_platform_mode() is False, f"expected False for {val!r}"

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("USE_PLATFORM", raising=False)
        assert pb.is_platform_mode() is False


# ---------------------------------------------------------------------------
# _build_cli_command
# ---------------------------------------------------------------------------


class TestBuildCliCommand:
    def test_basic_command(self):
        cmd = pb._build_cli_command(
            capability="monitoring.trend",
            tenant_id="t1",
            user_id="u1",
            params={"date_str": "2026-05-20"},
            python_executable="/usr/bin/python3",
        )
        assert cmd[0] == "/usr/bin/python3"
        assert "-m" in cmd
        assert "deerflow.integrations.cli" in cmd
        assert "--capability" in cmd
        assert "monitoring.trend" in cmd
        assert "--tenant-id" in cmd
        assert "t1" in cmd
        assert "--user-id" in cmd
        assert "u1" in cmd
        assert "--params" in cmd
        params_idx = cmd.index("--params")
        parsed = json.loads(cmd[params_idx + 1])
        assert parsed == {"date_str": "2026-05-20"}

    def test_default_python_executable(self):
        cmd = pb._build_cli_command(
            capability="asset.catalog",
            tenant_id="t",
            user_id="u",
            params={},
        )
        assert cmd[0] == sys.executable


# ---------------------------------------------------------------------------
# call_capability — success path
# ---------------------------------------------------------------------------


class TestCallCapabilitySuccess:
    def test_parses_ok_json(self, monkeypatch):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"ok": True, "data": [1, 2, 3]})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            result = pb.call_capability(
                capability="monitoring.trend",
                params={"date_str": "2026-05-20"},
                tenant_id="t1",
                user_id="u1",
            )

        assert result["ok"] is True
        assert result["data"] == [1, 2, 3]
        mock_run.assert_called_once()

    def test_tenant_id_from_env(self, monkeypatch):
        monkeypatch.setenv("DEER_FLOW_TENANT_ID", "env_tenant")
        monkeypatch.setenv("DEER_FLOW_EFFECTIVE_USER_ID", "env_user")

        mock_result = MagicMock()
        mock_result.stdout = json.dumps({"ok": True, "data": {}})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            pb.call_capability(capability="asset.catalog", params={})

        cmd = mock_run.call_args[0][0]
        tenant_idx = cmd.index("--tenant-id")
        assert cmd[tenant_idx + 1] == "env_tenant"
        user_idx = cmd.index("--user-id")
        assert cmd[user_idx + 1] == "env_user"


# ---------------------------------------------------------------------------
# call_capability — error paths
# ---------------------------------------------------------------------------


class TestCallCapabilityErrors:
    def test_timeout_raises(self):
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=5)):
            with pytest.raises(pb.PlatformBridgeError, match="timed out"):
                pb.call_capability(capability="x", params={}, timeout=5)

    def test_os_error_raises(self):
        with patch("subprocess.run", side_effect=OSError("no such file")):
            with pytest.raises(pb.PlatformBridgeError, match="Failed to launch"):
                pb.call_capability(capability="x", params={})

    def test_empty_stdout_raises(self):
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "some error"
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(pb.PlatformBridgeError, match="no stdout"):
                pb.call_capability(capability="x", params={})

    def test_invalid_json_raises(self):
        mock_result = MagicMock()
        mock_result.stdout = "not json at all"
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(pb.PlatformBridgeError, match="invalid JSON"):
                pb.call_capability(capability="x", params={})

    def test_non_dict_raises(self):
        mock_result = MagicMock()
        mock_result.stdout = json.dumps([1, 2, 3])
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(pb.PlatformBridgeError, match="non-dict"):
                pb.call_capability(capability="x", params={})

    def test_ok_false_raises(self):
        mock_result = MagicMock()
        mock_result.stdout = json.dumps({
            "ok": False,
            "error": "route not found",
            "error_type": "CapabilityRouteNotFoundError",
        })
        mock_result.stderr = ""
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(pb.PlatformBridgeError, match="route not found"):
                pb.call_capability(capability="x", params={})


# ---------------------------------------------------------------------------
# Script-level fallback (USE_PLATFORM=true → platform bridge fails → legacy)
# ---------------------------------------------------------------------------


class TestScriptPlatformFallback:
    """Verify query scripts fall back to legacy when platform bridge fails."""

    @pytest.fixture(autouse=True)
    def _add_daily_path(self):
        if _DAILY_SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _DAILY_SCRIPTS_DIR)

    def test_daily_fallback_on_platform_error(self, monkeypatch):
        """When USE_PLATFORM=true and platform bridge raises, daily falls through."""
        monkeypatch.setenv("USE_PLATFORM", "true")

        mock_legacy = MagicMock()
        mock_legacy.get_provider.return_value = MagicMock()
        mock_result = MagicMock()
        mock_result.data = {"kpis": {"runtime_rate": 0.95}, "kpi_units": {}, "alarms": []}
        mock_result.data_source = "ins"
        mock_result.notes = []
        mock_legacy.ProviderResult = type(mock_result)
        mock_legacy.get_provider.return_value.fetch.return_value = mock_result

        with patch.dict(sys.modules, {"_data_providers": mock_legacy}):
            with patch("_platform_bridge.call_capability", side_effect=pb.PlatformBridgeError("bridge down")):
                import query_daily as qd  # type: ignore[import-not-found]

                data, source, notes = qd.fetch_day_with_provenance(
                    date_str="2026-05-20",
                    equipment_ids=["E001"],
                    kpi_keys=["runtime_rate"],
                )
                assert source == "ins"
