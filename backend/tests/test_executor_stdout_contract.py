"""Tests for DirectReportExecutor stdout contract resolution.

Verifies that the executor correctly parses script stdout metadata
``{"output": "<path>", ...}`` to locate actual data files instead of
overwriting them with stdout content.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.report_executor import (
    DirectReportExecutor,
    ScriptFailedError,
)


class TestResolveOutputPath:
    """Test suite for _resolve_output_path."""

    def test_returns_path_from_output_field(self, tmp_path: Path) -> None:
        actual_data = tmp_path / "actual_data.json"
        actual_data.write_text('{"real": "data"}', encoding="utf-8")

        executor = DirectReportExecutor(output_dir=str(tmp_path))
        stdout = json.dumps({"output": str(actual_data), "report_date": "2026-06-08"})

        result = executor._resolve_output_path(stdout, step="query_daily.py", fallback=tmp_path / "fallback.json")
        assert result == actual_data

    def test_returns_fallback_when_no_output_field(self, tmp_path: Path) -> None:
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        stdout = json.dumps({"report_date": "2026-06-08", "kpi_keys": ["runtime_rate"]})
        fallback = tmp_path / "fallback.json"

        result = executor._resolve_output_path(stdout, step="query_daily.py", fallback=fallback)
        assert result == fallback

    def test_raises_when_output_file_missing(self, tmp_path: Path) -> None:
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        nonexistent = tmp_path / "does_not_exist.json"
        stdout = json.dumps({"output": str(nonexistent)})

        with pytest.raises(ScriptFailedError, match="does not exist"):
            executor._resolve_output_path(stdout, step="query_daily.py", fallback=tmp_path / "fallback.json")

    def test_returns_fallback_on_invalid_json(self, tmp_path: Path) -> None:
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        fallback = tmp_path / "fallback.json"

        result = executor._resolve_output_path("not json at all", step="query_daily.py", fallback=fallback)
        assert result == fallback

    def test_returns_fallback_when_output_is_empty(self, tmp_path: Path) -> None:
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        stdout = json.dumps({"output": ""})
        fallback = tmp_path / "fallback.json"

        result = executor._resolve_output_path(stdout, step="query_daily.py", fallback=fallback)
        assert result == fallback

    def test_returns_fallback_when_stdout_not_dict(self, tmp_path: Path) -> None:
        executor = DirectReportExecutor(output_dir=str(tmp_path))
        stdout = json.dumps([1, 2, 3])
        fallback = tmp_path / "fallback.json"

        result = executor._resolve_output_path(stdout, step="query_daily.py", fallback=fallback)
        assert result == fallback
