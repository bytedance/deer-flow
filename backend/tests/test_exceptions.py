"""Tests for DeerFlow custom exceptions."""

import pytest

from deerflow.exceptions import (
    ChannelConnectionError,
    ChannelError,
    ChannelNotConfiguredError,
    ConfigError,
    ConfigNotFoundError,
    ConfigParseError,
    ConfigValidationError,
    DeerFlowError,
    MCPConnectionError,
    MCPError,
    MCPToolError,
    MemoryError,
    MemoryExtractionError,
    MemoryStorageError,
    ModelAPICallError,
    ModelError,
    ModelLoadError,
    ModelNotFoundError,
    ModelProviderError,
    SkillError,
    SkillInstallError,
    SkillLoadError,
    SkillNotFoundError,
    SubagentError,
    SubagentLimitExceededError,
    SubagentSpawnError,
    SubagentTimeoutError,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    UploadError,
    UploadFileError,
    UploadSecurityError,
)


class TestDeerFlowError:
    """Tests for the base DeerFlowError class."""

    def test_basic_error(self):
        """Test creating a basic error."""
        error = DeerFlowError("Something went wrong")
        assert str(error) == "Something went wrong"
        assert error.message == "Something went wrong"
        assert error.recoverable is False
        assert error.suggestion is None

    def test_error_with_all_options(self):
        """Test creating an error with all options."""
        error = DeerFlowError(
            "Failed to load config",
            error_code="CONFIG_LOAD_FAILED",
            details={"path": "/etc/config.yaml"},
            recoverable=True,
            suggestion="Check the file exists",
        )
        assert error.message == "Failed to load config"
        assert error.error_code == "CONFIG_LOAD_FAILED"
        assert error.details == {"path": "/etc/config.yaml"}
        assert error.recoverable is True
        assert error.suggestion == "Check the file exists"
        assert "Failed to load config" in str(error)
        assert "path=/etc/config.yaml" in str(error)
        assert "Suggestion: Check the file exists" in str(error)

    def test_to_dict(self):
        """Test converting error to dictionary."""
        error = DeerFlowError(
            "Test error",
            error_code="TEST_ERROR",
            details={"key": "value"},
            recoverable=True,
            suggestion="Try again",
        )
        result = error.to_dict()
        assert result == {
            "error": "TEST_ERROR",
            "message": "Test error",
            "details": {"key": "value"},
            "recoverable": True,
            "suggestion": "Try again",
        }


class TestConfigErrors:
    """Tests for configuration-related errors."""

    def test_config_not_found_error(self):
        """Test ConfigNotFoundError."""
        error = ConfigNotFoundError("/path/to/config.yaml")
        assert error.config_path == "/path/to/config.yaml"
        assert error.recoverable is True
        assert "not found" in error.message.lower()
        assert "DEER_FLOW_CONFIG_PATH" in error.suggestion

    def test_config_parse_error(self):
        """Test ConfigParseError."""
        error = ConfigParseError("/path/to/config.yaml", "Invalid YAML at line 5")
        assert error.config_path == "/path/to/config.yaml"
        assert error.parse_error == "Invalid YAML at line 5"
        assert error.recoverable is True

    def test_config_validation_error(self):
        """Test ConfigValidationError."""
        error = ConfigValidationError("Invalid model configuration", field="models[0].name")
        assert error.field == "models[0].name"
        assert error.recoverable is True


class TestModelErrors:
    """Tests for model-related errors."""

    def test_model_not_found_error(self):
        """Test ModelNotFoundError."""
        error = ModelNotFoundError("gpt-5", available_models=["gpt-4", "claude-3"])
        assert error.model_name == "gpt-5"
        assert error.available_models == ["gpt-4", "claude-3"]
        assert error.recoverable is True
        assert "gpt-5" in error.message
        assert "gpt-4" in error.suggestion

    def test_model_not_found_error_no_available(self):
        """Test ModelNotFoundError without available models."""
        error = ModelNotFoundError("gpt-5")
        assert error.model_name == "gpt-5"
        assert error.available_models is None
        assert "config.yaml" in error.suggestion

    def test_model_load_error(self):
        """Test ModelLoadError."""
        error = ModelLoadError("gpt-4", "API key not found")
        assert error.model_name == "gpt-4"
        assert error.reason == "API key not found"
        assert error.recoverable is True
        assert "API key" in error.suggestion

    def test_model_provider_error(self):
        """Test ModelProviderError."""
        error = ModelProviderError("langchain_openai:ChatOpenAI", model_name="gpt-4")
        assert error.provider_path == "langchain_openai:ChatOpenAI"
        assert error.model_name == "gpt-4"
        assert "langchain-openai" in error.suggestion.lower()
        assert "uv add" in error.suggestion

    def test_model_api_call_error(self):
        """Test ModelAPICallError."""
        error = ModelAPICallError("gpt-4", "Rate limit exceeded", status_code=429, retry_after=30)
        assert error.model_name == "gpt-4"
        assert error.status_code == 429
        assert error.retry_after == 30
        assert error.recoverable is True
        assert "Rate limit" in error.suggestion

    def test_model_api_call_error_auth(self):
        """Test ModelAPICallError with auth error."""
        error = ModelAPICallError("gpt-4", "Unauthorized", status_code=401)
        assert error.status_code == 401
        assert error.recoverable is False
        assert "API key" in error.suggestion

    def test_model_api_call_error_server_error(self):
        """Test ModelAPICallError with server error."""
        error = ModelAPICallError("gpt-4", "Internal server error", status_code=500)
        assert error.status_code == 500
        assert error.recoverable is True


class TestToolErrors:
    """Tests for tool-related errors."""

    def test_tool_not_found_error(self):
        """Test ToolNotFoundError."""
        error = ToolNotFoundError("custom_tool", available_tools=["bash", "read_file"])
        assert error.tool_name == "custom_tool"
        assert error.available_tools == ["bash", "read_file"]
        assert error.recoverable is True

    def test_tool_execution_error(self):
        """Test ToolExecutionError."""
        error = ToolExecutionError("bash", "Command not found", tool_call_id="tc-123")
        assert error.tool_name == "bash"
        assert error.tool_call_id == "tc-123"
        assert error.reason == "Command not found"
        assert error.recoverable is True

    def test_tool_timeout_error(self):
        """Test ToolTimeoutError."""
        error = ToolTimeoutError("bash", 30.0, tool_call_id="tc-123")
        assert error.tool_name == "bash"
        assert error.timeout_seconds == 30.0
        assert "30" in error.message


class TestChannelErrors:
    """Tests for channel-related errors."""

    def test_channel_not_configured_error(self):
        """Test ChannelNotConfiguredError."""
        error = ChannelNotConfiguredError("slack", missing_fields=["bot_token", "app_token"])
        assert error.channel_type == "slack"
        assert error.missing_fields == ["bot_token", "app_token"]
        assert error.recoverable is True
        assert "bot_token" in error.suggestion

    def test_channel_connection_error(self):
        """Test ChannelConnectionError."""
        error = ChannelConnectionError("telegram", "Network unreachable")
        assert error.channel_type == "telegram"
        assert error.reason == "Network unreachable"
        assert error.recoverable is True


class TestMemoryErrors:
    """Tests for memory-related errors."""

    def test_memory_storage_error(self):
        """Test MemoryStorageError."""
        error = MemoryStorageError("save", "Disk full")
        assert error.operation == "save"
        assert error.reason == "Disk full"
        assert error.recoverable is True

    def test_memory_extraction_error(self):
        """Test MemoryExtractionError."""
        error = MemoryExtractionError("LLM timeout")
        assert error.reason == "LLM timeout"
        assert error.recoverable is True


class TestUploadErrors:
    """Tests for upload-related errors."""

    def test_upload_file_error(self):
        """Test UploadFileError."""
        error = UploadFileError("large_file.pdf", "File too large", thread_id="thread-123")
        assert error.filename == "large_file.pdf"
        assert error.thread_id == "thread-123"
        assert error.reason == "File too large"
        assert error.recoverable is True

    def test_upload_security_error(self):
        """Test UploadSecurityError."""
        error = UploadSecurityError("../../../etc/passwd", "Path traversal detected")
        assert error.filename == "../../../etc/passwd"
        assert error.reason == "Path traversal detected"
        assert error.recoverable is False


class TestSkillErrors:
    """Tests for skill-related errors."""

    def test_skill_not_found_error(self):
        """Test SkillNotFoundError."""
        error = SkillNotFoundError("custom-skill", available_skills=["research", "report"])
        assert error.skill_name == "custom-skill"
        assert error.available_skills == ["research", "report"]
        assert error.recoverable is True

    def test_skill_load_error(self):
        """Test SkillLoadError."""
        error = SkillLoadError("research", "SKILL.md not found")
        assert error.skill_name == "research"
        assert error.reason == "SKILL.md not found"
        assert error.recoverable is True

    def test_skill_install_error(self):
        """Test SkillInstallError."""
        error = SkillInstallError("Archive corrupted", skill_source="custom.skill")
        assert error.reason == "Archive corrupted"
        assert error.skill_source == "custom.skill"
        assert error.recoverable is True


class TestMCPErrors:
    """Tests for MCP-related errors."""

    def test_mcp_connection_error(self):
        """Test MCPConnectionError."""
        error = MCPConnectionError("github", "Connection refused")
        assert error.server_name == "github"
        assert error.reason == "Connection refused"
        assert error.recoverable is True

    def test_mcp_tool_error(self):
        """Test MCPToolError."""
        error = MCPToolError("github", "search_repos", "Rate limit exceeded")
        assert error.server_name == "github"
        assert error.tool_name == "search_repos"
        assert error.reason == "Rate limit exceeded"
        assert error.recoverable is True


class TestSubagentErrors:
    """Tests for subagent-related errors."""

    def test_subagent_limit_exceeded_error(self):
        """Test SubagentLimitExceededError."""
        error = SubagentLimitExceededError(current_count=3, max_count=3)
        assert error.current_count == 3
        assert error.max_count == 3
        assert "3/3" in error.message
        assert error.recoverable is True

    def test_subagent_timeout_error(self):
        """Test SubagentTimeoutError."""
        error = SubagentTimeoutError("research-agent", 900.0)
        assert error.agent_name == "research-agent"
        assert error.timeout_seconds == 900.0
        assert "900" in error.message
        assert error.recoverable is True

    def test_subagent_spawn_error(self):
        """Test SubagentSpawnError."""
        error = SubagentSpawnError("custom-agent", "Tool not available")
        assert error.agent_name == "custom-agent"
        assert error.reason == "Tool not available"
        assert error.recoverable is True


class TestExceptionRaising:
    """Tests for raising and catching exceptions."""

    def test_raise_and_catch_deerflow_error(self):
        """Test raising and catching DeerFlowError."""
        with pytest.raises(DeerFlowError) as exc_info:
            raise ModelNotFoundError("gpt-5")
        assert exc_info.value.model_name == "gpt-5"

    def test_catch_subclass_as_base_class(self):
        """Test catching a subclass as the base class."""
        with pytest.raises(DeerFlowError):
            raise ConfigNotFoundError("/path/to/config")

    def test_catch_model_error_as_model_error(self):
        """Test catching a ModelError subclass."""
        with pytest.raises(ModelError):
            raise ModelNotFoundError("gpt-5")

    def test_error_details_inheritance(self):
        """Test that error details are preserved through inheritance."""
        error = ModelAPICallError(
            "gpt-4",
            "Timeout",
            status_code=504,
            details={"request_id": "req-123"},
        )
        assert error.details["request_id"] == "req-123"
        assert error.details["status_code"] == 504
        assert error.details["model_name"] == "gpt-4"