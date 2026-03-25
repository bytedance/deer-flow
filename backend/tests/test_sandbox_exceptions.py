"""Tests for sandbox exception classes."""

import pytest

from deerflow.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
    SandboxCommandError,
    SandboxFileError,
    SandboxPermissionError,
    SandboxFileNotFoundError,
)


class TestSandboxError:
    """Tests for base SandboxError class."""

    def test_basic_message(self):
        """Should store and display basic message."""
        err = SandboxError("Something went wrong")
        assert err.message == "Something went wrong"
        assert str(err) == "Something went wrong"

    def test_message_with_details(self):
        """Should include details in string representation."""
        err = SandboxError("Command failed", details={"cmd": "ls", "code": 1})
        assert err.message == "Command failed"
        assert err.details == {"cmd": "ls", "code": 1}
        str_repr = str(err)
        assert "Command failed" in str_repr
        assert "cmd=ls" in str_repr
        assert "code=1" in str_repr

    def test_empty_details(self):
        """Should handle empty details gracefully."""
        err = SandboxError("Simple error")
        assert err.details == {}

    def test_details_default_to_empty_dict(self):
        """Should default details to empty dict when None."""
        err = SandboxError("Error", details=None)
        assert err.details == {}


class TestSandboxNotFoundError:
    """Tests for SandboxNotFoundError."""

    def test_default_message(self):
        """Should have default message."""
        err = SandboxNotFoundError()
        assert err.message == "Sandbox not found"
        assert err.sandbox_id is None

    def test_custom_message(self):
        """Should accept custom message."""
        err = SandboxNotFoundError("Custom not found message")
        assert err.message == "Custom not found message"

    def test_with_sandbox_id(self):
        """Should store sandbox_id in details."""
        err = SandboxNotFoundError(sandbox_id="sandbox-123")
        assert err.sandbox_id == "sandbox-123"
        assert err.details == {"sandbox_id": "sandbox-123"}
        assert "sandbox-123" in str(err)

    def test_with_message_and_sandbox_id(self):
        """Should accept both message and sandbox_id."""
        err = SandboxNotFoundError("Sandbox expired", sandbox_id="sandbox-456")
        assert err.message == "Sandbox expired"
        assert err.sandbox_id == "sandbox-456"


class TestSandboxRuntimeError:
    """Tests for SandboxRuntimeError."""

    def test_inherits_from_sandbox_error(self):
        """Should inherit from SandboxError."""
        err = SandboxRuntimeError("Runtime error")
        assert isinstance(err, SandboxError)

    def test_basic_message(self):
        """Should handle basic message."""
        err = SandboxRuntimeError("Docker not available")
        assert err.message == "Docker not available"


class TestSandboxCommandError:
    """Tests for SandboxCommandError."""

    def test_basic_message(self):
        """Should store basic message."""
        err = SandboxCommandError("Command failed")
        assert err.message == "Command failed"
        assert err.command is None
        assert err.exit_code is None

    def test_with_command(self):
        """Should store command in details."""
        err = SandboxCommandError("Failed", command="ls -la")
        assert err.command == "ls -la"
        assert err.details == {"command": "ls -la"}
        assert "ls -la" in str(err)

    def test_with_exit_code(self):
        """Should store exit code in details."""
        err = SandboxCommandError("Failed", exit_code=127)
        assert err.exit_code == 127
        assert err.details == {"exit_code": 127}

    def test_with_command_and_exit_code(self):
        """Should store both command and exit code."""
        err = SandboxCommandError("Failed", command="cat file.txt", exit_code=1)
        assert err.command == "cat file.txt"
        assert err.exit_code == 1
        str_repr = str(err)
        assert "command=cat file.txt" in str_repr
        assert "exit_code=1" in str_repr

    def test_long_command_truncation(self):
        """Should truncate very long commands."""
        long_command = "x" * 200
        err = SandboxCommandError("Failed", command=long_command)
        assert len(err.details["command"]) < 200
        assert "..." in err.details["command"]


class TestSandboxFileError:
    """Tests for SandboxFileError."""

    def test_basic_message(self):
        """Should store basic message."""
        err = SandboxFileError("File operation failed")
        assert err.message == "File operation failed"
        assert err.path is None
        assert err.operation is None

    def test_with_path(self):
        """Should store path in details."""
        err = SandboxFileError("Cannot read", path="/tmp/file.txt")
        assert err.path == "/tmp/file.txt"
        assert err.details == {"path": "/tmp/file.txt"}
        assert "/tmp/file.txt" in str(err)

    def test_with_operation(self):
        """Should store operation in details."""
        err = SandboxFileError("Failed", operation="write")
        assert err.operation == "write"
        assert err.details == {"operation": "write"}

    def test_with_path_and_operation(self):
        """Should store both path and operation."""
        err = SandboxFileError("Failed", path="/tmp/file.txt", operation="read")
        assert err.path == "/tmp/file.txt"
        assert err.operation == "read"
        str_repr = str(err)
        assert "path=/tmp/file.txt" in str_repr
        assert "operation=read" in str_repr


class TestSandboxPermissionError:
    """Tests for SandboxPermissionError."""

    def test_inherits_from_sandbox_file_error(self):
        """Should inherit from SandboxFileError."""
        err = SandboxPermissionError("Permission denied")
        assert isinstance(err, SandboxFileError)
        assert isinstance(err, SandboxError)

    def test_with_path(self):
        """Should accept path parameter."""
        err = SandboxPermissionError("Access denied", path="/root/secret.txt")
        assert err.path == "/root/secret.txt"


class TestSandboxFileNotFoundError:
    """Tests for SandboxFileNotFoundError."""

    def test_inherits_from_sandbox_file_error(self):
        """Should inherit from SandboxFileError."""
        err = SandboxFileNotFoundError("File not found")
        assert isinstance(err, SandboxFileError)
        assert isinstance(err, SandboxError)

    def test_with_path(self):
        """Should accept path parameter."""
        err = SandboxFileNotFoundError("Missing file", path="/tmp/missing.txt")
        assert err.path == "/tmp/missing.txt"


class TestExceptionHierarchy:
    """Tests for exception class hierarchy."""

    def test_all_inherit_from_sandbox_error(self):
        """All sandbox exceptions should inherit from SandboxError."""
        exceptions = [
            SandboxNotFoundError,
            SandboxRuntimeError,
            SandboxCommandError,
            SandboxFileError,
            SandboxPermissionError,
            SandboxFileNotFoundError,
        ]
        for exc_class in exceptions:
            err = exc_class("test")
            assert isinstance(err, SandboxError)

    def test_can_be_caught_as_sandbox_error(self):
        """All exceptions should be catchable as SandboxError."""
        with pytest.raises(SandboxError):
            raise SandboxNotFoundError()

        with pytest.raises(SandboxError):
            raise SandboxCommandError("failed")

        with pytest.raises(SandboxError):
            raise SandboxFileError("error")
