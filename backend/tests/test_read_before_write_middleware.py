"""Tests for the read-before-write gate (issue #3857, output layer)."""

from unittest.mock import MagicMock, patch

import pytest


class TestReadCurrentFileContent:
    def test_reads_via_sandbox_with_resolution(self):
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.return_value = "hello"
        runtime = MagicMock()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            assert sandbox_tools.read_current_file_content(runtime, "/mnt/user-data/outputs/report.md") == "hello"
        sandbox.read_file.assert_called_once_with("/mnt/user-data/outputs/report.md")

    def test_propagates_file_not_found(self):
        from deerflow.sandbox import tools as sandbox_tools

        sandbox = MagicMock()
        sandbox.read_file.side_effect = FileNotFoundError()
        with (
            patch.object(sandbox_tools, "ensure_sandbox_initialized", return_value=sandbox),
            patch.object(sandbox_tools, "ensure_thread_directories_exist"),
            patch.object(sandbox_tools, "is_local_sandbox", return_value=False),
        ):
            with pytest.raises(FileNotFoundError):
                sandbox_tools.read_current_file_content(MagicMock(), "/mnt/user-data/outputs/missing.md")
