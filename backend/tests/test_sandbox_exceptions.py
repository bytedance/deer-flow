"""Tests for deerflow.sandbox.exceptions — structured sandbox error hierarchy.

Verifies the exception class hierarchy, __str__ formatting with details,
field storage, and that exceptions can be caught by parent types.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure heavy dependencies are mocked before importing deerflow modules.
# ---------------------------------------------------------------------------
for _mod in ("yaml", "dotenv", "langchain", "langchain_core", "langchain_core.tools"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

_harness_path = str(Path(__file__).resolve().parents[1] / "packages" / "harness")
if _harness_path not in sys.path:
    sys.path.insert(0, _harness_path)

from deerflow.sandbox.exceptions import (  # noqa: E402
    SandboxCommandError,
    SandboxError,
    SandboxFileError,
    SandboxFileNotFoundError,
    SandboxNotFoundError,
    SandboxPermissionError,
    SandboxRuntimeError,
)


# ---------------------------------------------------------------------------
# SandboxError (base)
# ---------------------------------------------------------------------------


class TestSandboxError:
    def test_message_only(self):
        err = SandboxError("something failed")
        assert str(err) == "something failed"
        assert err.message == "something failed"
        assert err.details == {}

    def test_message_with_details(self):
        err = SandboxError("failed", details={"code": 42, "reason": "timeout"})
        assert "code=42" in str(err)
        assert "reason=timeout" in str(err)
        assert err.details == {"code": 42, "reason": "timeout"}

    def test_is_exception(self):
        err = SandboxError("test")
        assert isinstance(err, Exception)

    def test_none_details_becomes_empty_dict(self):
        err = SandboxError("msg", details=None)
        assert err.details == {}


# ---------------------------------------------------------------------------
# SandboxNotFoundError
# ---------------------------------------------------------------------------


class TestSandboxNotFoundError:
    def test_default_message(self):
        err = SandboxNotFoundError()
        assert str(err) == "Sandbox not found"
        assert err.sandbox_id is None

    def test_with_sandbox_id(self):
        err = SandboxNotFoundError(sandbox_id="sb-123")
        assert "sandbox_id=sb-123" in str(err)
        assert err.sandbox_id == "sb-123"

    def test_custom_message(self):
        err = SandboxNotFoundError("custom msg", sandbox_id="sb-456")
        assert "custom msg" in str(err)
        assert err.sandbox_id == "sb-456"

    def test_inherits_sandbox_error(self):
        err = SandboxNotFoundError()
        assert isinstance(err, SandboxError)


# ---------------------------------------------------------------------------
# SandboxRuntimeError
# ---------------------------------------------------------------------------


class TestSandboxRuntimeError:
    def test_basic(self):
        err = SandboxRuntimeError("runtime not configured")
        assert str(err) == "runtime not configured"

    def test_inherits_sandbox_error(self):
        assert issubclass(SandboxRuntimeError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxCommandError
# ---------------------------------------------------------------------------


class TestSandboxCommandError:
    def test_message_only(self):
        err = SandboxCommandError("cmd failed")
        assert str(err) == "cmd failed"
        assert err.command is None
        assert err.exit_code is None

    def test_with_command_and_exit_code(self):
        err = SandboxCommandError("failed", command="ls -la", exit_code=1)
        assert "command=ls -la" in str(err)
        assert "exit_code=1" in str(err)

    def test_long_command_truncated(self):
        long_cmd = "x" * 200
        err = SandboxCommandError("failed", command=long_cmd)
        assert err.details["command"] == "x" * 100 + "..."

    def test_short_command_not_truncated(self):
        err = SandboxCommandError("failed", command="ls")
        assert err.details["command"] == "ls"

    def test_exit_code_zero(self):
        err = SandboxCommandError("unexpected", exit_code=0)
        assert err.exit_code == 0
        assert "exit_code=0" in str(err)

    def test_inherits_sandbox_error(self):
        assert issubclass(SandboxCommandError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxFileError
# ---------------------------------------------------------------------------


class TestSandboxFileError:
    def test_message_only(self):
        err = SandboxFileError("file error")
        assert str(err) == "file error"
        assert err.path is None
        assert err.operation is None

    def test_with_path_and_operation(self):
        err = SandboxFileError("failed", path="/tmp/file.txt", operation="read")
        assert "path=/tmp/file.txt" in str(err)
        assert "operation=read" in str(err)

    def test_inherits_sandbox_error(self):
        assert issubclass(SandboxFileError, SandboxError)


# ---------------------------------------------------------------------------
# SandboxPermissionError
# ---------------------------------------------------------------------------


class TestSandboxPermissionError:
    def test_inherits_file_error(self):
        assert issubclass(SandboxPermissionError, SandboxFileError)

    def test_instantiation(self):
        err = SandboxPermissionError("no access", path="/secret", operation="write")
        assert "no access" in str(err)
        assert err.path == "/secret"
        assert err.operation == "write"


# ---------------------------------------------------------------------------
# SandboxFileNotFoundError
# ---------------------------------------------------------------------------


class TestSandboxFileNotFoundError:
    def test_inherits_file_error(self):
        assert issubclass(SandboxFileNotFoundError, SandboxFileError)

    def test_instantiation(self):
        err = SandboxFileNotFoundError("missing", path="/gone.txt", operation="open")
        assert err.path == "/gone.txt"
        assert err.operation == "open"


# ---------------------------------------------------------------------------
# Exception hierarchy — can be caught by parent type
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    def test_catch_not_found_as_sandbox_error(self):
        with pytest.raises(SandboxError):
            raise SandboxNotFoundError("gone")

    def test_catch_command_error_as_sandbox_error(self):
        with pytest.raises(SandboxError):
            raise SandboxCommandError("boom")

    def test_catch_permission_error_as_file_error(self):
        with pytest.raises(SandboxFileError):
            raise SandboxPermissionError("denied")

    def test_catch_file_not_found_as_file_error(self):
        with pytest.raises(SandboxFileError):
            raise SandboxFileNotFoundError("missing")

    def test_catch_file_not_found_as_sandbox_error(self):
        with pytest.raises(SandboxError):
            raise SandboxFileNotFoundError("missing")
