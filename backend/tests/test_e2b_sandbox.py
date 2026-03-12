"""Tests for E2B sandbox provider and sandbox implementations."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Mock e2b before importing our modules
mock_e2b = MagicMock()
sys.modules["e2b"] = mock_e2b


from src.community.e2b_sandbox.e2b_sandbox import E2bSandbox
from src.community.e2b_sandbox.e2b_sandbox_provider import E2bSandboxProvider
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import SandboxProvider


class TestE2bSandbox:
    """Tests for E2bSandbox class."""

    def _make_sandbox(self):
        client = MagicMock()
        return E2bSandbox(id="test-sandbox-123", client=client), client

    def test_is_sandbox_subclass(self):
        assert issubclass(E2bSandbox, Sandbox)

    def test_id_property(self):
        sandbox, _ = self._make_sandbox()
        assert sandbox.id == "test-sandbox-123"

    def test_client_property(self):
        sandbox, client = self._make_sandbox()
        assert sandbox.client is client

    def test_execute_command_stdout_only(self):
        sandbox, client = self._make_sandbox()
        result = MagicMock()
        result.stdout = "hello world"
        result.stderr = ""
        result.exit_code = 0
        client.commands.run.return_value = result

        output = sandbox.execute_command("echo hello world")

        client.commands.run.assert_called_once_with(cmd="echo hello world", timeout=600)
        assert output == "hello world"

    def test_execute_command_with_stderr(self):
        sandbox, client = self._make_sandbox()
        result = MagicMock()
        result.stdout = "output"
        result.stderr = "warning"
        result.exit_code = 0
        client.commands.run.return_value = result

        output = sandbox.execute_command("some-cmd")
        assert "output" in output
        assert "Std Error:" in output
        assert "warning" in output

    def test_execute_command_nonzero_exit(self):
        sandbox, client = self._make_sandbox()
        result = MagicMock()
        result.stdout = ""
        result.stderr = "not found"
        result.exit_code = 1
        client.commands.run.return_value = result

        output = sandbox.execute_command("bad-cmd")
        assert "Exit Code: 1" in output

    def test_execute_command_no_output(self):
        sandbox, client = self._make_sandbox()
        result = MagicMock()
        result.stdout = ""
        result.stderr = ""
        result.exit_code = 0
        client.commands.run.return_value = result

        output = sandbox.execute_command("true")
        assert output == "(no output)"

    def test_execute_command_exception(self):
        sandbox, client = self._make_sandbox()
        client.commands.run.side_effect = Exception("connection lost")

        output = sandbox.execute_command("echo test")
        assert "Error:" in output

    def test_read_file(self):
        sandbox, client = self._make_sandbox()
        client.files.read.return_value = "file content here"

        content = sandbox.read_file("/mnt/user-data/workspace/test.txt")

        client.files.read.assert_called_once_with(path="/mnt/user-data/workspace/test.txt", format="text")
        assert content == "file content here"

    def test_read_file_error(self):
        sandbox, client = self._make_sandbox()
        client.files.read.side_effect = Exception("file not found")

        with pytest.raises(OSError, match="Failed to read"):
            sandbox.read_file("/nonexistent")

    def test_list_dir(self):
        sandbox, client = self._make_sandbox()
        entry1 = MagicMock()
        entry1.path = "/mnt/user-data/workspace/file1.txt"
        entry2 = MagicMock()
        entry2.path = "/mnt/user-data/workspace/subdir"
        client.files.list.return_value = [entry1, entry2]

        result = sandbox.list_dir("/mnt/user-data/workspace", max_depth=2)

        client.files.list.assert_called_once_with(path="/mnt/user-data/workspace", depth=2)
        assert result == ["/mnt/user-data/workspace/file1.txt", "/mnt/user-data/workspace/subdir"]

    def test_list_dir_error(self):
        sandbox, client = self._make_sandbox()
        client.files.list.side_effect = Exception("access denied")

        result = sandbox.list_dir("/mnt/user-data")
        assert result == []

    def test_write_file(self):
        sandbox, client = self._make_sandbox()

        sandbox.write_file("/mnt/user-data/outputs/result.txt", "content here")

        client.files.write.assert_called_once_with(path="/mnt/user-data/outputs/result.txt", data="content here")

    def test_write_file_append(self):
        sandbox, client = self._make_sandbox()
        client.files.read.return_value = "existing "

        sandbox.write_file("/mnt/user-data/outputs/log.txt", "new data", append=True)

        client.files.read.assert_called_once()
        client.files.write.assert_called_once_with(path="/mnt/user-data/outputs/log.txt", data="existing new data")

    def test_write_file_append_new_file(self):
        sandbox, client = self._make_sandbox()
        client.files.read.side_effect = Exception("not found")

        sandbox.write_file("/mnt/user-data/outputs/new.txt", "content", append=True)

        client.files.write.assert_called_once_with(path="/mnt/user-data/outputs/new.txt", data="content")

    def test_write_file_error(self):
        sandbox, client = self._make_sandbox()
        client.files.write.side_effect = Exception("disk full")

        with pytest.raises(OSError, match="Failed to write"):
            sandbox.write_file("/mnt/user-data/outputs/big.dat", "data")

    def test_update_file(self):
        sandbox, client = self._make_sandbox()

        sandbox.update_file("/mnt/user-data/outputs/image.png", b"\x89PNG\r\n")

        client.files.write.assert_called_once_with(path="/mnt/user-data/outputs/image.png", data=b"\x89PNG\r\n")

    def test_update_file_error(self):
        sandbox, client = self._make_sandbox()
        client.files.write.side_effect = Exception("write error")

        with pytest.raises(OSError, match="Failed to update"):
            sandbox.update_file("/path", b"data")


class TestE2bSandboxProvider:
    """Tests for E2bSandboxProvider class."""

    def test_is_provider_subclass(self):
        assert issubclass(E2bSandboxProvider, SandboxProvider)

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_load_config_defaults(self, mock_config):
        """Test that config loads with sensible defaults."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = None
        sandbox_cfg.environment = {}
        sandbox_cfg.template = None
        mock_config.return_value.sandbox = sandbox_cfg

        # Don't actually start threads
        with patch.object(E2bSandboxProvider, "_start_idle_checker"):
            provider = E2bSandboxProvider()

        assert provider._config["timeout"] == 300  # DEFAULT_TIMEOUT
        assert provider._config["environment"] == {}
        assert provider._config["template"] is None

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_load_config_with_values(self, mock_config):
        """Test that config loads custom values."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 600
        sandbox_cfg.environment = {"KEY": "value"}
        sandbox_cfg.template = "custom-template"
        mock_config.return_value.sandbox = sandbox_cfg

        with patch.object(E2bSandboxProvider, "_start_idle_checker"):
            provider = E2bSandboxProvider()

        assert provider._config["timeout"] == 600
        assert provider._config["template"] == "custom-template"

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_acquire_creates_sandbox(self, mock_config):
        """Test that acquire creates a new E2B sandbox."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 0  # Disable idle checker
        sandbox_cfg.environment = {}
        sandbox_cfg.template = None
        mock_config.return_value.sandbox = sandbox_cfg

        mock_client = MagicMock()
        mock_client.sandbox_id = "e2b-abc123"
        mock_client.is_running.return_value = True

        with patch("e2b.Sandbox.create", return_value=mock_client) as mock_create:
            with patch("src.community.e2b_sandbox.e2b_sandbox_provider.E2bSandboxProvider._sync_skills_to_sandbox"):
                with patch("src.community.e2b_sandbox.e2b_sandbox_provider.E2bSandboxProvider._sync_storage_to_sandbox"):
                    provider = E2bSandboxProvider()
                    sandbox_id = provider.acquire(thread_id="test-thread")

        assert sandbox_id == "e2b-abc123"
        assert "e2b-abc123" in provider._sandboxes
        assert provider._thread_sandboxes.get("test-thread") == "e2b-abc123"

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_acquire_reuses_existing(self, mock_config):
        """Test that acquire reuses an existing sandbox for the same thread."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 0
        sandbox_cfg.environment = {}
        sandbox_cfg.template = None
        mock_config.return_value.sandbox = sandbox_cfg

        mock_client = MagicMock()
        mock_client.sandbox_id = "e2b-abc123"
        mock_client.is_running.return_value = True

        provider = E2bSandboxProvider()
        sandbox = E2bSandbox(id="e2b-abc123", client=mock_client)
        provider._sandboxes["e2b-abc123"] = sandbox
        provider._thread_sandboxes["test-thread"] = "e2b-abc123"

        result = provider.acquire(thread_id="test-thread")
        assert result == "e2b-abc123"

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_get_returns_sandbox(self, mock_config):
        """Test that get returns the correct sandbox."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 0
        sandbox_cfg.environment = {}
        mock_config.return_value.sandbox = sandbox_cfg

        provider = E2bSandboxProvider()
        mock_sandbox = MagicMock(spec=E2bSandbox)
        provider._sandboxes["test-id"] = mock_sandbox

        assert provider.get("test-id") is mock_sandbox
        assert provider.get("nonexistent") is None

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_release_kills_sandbox(self, mock_config):
        """Test that release kills the E2B sandbox."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 0
        sandbox_cfg.environment = {}
        mock_config.return_value.sandbox = sandbox_cfg

        provider = E2bSandboxProvider()
        mock_client = MagicMock()
        sandbox = E2bSandbox(id="e2b-xyz", client=mock_client)
        provider._sandboxes["e2b-xyz"] = sandbox
        provider._thread_sandboxes["thread-1"] = "e2b-xyz"
        provider._last_activity["e2b-xyz"] = 123.0

        provider.release("e2b-xyz")

        mock_client.kill.assert_called_once()
        assert "e2b-xyz" not in provider._sandboxes
        assert "thread-1" not in provider._thread_sandboxes
        assert "e2b-xyz" not in provider._last_activity

    @patch("src.community.e2b_sandbox.e2b_sandbox_provider.get_app_config")
    def test_shutdown_idempotent(self, mock_config):
        """Test that shutdown is idempotent."""
        sandbox_cfg = MagicMock()
        sandbox_cfg.idle_timeout = 0
        sandbox_cfg.environment = {}
        mock_config.return_value.sandbox = sandbox_cfg

        provider = E2bSandboxProvider()
        provider.shutdown()
        provider.shutdown()  # Should not raise

    def test_resolve_env_vars(self):
        """Test environment variable resolution."""
        import os

        os.environ["TEST_E2B_KEY"] = "secret123"
        result = E2bSandboxProvider._resolve_env_vars({"API_KEY": "$TEST_E2B_KEY", "STATIC": "value"})
        assert result == {"API_KEY": "secret123", "STATIC": "value"}
        del os.environ["TEST_E2B_KEY"]

    def test_resolve_env_vars_missing(self):
        """Test that missing env vars resolve to empty string."""
        result = E2bSandboxProvider._resolve_env_vars({"MISSING": "$NONEXISTENT_VAR_XYZ"})
        assert result == {"MISSING": ""}
