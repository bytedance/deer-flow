"""Tests for AioSandbox: HTTP client wrapper with error handling."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# Mock the agent_sandbox import since it may not be installed in test env
@pytest.fixture(autouse=True)
def _mock_agent_sandbox():
    """Provide a mock for the agent_sandbox package."""
    import sys

    mock_module = MagicMock()
    saved = sys.modules.get("agent_sandbox")
    sys.modules["agent_sandbox"] = mock_module
    yield
    if saved is not None:
        sys.modules["agent_sandbox"] = saved
    else:
        sys.modules.pop("agent_sandbox", None)


def _make_sandbox():
    """Create an AioSandbox with a mocked client."""
    # Import after mocking agent_sandbox
    import importlib

    import src.community.aio_sandbox.aio_sandbox as mod

    importlib.reload(mod)
    AioSandbox = mod.AioSandbox

    sandbox = AioSandbox.__new__(AioSandbox)
    sandbox._id = "test-sandbox"
    sandbox._base_url = "http://localhost:8080"
    sandbox._client = MagicMock()
    sandbox._home_dir = "/home/user"
    return sandbox


# ---------------------------------------------------------------------------
# execute_command
# ---------------------------------------------------------------------------
class TestExecuteCommand:
    """Tests for AioSandbox.execute_command()."""

    def test_success(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.shell.exec_command.return_value = SimpleNamespace(data=SimpleNamespace(output="result"))
        assert sandbox.execute_command("echo hello") == "result"

    def test_error_returns_string(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.shell.exec_command.side_effect = RuntimeError("connection failed")
        result = sandbox.execute_command("echo hello")
        assert result.startswith("Error:")
        assert "connection failed" in result

    def test_empty_output(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.shell.exec_command.return_value = SimpleNamespace(data=SimpleNamespace(output=""))
        assert sandbox.execute_command("true") == "(no output)"

    def test_none_data(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.shell.exec_command.return_value = SimpleNamespace(data=None)
        assert sandbox.execute_command("true") == "(no output)"


# ---------------------------------------------------------------------------
# read_file / _read_file_raw
# ---------------------------------------------------------------------------
class TestReadFile:
    """Tests for AioSandbox.read_file() and _read_file_raw()."""

    def test_read_file_success(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.return_value = SimpleNamespace(data=SimpleNamespace(content="hello"))
        assert sandbox.read_file("/tmp/test.txt") == "hello"

    def test_read_file_error_returns_string(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.side_effect = FileNotFoundError("not found")
        result = sandbox.read_file("/tmp/missing.txt")
        assert result.startswith("Error:")
        assert "not found" in result

    def test_read_file_raw_raises_on_error(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.side_effect = FileNotFoundError("not found")
        with pytest.raises(FileNotFoundError, match="not found"):
            sandbox._read_file_raw("/tmp/missing.txt")

    def test_read_file_raw_success(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.return_value = SimpleNamespace(data=SimpleNamespace(content="content"))
        assert sandbox._read_file_raw("/tmp/test.txt") == "content"


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------
class TestWriteFile:
    """Tests for AioSandbox.write_file() with append mode."""

    def test_write_file_no_append(self) -> None:
        sandbox = _make_sandbox()
        sandbox.write_file("/tmp/test.txt", "overwrite", append=False)
        sandbox._client.file.write_file.assert_called_once_with(file="/tmp/test.txt", content="overwrite")
        # read_file should NOT have been called
        sandbox._client.file.read_file.assert_not_called()

    def test_write_file_append_concatenates(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.return_value = SimpleNamespace(data=SimpleNamespace(content="first "))
        sandbox.write_file("/tmp/test.txt", "second", append=True)
        sandbox._client.file.write_file.assert_called_once_with(file="/tmp/test.txt", content="first second")

    def test_write_file_append_new_file(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.side_effect = FileNotFoundError("not found")
        sandbox.write_file("/tmp/new.txt", "new content", append=True)
        # Should write only the new content since file doesn't exist
        sandbox._client.file.write_file.assert_called_once_with(file="/tmp/new.txt", content="new content")

    def test_write_file_append_preserves_error_prefix_content(self) -> None:
        """Key regression test: files starting with 'Error:' should not be discarded."""
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.return_value = SimpleNamespace(data=SimpleNamespace(content="Error: this is valid content"))
        sandbox.write_file("/tmp/test.txt", " more", append=True)
        # Should concatenate, NOT discard existing content
        sandbox._client.file.write_file.assert_called_once_with(file="/tmp/test.txt", content="Error: this is valid content more")

    def test_write_file_append_with_empty_existing(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.read_file.return_value = SimpleNamespace(data=SimpleNamespace(content=""))
        sandbox.write_file("/tmp/test.txt", "new", append=True)
        sandbox._client.file.write_file.assert_called_once_with(file="/tmp/test.txt", content="new")

    def test_write_file_raises_on_write_error(self) -> None:
        sandbox = _make_sandbox()
        sandbox._client.file.write_file.side_effect = RuntimeError("disk full")
        with pytest.raises(RuntimeError, match="disk full"):
            sandbox.write_file("/tmp/test.txt", "content")
