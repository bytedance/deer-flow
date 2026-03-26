"""DeerFlow exception hierarchy with structured error information and recovery hints.

This module provides a comprehensive exception hierarchy for the DeerFlow project.
All custom exceptions inherit from DeerFlowError, which provides:
- Structured error details (message, error_code, recoverable flag)
- Recovery suggestions to guide users on how to fix the error
- Context information for debugging and logging
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class DeerFlowError(Exception):
    """Base exception for all DeerFlow-related errors.

    This is the root of the DeerFlow exception hierarchy. All custom exceptions
    should inherit from this class to provide consistent error handling across
    the project.

    Attributes:
        message: Human-readable error message.
        error_code: Machine-readable error code for programmatic handling.
        details: Additional context about the error.
        recoverable: Whether the error can potentially be recovered from.
        suggestion: Hint on how to recover from the error.

    Example:
        >>> raise DeerFlowError(
        ...     "Failed to load configuration",
        ...     error_code="CONFIG_LOAD_FAILED",
        ...     recoverable=True,
        ...     suggestion="Check that config.yaml exists and has valid YAML syntax"
        ... )
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        details: dict | None = None,
        recoverable: bool = False,
        suggestion: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__.replace("Error", "_ERROR").upper()
        self.details = details or {}
        self.recoverable = recoverable
        self.suggestion = suggestion

    def __str__(self) -> str:
        parts = [self.message]
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            parts.append(f"({detail_str})")
        if self.suggestion:
            parts.append(f"Suggestion: {self.suggestion}")
        return " | ".join(parts)

    def to_dict(self) -> dict:
        """Convert exception to a dictionary for API responses and logging."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
            "recoverable": self.recoverable,
            "suggestion": self.suggestion,
        }


# ============================================================================
# Configuration Errors
# ============================================================================


class ConfigError(DeerFlowError):
    """Base exception for configuration-related errors."""

    def __init__(
        self,
        message: str,
        *,
        config_path: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if config_path:
            details["config_path"] = config_path
        super().__init__(message, details=details, **kwargs)
        self.config_path = config_path


class ConfigNotFoundError(ConfigError):
    """Raised when a configuration file cannot be found."""

    def __init__(self, config_path: str, **kwargs):
        super().__init__(
            f"Configuration file not found: {config_path}",
            config_path=config_path,
            error_code="CONFIG_NOT_FOUND",
            recoverable=True,
            suggestion=f"Create the configuration file at {config_path} or specify a different path via DEER_FLOW_CONFIG_PATH environment variable",
            **kwargs,
        )


class ConfigParseError(ConfigError):
    """Raised when a configuration file cannot be parsed."""

    def __init__(self, config_path: str, parse_error: str, **kwargs):
        super().__init__(
            f"Failed to parse configuration file: {parse_error}",
            config_path=config_path,
            error_code="CONFIG_PARSE_ERROR",
            recoverable=True,
            suggestion=f"Fix the syntax error in {config_path}. Check for valid YAML/JSON syntax and correct indentation",
            **kwargs,
        )
        self.parse_error = parse_error


class ConfigValidationError(ConfigError):
    """Raised when configuration validation fails."""

    def __init__(self, message: str, *, field: str | None = None, **kwargs):
        details = kwargs.pop("details", {}) or {}
        if field:
            details["field"] = field
        super().__init__(
            message,
            error_code="CONFIG_VALIDATION_ERROR",
            recoverable=True,
            suggestion="Check the configuration field and ensure it meets the required format and constraints",
            details=details,
            **kwargs,
        )
        self.field = field


# ============================================================================
# Model Errors
# ============================================================================


class ModelError(DeerFlowError):
    """Base exception for model-related errors."""

    def __init__(
        self,
        message: str,
        *,
        model_name: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if model_name:
            details["model_name"] = model_name
        super().__init__(message, details=details, **kwargs)
        self.model_name = model_name


class ModelNotFoundError(ModelError):
    """Raised when a requested model is not configured."""

    def __init__(self, model_name: str, available_models: list[str] | None = None, **kwargs):
        details = kwargs.pop("details", {}) or {}
        if available_models:
            details["available_models"] = ", ".join(available_models)
        suggestion = f"Add the model '{model_name}' to your config.yaml under the 'models' section"
        if available_models:
            suggestion += f", or use one of the available models: {', '.join(available_models)}"
        super().__init__(
            f"Model '{model_name}' not found in configuration",
            model_name=model_name,
            error_code="MODEL_NOT_FOUND",
            recoverable=True,
            suggestion=suggestion,
            details=details,
            **kwargs,
        )
        self.available_models = available_models


class ModelLoadError(ModelError):
    """Raised when a model fails to load."""

    def __init__(self, model_name: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to load model '{model_name}': {reason}",
            model_name=model_name,
            error_code="MODEL_LOAD_ERROR",
            recoverable=True,
            suggestion="Check that the model provider is installed (e.g., 'uv add langchain-openai') and API keys are configured correctly",
            **kwargs,
        )
        self.reason = reason


class ModelProviderError(ModelError):
    """Raised when a model provider is not installed or not found."""

    def __init__(self, provider_path: str, model_name: str | None = None, **kwargs):
        # Extract package name from provider path (e.g., "langchain_openai:ChatOpenAI" -> "langchain-openai")
        package_name = provider_path.split(":")[0].replace("_", "-")
        super().__init__(
            f"Model provider '{provider_path}' not found or not installed",
            model_name=model_name,
            error_code="MODEL_PROVIDER_ERROR",
            recoverable=True,
            suggestion=f"Install the provider package: 'uv add {package_name}' or 'pip install {package_name}'",
            details={"provider_path": provider_path, "install_hint": f"uv add {package_name}"},
            **kwargs,
        )
        self.provider_path = provider_path


class ModelAPICallError(ModelError):
    """Raised when an API call to a model fails."""

    def __init__(
        self,
        model_name: str,
        api_error: str,
        *,
        status_code: int | None = None,
        retry_after: int | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if status_code:
            details["status_code"] = status_code
        if retry_after:
            details["retry_after"] = retry_after
        recoverable = status_code is None or status_code >= 500 or status_code == 429
        suggestion = "Check your API key and network connection"
        if status_code == 401:
            suggestion = "Verify your API key is correct and has not expired"
        elif status_code == 429:
            suggestion = f"Rate limit exceeded. Wait {retry_after or 'a few seconds'} before retrying"
        elif status_code and status_code >= 500:
            suggestion = "Server error. The issue may be temporary - try again in a few moments"
        super().__init__(
            f"API call failed for model '{model_name}': {api_error}",
            model_name=model_name,
            error_code="MODEL_API_ERROR",
            recoverable=recoverable,
            suggestion=suggestion,
            details=details,
            **kwargs,
        )
        self.api_error = api_error
        self.status_code = status_code
        self.retry_after = retry_after


# ============================================================================
# Tool Errors
# ============================================================================


class ToolError(DeerFlowError):
    """Base exception for tool-related errors."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if tool_name:
            details["tool_name"] = tool_name
        if tool_call_id:
            details["tool_call_id"] = tool_call_id
        super().__init__(message, details=details, **kwargs)
        self.tool_name = tool_name
        self.tool_call_id = tool_call_id


class ToolNotFoundError(ToolError):
    """Raised when a requested tool is not available."""

    def __init__(self, tool_name: str, available_tools: list[str] | None = None, **kwargs):
        details = kwargs.pop("details", {}) or {}
        if available_tools:
            details["available_tools"] = ", ".join(available_tools[:10])  # Limit to first 10
        suggestion = f"Check that the tool '{tool_name}' is correctly configured"
        if available_tools:
            suggestion += f". Available tools: {', '.join(available_tools[:5])}"
        super().__init__(
            f"Tool '{tool_name}' not found",
            tool_name=tool_name,
            error_code="TOOL_NOT_FOUND",
            recoverable=True,
            suggestion=suggestion,
            details=details,
            **kwargs,
        )
        self.available_tools = available_tools


class ToolExecutionError(ToolError):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        reason: str,
        *,
        tool_call_id: str | None = None,
        **kwargs,
    ):
        super().__init__(
            f"Tool '{tool_name}' execution failed: {reason}",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            error_code="TOOL_EXECUTION_ERROR",
            recoverable=True,
            suggestion="Check the tool parameters and try again with corrected input",
            **kwargs,
        )
        self.reason = reason


class ToolTimeoutError(ToolError):
    """Raised when a tool execution times out."""

    def __init__(
        self,
        tool_name: str,
        timeout_seconds: float,
        *,
        tool_call_id: str | None = None,
        **kwargs,
    ):
        super().__init__(
            f"Tool '{tool_name}' execution timed out after {timeout_seconds}s",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            error_code="TOOL_TIMEOUT",
            recoverable=True,
            suggestion=f"The operation took too long. Try simplifying the request or increasing the timeout",
            details={"timeout_seconds": timeout_seconds},
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds


# ============================================================================
# Channel Errors
# ============================================================================


class ChannelError(DeerFlowError):
    """Base exception for channel (IM integration) errors."""

    def __init__(
        self,
        message: str,
        *,
        channel_type: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if channel_type:
            details["channel_type"] = channel_type
        super().__init__(message, details=details, **kwargs)
        self.channel_type = channel_type


class ChannelNotConfiguredError(ChannelError):
    """Raised when a channel is enabled but not properly configured."""

    def __init__(self, channel_type: str, missing_fields: list[str], **kwargs):
        super().__init__(
            f"Channel '{channel_type}' is enabled but missing required configuration",
            channel_type=channel_type,
            error_code="CHANNEL_NOT_CONFIGURED",
            recoverable=True,
            suggestion=f"Add the following fields to your config.yaml channels.{channel_type} section: {', '.join(missing_fields)}",
            details={"missing_fields": ", ".join(missing_fields)},
            **kwargs,
        )
        self.missing_fields = missing_fields


class ChannelConnectionError(ChannelError):
    """Raised when a channel connection fails."""

    def __init__(self, channel_type: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to connect to {channel_type} channel: {reason}",
            channel_type=channel_type,
            error_code="CHANNEL_CONNECTION_ERROR",
            recoverable=True,
            suggestion="Check your network connection and verify API credentials are correct",
            **kwargs,
        )
        self.reason = reason


class ChannelMessageError(ChannelError):
    """Raised when sending or receiving a message through a channel fails."""

    def __init__(self, channel_type: str, operation: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to {operation} message via {channel_type}: {reason}",
            channel_type=channel_type,
            error_code="CHANNEL_MESSAGE_ERROR",
            recoverable=True,
            suggestion="The message operation failed. Try again or check channel status",
            details={"operation": operation},
            **kwargs,
        )
        self.operation = operation
        self.reason = reason


# ============================================================================
# Memory Errors
# ============================================================================


class MemoryError(DeerFlowError):
    """Base exception for memory-related errors."""

    def __init__(
        self,
        message: str,
        *,
        user_id: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if user_id:
            details["user_id"] = user_id
        super().__init__(message, details=details, **kwargs)
        self.user_id = user_id


class MemoryStorageError(MemoryError):
    """Raised when memory storage operations fail."""

    def __init__(self, operation: str, reason: str, **kwargs):
        super().__init__(
            f"Memory {operation} failed: {reason}",
            error_code="MEMORY_STORAGE_ERROR",
            recoverable=True,
            suggestion="The memory operation failed. Check disk space and file permissions",
            details={"operation": operation},
            **kwargs,
        )
        self.operation = operation
        self.reason = reason


class MemoryExtractionError(MemoryError):
    """Raised when memory extraction from conversations fails."""

    def __init__(self, reason: str, **kwargs):
        super().__init__(
            f"Failed to extract memory from conversation: {reason}",
            error_code="MEMORY_EXTRACTION_ERROR",
            recoverable=True,
            suggestion="Memory extraction failed. The conversation will continue but memory may not be updated",
            **kwargs,
        )
        self.reason = reason


# ============================================================================
# Upload Errors
# ============================================================================


class UploadError(DeerFlowError):
    """Base exception for upload-related errors."""

    def __init__(
        self,
        message: str,
        *,
        filename: str | None = None,
        thread_id: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if filename:
            details["filename"] = filename
        if thread_id:
            details["thread_id"] = thread_id
        super().__init__(message, details=details, **kwargs)
        self.filename = filename
        self.thread_id = thread_id


class UploadFileError(UploadError):
    """Raised when a file upload fails."""

    def __init__(self, filename: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to upload file '{filename}': {reason}",
            filename=filename,
            error_code="UPLOAD_FILE_ERROR",
            recoverable=True,
            suggestion="Check that the file exists and is readable, and that the filename is valid",
            **kwargs,
        )
        self.reason = reason


class UploadSecurityError(UploadError):
    """Raised when a file upload is rejected due to security concerns."""

    def __init__(self, filename: str, reason: str, **kwargs):
        super().__init__(
            f"File upload rejected for security: {reason}",
            filename=filename,
            error_code="UPLOAD_SECURITY_ERROR",
            recoverable=False,
            suggestion="The file was rejected for security reasons. Use a different filename or file type",
            **kwargs,
        )
        self.reason = reason


# ============================================================================
# Skill Errors
# ============================================================================


class SkillError(DeerFlowError):
    """Base exception for skill-related errors."""

    def __init__(
        self,
        message: str,
        *,
        skill_name: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if skill_name:
            details["skill_name"] = skill_name
        super().__init__(message, details=details, **kwargs)
        self.skill_name = skill_name


class SkillNotFoundError(SkillError):
    """Raised when a requested skill is not found."""

    def __init__(self, skill_name: str, available_skills: list[str] | None = None, **kwargs):
        details = kwargs.pop("details", {}) or {}
        if available_skills:
            details["available_skills"] = ", ".join(available_skills[:10])
        suggestion = f"Check that the skill '{skill_name}' exists in the skills directory"
        if available_skills:
            suggestion += f". Available skills: {', '.join(available_skills[:5])}"
        super().__init__(
            f"Skill '{skill_name}' not found",
            skill_name=skill_name,
            error_code="SKILL_NOT_FOUND",
            recoverable=True,
            suggestion=suggestion,
            details=details,
            **kwargs,
        )
        self.available_skills = available_skills


class SkillLoadError(SkillError):
    """Raised when a skill fails to load."""

    def __init__(self, skill_name: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to load skill '{skill_name}': {reason}",
            skill_name=skill_name,
            error_code="SKILL_LOAD_ERROR",
            recoverable=True,
            suggestion="Check that the skill's SKILL.md file is valid and all referenced files exist",
            **kwargs,
        )
        self.reason = reason


class SkillInstallError(SkillError):
    """Raised when a skill installation fails."""

    def __init__(self, reason: str, skill_source: str | None = None, **kwargs):
        details = kwargs.pop("details", {}) or {}
        if skill_source:
            details["skill_source"] = skill_source
        super().__init__(
            f"Failed to install skill: {reason}",
            error_code="SKILL_INSTALL_ERROR",
            recoverable=True,
            suggestion="Check that the skill archive is valid and the skills directory is writable",
            details=details,
            **kwargs,
        )
        self.reason = reason
        self.skill_source = skill_source


# ============================================================================
# MCP (Model Context Protocol) Errors
# ============================================================================


class MCPError(DeerFlowError):
    """Base exception for MCP-related errors."""

    def __init__(
        self,
        message: str,
        *,
        server_name: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if server_name:
            details["server_name"] = server_name
        super().__init__(message, details=details, **kwargs)
        self.server_name = server_name


class MCPConnectionError(MCPError):
    """Raised when connection to an MCP server fails."""

    def __init__(self, server_name: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to connect to MCP server '{server_name}': {reason}",
            server_name=server_name,
            error_code="MCP_CONNECTION_ERROR",
            recoverable=True,
            suggestion="Check that the MCP server is running and accessible. Verify the connection URL and credentials",
            **kwargs,
        )
        self.reason = reason


class MCPToolError(MCPError):
    """Raised when an MCP tool execution fails."""

    def __init__(self, server_name: str, tool_name: str, reason: str, **kwargs):
        super().__init__(
            f"MCP tool '{tool_name}' from server '{server_name}' failed: {reason}",
            server_name=server_name,
            error_code="MCP_TOOL_ERROR",
            recoverable=True,
            suggestion="Check the tool parameters and MCP server status",
            details={"tool_name": tool_name},
            **kwargs,
        )
        self.tool_name = tool_name
        self.reason = reason


# ============================================================================
# Subagent Errors
# ============================================================================


class SubagentError(DeerFlowError):
    """Base exception for subagent-related errors."""

    def __init__(
        self,
        message: str,
        *,
        agent_name: str | None = None,
        task_id: str | None = None,
        **kwargs,
    ):
        details = kwargs.pop("details", {}) or {}
        if agent_name:
            details["agent_name"] = agent_name
        if task_id:
            details["task_id"] = task_id
        super().__init__(message, details=details, **kwargs)
        self.agent_name = agent_name
        self.task_id = task_id


class SubagentLimitExceededError(SubagentError):
    """Raised when the maximum number of concurrent subagents is exceeded."""

    def __init__(self, current_count: int, max_count: int, **kwargs):
        super().__init__(
            f"Subagent limit exceeded: {current_count}/{max_count} subagents already running",
            error_code="SUBAGENT_LIMIT_EXCEEDED",
            recoverable=True,
            suggestion="Wait for an existing subagent to complete before spawning new ones, or increase the limit in configuration",
            details={"current_count": current_count, "max_count": max_count},
            **kwargs,
        )
        self.current_count = current_count
        self.max_count = max_count


class SubagentTimeoutError(SubagentError):
    """Raised when a subagent execution times out."""

    def __init__(self, agent_name: str, timeout_seconds: float, **kwargs):
        super().__init__(
            f"Subagent '{agent_name}' execution timed out after {timeout_seconds}s",
            agent_name=agent_name,
            error_code="SUBAGENT_TIMEOUT",
            recoverable=True,
            suggestion="Try breaking the task into smaller subtasks or increase the timeout in configuration",
            details={"timeout_seconds": timeout_seconds},
            **kwargs,
        )
        self.timeout_seconds = timeout_seconds


class SubagentSpawnError(SubagentError):
    """Raised when spawning a new subagent fails."""

    def __init__(self, agent_name: str, reason: str, **kwargs):
        super().__init__(
            f"Failed to spawn subagent '{agent_name}': {reason}",
            agent_name=agent_name,
            error_code="SUBAGENT_SPAWN_ERROR",
            recoverable=True,
            suggestion="Check that the agent is properly configured and has the required tools available",
            **kwargs,
        )
        self.reason = reason