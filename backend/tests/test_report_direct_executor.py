"""Tests for DirectReportExecutor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from deerflow.report_executor import (
    DirectReportExecutor,
    NoDataError,
    ScriptFailedError,
)


class TestDirectReportExecutor:
    """Test suite for DirectReportExecutor."""

    def test_init_creates_output_dir(self, tmp_path):
        """Test that __init__ creates output directory."""
        output_dir = tmp_path / "outputs"
        executor = DirectReportExecutor(output_dir=str(output_dir))
        assert output_dir.exists()
        assert executor.output_dir == output_dir

    def test_execute_invalid_report_type(self, tmp_path):
        """Test that invalid report_type raises ValueError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        with pytest.raises(ValueError, match="Unknown report_type"):
            executor.execute(report_type="invalid", scope={})

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_daily_success(self, mock_subprocess, tmp_path):
        """Test successful daily report execution."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))

        mock_data = {"kpi_summary": [{"name": "运行率", "value": 95.5}]}
        mock_subprocess.return_value = json.dumps(mock_data)

        result = executor.execute(
            report_type="daily",
            scope={"report_date": "2026-06-08"},
            equipment_type="all",
        )

        assert result["status"] == "success"
        assert result["report_run_id"].startswith("rr_")
        assert len(result["artifacts"]) == 3
        assert mock_subprocess.call_count == 3

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_weekly_success(self, mock_subprocess, tmp_path):
        """Test successful weekly report execution."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_subprocess.return_value = json.dumps({"data": "test"})

        result = executor.execute(
            report_type="weekly",
            scope={"week_start": "2026-06-01", "date_end": "2026-06-07"},
        )

        assert result["status"] == "success"
        assert len(result["artifacts"]) == 3

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_monthly_success(self, mock_subprocess, tmp_path):
        """Test successful monthly report execution."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_subprocess.return_value = json.dumps({"data": "test"})

        result = executor.execute(
            report_type="monthly",
            scope={"report_month": "2026-06"},
        )

        assert result["status"] == "success"

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_script_failure(self, mock_subprocess, tmp_path):
        """Test that script failure raises ScriptFailedError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_subprocess.side_effect = ScriptFailedError("Script failed", step="query_daily.py")

        with pytest.raises(ScriptFailedError, match="Script failed"):
            executor.execute(
                report_type="daily",
                scope={"report_date": "2026-06-08"},
            )

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_no_data(self, mock_subprocess, tmp_path):
        """Test that empty data raises NoDataError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_subprocess.side_effect = NoDataError("No data", step="query_daily.py")

        with pytest.raises(NoDataError, match="No data"):
            executor.execute(
                report_type="daily",
                scope={"report_date": "2026-06-08"},
            )

    def test_build_scope_args_daily(self, tmp_path):
        """Test scope args for daily report."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        args = executor._build_scope_args("daily", {"report_date": "2026-06-08"})
        assert args == ["--date", "2026-06-08"]

    def test_build_scope_args_weekly(self, tmp_path):
        """Test scope args for weekly report."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        args = executor._build_scope_args(
            "weekly",
            {"week_start": "2026-06-01", "date_end": "2026-06-07"},
        )
        assert args == ["--week-start", "2026-06-01"]

    def test_build_scope_args_monthly(self, tmp_path):
        """Test scope args for monthly report."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        args = executor._build_scope_args("monthly", {"report_month": "2026-06"})
        assert args == ["--report-month", "2026-06"]

    @patch("subprocess.run")
    def test_run_subprocess_success(self, mock_run, tmp_path):
        """Test successful subprocess execution."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_run.return_value = MagicMock(returncode=0, stdout='{"data": "test"}', stderr="")

        stdout = executor._run_subprocess(["python", "test.py"], step="test.py")
        assert stdout == '{"data": "test"}'

    @patch("subprocess.run")
    def test_run_subprocess_failure(self, mock_run, tmp_path):
        """Test subprocess failure raises ScriptFailedError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Error occurred")

        with pytest.raises(ScriptFailedError, match="exited with code 1"):
            executor._run_subprocess(["python", "test.py"], step="test.py")

    def test_validate_script_output_valid_json(self, tmp_path):
        """Test validation of valid JSON output."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        executor._validate_script_output('{"data": "test"}', step="test.py")

    def test_validate_script_output_invalid_json(self, tmp_path):
        """Test validation of invalid JSON raises ScriptFailedError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        with pytest.raises(ScriptFailedError, match="not valid JSON"):
            executor._validate_script_output("not json", step="test.py")

    def test_validate_script_output_error_field(self, tmp_path):
        """Test validation of JSON with error field raises ScriptFailedError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        with pytest.raises(ScriptFailedError, match="returned error"):
            executor._validate_script_output('{"error": "Something went wrong"}', step="test.py")

    def test_validate_script_output_empty_dict(self, tmp_path):
        """Test validation of empty dict raises NoDataError."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        with pytest.raises(NoDataError, match="empty data"):
            executor._validate_script_output("{}", step="test.py")

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_weekly_with_equipment_meta(self, mock_subprocess, tmp_path):
        """Test weekly report execution with equipment_meta parameter."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))

        # Create dummy output files
        data_file = tmp_path / "weekly_data.json"
        data_file.write_text("{}")
        kpi_file = tmp_path / "weekly_kpi.json"
        kpi_file.write_text("{}")
        report_file = tmp_path / "weekly_report.md"
        report_file.write_text("")

        mock_subprocess.side_effect = [
            json.dumps({"output": str(data_file)}),
            json.dumps({"output": str(kpi_file)}),
            json.dumps({"output": str(report_file)}),
        ]

        equipment_meta = {
            "eq1": {"id": "eq1", "name": "设备1"},
            "eq2": {"id": "eq2", "name": "设备2"},
        }

        result = executor.execute(
            report_type="weekly",
            scope={"week_start": "2026-06-01", "date_end": "2026-06-07"},
            equipment_ids=["eq1", "eq2"],
            equipment_labels=["设备1", "设备2"],
            equipment_meta=equipment_meta,
        )

        assert result["status"] == "success"
        assert mock_subprocess.call_count == 3

        first_call_args = mock_subprocess.call_args_list[0][0][0]
        assert "--equipment-meta" in first_call_args

    @patch("deerflow.report_executor.executor.DirectReportExecutor._run_subprocess")
    def test_execute_monthly_with_equipment_meta(self, mock_subprocess, tmp_path):
        """Test monthly report execution with equipment_meta parameter."""
        executor = DirectReportExecutor(output_dir=str(tmp_path))

        # Create dummy output files
        data_file = tmp_path / "monthly_data.json"
        data_file.write_text("{}")
        kpi_file = tmp_path / "monthly_kpi.json"
        kpi_file.write_text("{}")
        report_file = tmp_path / "monthly_report.md"
        report_file.write_text("")

        mock_subprocess.side_effect = [
            json.dumps({"output": str(data_file)}),
            json.dumps({"output": str(kpi_file)}),
            json.dumps({"output": str(report_file)}),
        ]

        equipment_meta = {
            "pump1": {"id": "pump1", "name": "泵1"},
        }

        result = executor.execute(
            report_type="monthly",
            scope={"report_month": "2026-06"},
            equipment_ids=["pump1"],
            equipment_labels=["泵1"],
            equipment_meta=equipment_meta,
        )

        assert result["status"] == "success"
        first_call_args = mock_subprocess.call_args_list[0][0][0]
        assert "--equipment-meta" in first_call_args

    @patch("subprocess.run")
    def test_execute_passes_report_run_id_env(self, mock_run, tmp_path):
        """Test that report subprocess receives runtime environment variables."""
        executor = DirectReportExecutor(output_dir=str(tmp_path), access_token="  bearer-token  ")

        # Create dummy output files
        data_file = tmp_path / "daily_data.json"
        data_file.write_text("{}")
        kpi_file = tmp_path / "daily_kpi.json"
        kpi_file.write_text("{}")
        report_file = tmp_path / "daily_report.md"
        report_file.write_text("")

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=json.dumps({"output": str(data_file)}), stderr=""),
            MagicMock(returncode=0, stdout=json.dumps({"output": str(kpi_file)}), stderr=""),
            MagicMock(returncode=0, stdout=json.dumps({"output": str(report_file)}), stderr=""),
        ]

        result = executor.execute(
            report_type="daily",
            scope={"report_date": "2026-06-08"},
        )

        assert result["status"] == "success"
        assert result["report_run_id"].startswith("rr_")

        # Check that subprocess.run was called with env containing REPORT_RUN_ID and FEATURES_TOOL_ROOT
        first_call_kwargs = mock_run.call_args_list[0][1]
        assert "env" in first_call_kwargs
        assert "REPORT_RUN_ID" in first_call_kwargs["env"]
        assert first_call_kwargs["env"]["REPORT_RUN_ID"] == result["report_run_id"]
        assert "FEATURES_TOOL_ROOT" in first_call_kwargs["env"]
        assert first_call_kwargs["env"]["FEATURES_TOOL_ROOT"].endswith("custom/features-tool")
        assert first_call_kwargs["env"]["INS_ACCESS_TOKEN"] == "bearer-token"
