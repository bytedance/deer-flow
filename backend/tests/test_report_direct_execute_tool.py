"""Tests for report_direct_execute tool."""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock

import pytest

from deerflow.tools.builtins.report_direct_tools import report_direct_execute


class TestReportDirectExecuteTool:
    """Test suite for report_direct_execute LangChain tool."""

    @patch("deerflow.tools.builtins.report_direct_tools.DirectReportExecutor")
    @patch("deerflow.tools.builtins.report_direct_tools.get_config")
    def test_tool_success(self, mock_get_config, mock_executor_class):
        """Test successful tool execution."""
        mock_get_config.return_value = {"configurable": {"thread_id": "test-thread"}}
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {
            "report_run_id": "rr_test123",
            "artifacts": [
                {"path": "/mnt/user-data/outputs/daily_data.json", "type": "data"},
                {"path": "/mnt/user-data/outputs/daily_report.md", "type": "report"},
            ],
            "status": "success",
        }
        mock_executor_class.return_value = mock_executor

        result = report_direct_execute.invoke(
            {
                "report_type": "daily",
                "scope": {"report_date": "2026-06-08"},
                "equipment_type": "all",
            }
        )

        result_data = json.loads(result)
        assert result_data["status"] == "success"
        assert result_data["report_run_id"] == "rr_test123"
        assert len(result_data["artifacts"]) == 2
        mock_executor.execute.assert_called_once()

    @patch("deerflow.tools.builtins.report_direct_tools.DirectReportExecutor")
    @patch("deerflow.tools.builtins.report_direct_tools.get_config")
    def test_tool_script_failure(self, mock_get_config, mock_executor_class):
        """Test tool handles script failure."""
        from deerflow.report_executor import ScriptFailedError

        mock_get_config.return_value = {"configurable": {"thread_id": "test-thread"}}
        mock_executor = MagicMock()
        mock_executor.execute.side_effect = ScriptFailedError("Script failed", step="query_daily.py")
        mock_executor_class.return_value = mock_executor

        result = report_direct_execute.invoke(
            {
                "report_type": "daily",
                "scope": {"report_date": "2026-06-08"},
            }
        )

        result_data = json.loads(result)
        assert result_data["status"] == "failed"
        assert result_data["error"]["code"] == "SCRIPT_FAILED"
        assert result_data["error"]["step"] == "query_daily.py"

    @patch("deerflow.tools.builtins.report_direct_tools.DirectReportExecutor")
    @patch("deerflow.tools.builtins.report_direct_tools.get_config")
    def test_tool_no_data(self, mock_get_config, mock_executor_class):
        """Test tool handles no data error."""
        from deerflow.report_executor import NoDataError

        mock_get_config.return_value = {"configurable": {"thread_id": "test-thread"}}
        mock_executor = MagicMock()
        mock_executor.execute.side_effect = NoDataError("No data", step="query_daily.py")
        mock_executor_class.return_value = mock_executor

        result = report_direct_execute.invoke(
            {
                "report_type": "daily",
                "scope": {"report_date": "2026-06-08"},
            }
        )

        result_data = json.loads(result)
        assert result_data["status"] == "failed"
        assert result_data["error"]["code"] == "NO_DATA"

    @patch("deerflow.tools.builtins.report_direct_tools.DirectReportExecutor")
    @patch("deerflow.tools.builtins.report_direct_tools.get_config")
    def test_tool_unexpected_error(self, mock_get_config, mock_executor_class):
        """Test tool handles unexpected errors."""
        mock_get_config.return_value = {"configurable": {"thread_id": "test-thread"}}
        mock_executor = MagicMock()
        mock_executor.execute.side_effect = RuntimeError("Unexpected error")
        mock_executor_class.return_value = mock_executor

        result = report_direct_execute.invoke(
            {
                "report_type": "daily",
                "scope": {"report_date": "2026-06-08"},
            }
        )

        result_data = json.loads(result)
        assert result_data["status"] == "failed"
        assert result_data["error"]["code"] == "INTERNAL_ERROR"

    @patch("deerflow.tools.builtins.report_direct_tools.DirectReportExecutor")
    @patch("deerflow.tools.builtins.report_direct_tools.get_config")
    def test_tool_with_all_parameters(self, mock_get_config, mock_executor_class):
        """Test tool with all parameters specified."""
        mock_get_config.return_value = {"configurable": {"thread_id": "test-thread"}}
        mock_executor = MagicMock()
        mock_executor.execute.return_value = {
            "report_run_id": "rr_test456",
            "artifacts": [],
            "status": "success",
        }
        mock_executor_class.return_value = mock_executor

        result = report_direct_execute.invoke(
            {
                "report_type": "weekly",
                "scope": {"week_start": "2026-06-01", "date_end": "2026-06-07"},
                "equipment_type": "rotating_machinery",
                "compare_with": "previous_week",
                "equipment_ids": ["P-203A", "T-501A"],
                "equipment_labels": ["进料泵P-203A", "塔T-501A"],
                "kpi_keys": ["runtime_rate", "alarm_count"],
            }
        )

        result_data = json.loads(result)
        assert result_data["status"] == "success"

        call_kwargs = mock_executor.execute.call_args[1]
        assert call_kwargs["report_type"] == "weekly"
        assert call_kwargs["scope"] == {"week_start": "2026-06-01", "date_end": "2026-06-07"}
        assert call_kwargs["equipment_type"] == "rotating_machinery"
        assert call_kwargs["compare_with"] == "previous_week"
        assert call_kwargs["equipment_ids"] == ["P-203A", "T-501A"]
        assert call_kwargs["equipment_labels"] == ["进料泵P-203A", "塔T-501A"]
        assert call_kwargs["kpi_keys"] == ["runtime_rate", "alarm_count"]
