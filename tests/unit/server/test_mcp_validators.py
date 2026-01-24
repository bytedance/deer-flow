# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for MCP server configuration validators.

Tests cover:
- Command validation (allowlist)
- Argument validation (path traversal, command injection)
- Environment variable validation
- URL validation
- Header validation
- Full config validation
"""

import pytest

from src.server.mcp_validators import (
    ALLOWED_COMMANDS,
    MCPValidationError,
    validate_args_for_local_file_access,
    validate_command,
    validate_command_injection,
    validate_environment_variables,
    validate_headers,
    validate_mcp_server_config,
    validate_url,
)


class TestValidateCommand:
    """Tests for validate_command function."""

    def test_allowed_commands(self):
        """Test that all allowed commands pass validation."""
        for cmd in ALLOWED_COMMANDS:
            validate_command(cmd)  # Should not raise

    def test_allowed_command_with_path(self):
        """Test that commands with paths are validated by base name."""
        validate_command("/usr/bin/python3")
        validate_command("/usr/local/bin/node")
        validate_command("C:\\Python\\python.exe")

    def test_disallowed_command(self):
        """Test that disallowed commands raise an error."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_command("bash")
        assert "not allowed" in exc_info.value.message
        assert exc_info.value.field == "command"

    def test_disallowed_dangerous_commands(self):
        """Test that dangerous commands are rejected."""
        dangerous_commands = ["rm", "sudo", "chmod", "chown", "curl", "wget", "sh"]
        for cmd in dangerous_commands:
            with pytest.raises(MCPValidationError):
                validate_command(cmd)

    def test_empty_command(self):
        """Test that empty command raises an error."""
        with pytest.raises(MCPValidationError):
            validate_command("")

    def test_none_command(self):
        """Test that None command raises an error."""
        with pytest.raises(MCPValidationError):
            validate_command(None)


class TestValidateArgsForLocalFileAccess:
    """Tests for validate_args_for_local_file_access function."""

    def test_safe_args(self):
        """Test that safe arguments pass validation."""
        safe_args = [
            ["--help"],
            ["-v", "--verbose"],
            ["package-name"],
            ["--config", "config.json"],
            ["run", "script.py"],
        ]
        for args in safe_args:
            validate_args_for_local_file_access(args)  # Should not raise

    def test_directory_traversal(self):
        """Test that directory traversal patterns are rejected."""
        traversal_patterns = [
            ["../etc/passwd"],
            ["..\\windows\\system32"],
            ["../../secret"],
            ["foo/../bar/../../../etc/passwd"],
        ]
        for args in traversal_patterns:
            with pytest.raises(MCPValidationError) as exc_info:
                validate_args_for_local_file_access(args)
            assert "traversal" in exc_info.value.message.lower()

    def test_absolute_path_with_dangerous_extension(self):
        """Test that absolute paths with dangerous extensions are rejected."""
        with pytest.raises(MCPValidationError):
            validate_args_for_local_file_access(["/etc/passwd.sh"])

    def test_windows_absolute_path(self):
        """Test that Windows absolute paths are rejected."""
        with pytest.raises(MCPValidationError):
            validate_args_for_local_file_access(["C:\\Windows\\system32"])

    def test_home_directory_reference(self):
        """Test that home directory references are rejected."""
        with pytest.raises(MCPValidationError):
            validate_args_for_local_file_access(["~/secrets"])

        with pytest.raises(MCPValidationError):
            validate_args_for_local_file_access(["~\\secrets"])

    def test_null_byte(self):
        """Test that null bytes in arguments are rejected."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_args_for_local_file_access(["file\x00.txt"])
        assert "null byte" in exc_info.value.message.lower()

    def test_excessively_long_argument(self):
        """Test that excessively long arguments are rejected."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_args_for_local_file_access(["a" * 1001])
        assert "maximum length" in exc_info.value.message.lower()

    def test_dangerous_extensions(self):
        """Test that dangerous file extensions are rejected."""
        dangerous_files = [
            ["script.sh"],
            ["binary.exe"],
            ["library.dll"],
            ["secret.env"],
            ["key.pem"],
        ]
        for args in dangerous_files:
            with pytest.raises(MCPValidationError) as exc_info:
                validate_args_for_local_file_access(args)
            assert "dangerous file type" in exc_info.value.message.lower()

    def test_empty_args(self):
        """Test that empty args list passes validation."""
        validate_args_for_local_file_access([])
        validate_args_for_local_file_access(None)


class TestValidateCommandInjection:
    """Tests for validate_command_injection function."""

    def test_safe_args(self):
        """Test that safe arguments pass validation."""
        safe_args = [
            ["--help"],
            ["package-name"],
            ["@scope/package"],
            ["file.json"],
        ]
        for args in safe_args:
            validate_command_injection(args)  # Should not raise

    def test_shell_metacharacters(self):
        """Test that shell metacharacters are rejected."""
        metachar_args = [
            ["foo; rm -rf /"],
            ["foo & bar"],
            ["foo | cat /etc/passwd"],
            ["$(whoami)"],
            ["`id`"],
            ["foo > /etc/passwd"],
            ["foo < /etc/passwd"],
            ["${PATH}"],
        ]
        for args in metachar_args:
            with pytest.raises(MCPValidationError) as exc_info:
                validate_command_injection(args)
            assert "args" == exc_info.value.field

    def test_command_chaining(self):
        """Test that command chaining patterns are rejected."""
        chaining_args = [
            ["foo && bar"],
            ["foo || bar"],
            ["foo;; bar"],
            ["foo >> output"],
            ["foo << input"],
        ]
        for args in chaining_args:
            with pytest.raises(MCPValidationError):
                validate_command_injection(args)

    def test_backtick_injection(self):
        """Test that backtick command substitution is rejected."""
        with pytest.raises(MCPValidationError):
            validate_command_injection(["`whoami`"])

    def test_process_substitution(self):
        """Test that process substitution is rejected."""
        with pytest.raises(MCPValidationError):
            validate_command_injection(["<(cat /etc/passwd)"])

        with pytest.raises(MCPValidationError):
            validate_command_injection([">(tee /tmp/out)"])


class TestValidateEnvironmentVariables:
    """Tests for validate_environment_variables function."""

    def test_safe_env_vars(self):
        """Test that safe environment variables pass validation."""
        safe_env = {
            "API_KEY": "secret123",
            "DEBUG": "true",
            "MY_VARIABLE": "value",
        }
        validate_environment_variables(safe_env)  # Should not raise

    def test_dangerous_env_vars(self):
        """Test that dangerous environment variables are rejected."""
        dangerous_vars = [
            {"PATH": "/malicious/path"},
            {"LD_LIBRARY_PATH": "/malicious/lib"},
            {"DYLD_LIBRARY_PATH": "/malicious/lib"},
            {"LD_PRELOAD": "/malicious/lib.so"},
            {"PYTHONPATH": "/malicious/python"},
            {"NODE_PATH": "/malicious/node"},
        ]
        for env in dangerous_vars:
            with pytest.raises(MCPValidationError) as exc_info:
                validate_environment_variables(env)
            assert "not allowed" in exc_info.value.message.lower()

    def test_null_byte_in_value(self):
        """Test that null bytes in values are rejected."""
        with pytest.raises(MCPValidationError):
            validate_environment_variables({"KEY": "value\x00malicious"})

    def test_empty_env(self):
        """Test that empty env dict passes validation."""
        validate_environment_variables({})
        validate_environment_variables(None)


class TestValidateUrl:
    """Tests for validate_url function."""

    def test_valid_urls(self):
        """Test that valid URLs pass validation."""
        valid_urls = [
            "http://localhost:3000",
            "https://api.example.com",
            "http://192.168.1.1:8080/api",
            "https://mcp.example.com/sse",
        ]
        for url in valid_urls:
            validate_url(url)  # Should not raise

    def test_invalid_scheme(self):
        """Test that invalid URL schemes are rejected."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_url("ftp://example.com")
        assert "scheme" in exc_info.value.message.lower()

        with pytest.raises(MCPValidationError):
            validate_url("file:///etc/passwd")

    def test_credentials_in_url(self):
        """Test that URLs with credentials are rejected."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_url("https://user:pass@example.com")
        assert "credentials" in exc_info.value.message.lower()

    def test_null_byte_in_url(self):
        """Test that null bytes in URL are rejected."""
        with pytest.raises(MCPValidationError):
            validate_url("https://example.com\x00/malicious")

    def test_empty_url(self):
        """Test that empty URL raises an error."""
        with pytest.raises(MCPValidationError):
            validate_url("")

    def test_no_host(self):
        """Test that URL without host raises an error."""
        with pytest.raises(MCPValidationError):
            validate_url("http:///path")


class TestValidateHeaders:
    """Tests for validate_headers function."""

    def test_valid_headers(self):
        """Test that valid headers pass validation."""
        valid_headers = {
            "Authorization": "Bearer token123",
            "Content-Type": "application/json",
            "X-Custom-Header": "value",
        }
        validate_headers(valid_headers)  # Should not raise

    def test_newline_in_header_name(self):
        """Test that newlines in header names are rejected (HTTP header injection)."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_headers({"X-Bad\nHeader": "value"})
        assert "newline" in exc_info.value.message.lower()

    def test_newline_in_header_value(self):
        """Test that newlines in header values are rejected (HTTP header injection)."""
        with pytest.raises(MCPValidationError):
            validate_headers({"X-Header": "value\r\nX-Injected: malicious"})

    def test_null_byte_in_header(self):
        """Test that null bytes in headers are rejected."""
        with pytest.raises(MCPValidationError):
            validate_headers({"X-Header": "value\x00"})

    def test_empty_headers(self):
        """Test that empty headers dict passes validation."""
        validate_headers({})
        validate_headers(None)


class TestValidateMCPServerConfig:
    """Tests for the main validate_mcp_server_config function."""

    def test_valid_stdio_config(self):
        """Test valid stdio configuration."""
        validate_mcp_server_config(
            transport="stdio",
            command="npx",
            args=["@modelcontextprotocol/server-filesystem"],
            env={"API_KEY": "secret"},
        )  # Should not raise

    def test_valid_sse_config(self):
        """Test valid SSE configuration."""
        validate_mcp_server_config(
            transport="sse",
            url="https://api.example.com/sse",
            headers={"Authorization": "Bearer token"},
        )  # Should not raise

    def test_valid_http_config(self):
        """Test valid streamable_http configuration."""
        validate_mcp_server_config(
            transport="streamable_http",
            url="https://api.example.com/mcp",
        )  # Should not raise

    def test_invalid_transport(self):
        """Test that invalid transport type raises an error."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_mcp_server_config(transport="invalid")
        assert "Invalid transport type" in exc_info.value.message

    def test_combined_validation_errors(self):
        """Test that multiple validation errors are combined."""
        with pytest.raises(MCPValidationError) as exc_info:
            validate_mcp_server_config(
                transport="stdio",
                command="bash",  # Not allowed
                args=["../etc/passwd"],  # Path traversal
                env={"PATH": "/malicious"},  # Dangerous env var
            )
        # All errors should be combined
        assert "not allowed" in exc_info.value.message
        assert "traversal" in exc_info.value.message.lower()

    def test_non_strict_mode(self):
        """Test that non-strict mode logs warnings instead of raising."""
        # Should not raise, but would log warnings
        validate_mcp_server_config(
            transport="stdio",
            command="bash",
            strict=False,
        )

    def test_stdio_with_dangerous_args(self):
        """Test stdio config with command injection attempt."""
        with pytest.raises(MCPValidationError):
            validate_mcp_server_config(
                transport="stdio",
                command="node",
                args=["script.js; rm -rf /"],
            )

    def test_sse_with_invalid_url(self):
        """Test SSE config with invalid URL."""
        with pytest.raises(MCPValidationError):
            validate_mcp_server_config(
                transport="sse",
                url="ftp://example.com",
            )


class TestMCPServerMetadataRequest:
    """Tests for Pydantic model validation."""

    def test_valid_request(self):
        """Test that valid request passes validation."""
        from src.server.mcp_request import MCPServerMetadataRequest

        request = MCPServerMetadataRequest(
            transport="stdio",
            command="npx",
            args=["@modelcontextprotocol/server-filesystem"],
        )
        assert request.transport == "stdio"
        assert request.command == "npx"

    def test_invalid_command_raises_validation_error(self):
        """Test that invalid command raises Pydantic ValidationError."""
        from pydantic import ValidationError

        from src.server.mcp_request import MCPServerMetadataRequest

        with pytest.raises(ValidationError) as exc_info:
            MCPServerMetadataRequest(
                transport="stdio",
                command="bash",
            )
        assert "not allowed" in str(exc_info.value).lower()

    def test_command_injection_raises_validation_error(self):
        """Test that command injection raises Pydantic ValidationError."""
        from pydantic import ValidationError

        from src.server.mcp_request import MCPServerMetadataRequest

        with pytest.raises(ValidationError):
            MCPServerMetadataRequest(
                transport="stdio",
                command="node",
                args=["script.js; rm -rf /"],
            )

    def test_invalid_url_raises_validation_error(self):
        """Test that invalid URL raises Pydantic ValidationError."""
        from pydantic import ValidationError

        from src.server.mcp_request import MCPServerMetadataRequest

        with pytest.raises(ValidationError):
            MCPServerMetadataRequest(
                transport="sse",
                url="ftp://example.com",
            )
