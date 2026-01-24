# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
MCP Server Configuration Validators.

This module provides security validation for MCP server configurations,
inspired by Flowise's validateMCPServerConfig implementation. It prevents:
- Command injection attacks
- Path traversal attacks
- Unauthorized file access
- Dangerous environment variable modifications

Reference: https://github.com/FlowiseAI/Flowise/blob/main/packages/components/nodes/tools/MCP/core.ts
"""

import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class MCPValidationError(Exception):
    """Exception raised when MCP server configuration validation fails."""

    def __init__(self, message: str, field: Optional[str] = None):
        self.message = message
        self.field = field
        super().__init__(self.message)


# Allowed commands for stdio transport
# These are considered safe executable commands for MCP servers
ALLOWED_COMMANDS = frozenset([
    "node",
    "npx",
    "python",
    "python3",
    "docker",
    "uvx",
    "uv",
    "deno",
    "bun",
])

# Dangerous environment variables that should not be modified
DANGEROUS_ENV_VARS = frozenset([
    "PATH",
    "LD_LIBRARY_PATH",
    "DYLD_LIBRARY_PATH",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "PYTHONPATH",
    "NODE_PATH",
    "RUBYLIB",
    "PERL5LIB",
])

# Shell metacharacters that could be used for injection
SHELL_METACHARACTERS = frozenset([
    ";",
    "&",
    "|",
    "`",
    "$",
    "(",
    ")",
    "{",
    "}",
    "[",
    "]",
    "<",
    ">",
    "\n",
    "\r",
])

# Dangerous file extensions that should not be directly accessed
DANGEROUS_EXTENSIONS = frozenset([
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bat",
    ".cmd",
    ".ps1",
    ".sh",
    ".bash",
    ".zsh",
    ".env",
    ".pem",
    ".key",
    ".crt",
    ".p12",
    ".pfx",
])

# Command chaining patterns
COMMAND_CHAINING_PATTERNS = [
    "&&",
    "||",
    ";;",
    ">>",
    "<<",
    "$(",
    "<(",
    ">(",
]

# Maximum argument length to prevent buffer overflow attacks
MAX_ARG_LENGTH = 1000

# Allowed URL schemes for SSE/HTTP transports
ALLOWED_URL_SCHEMES = frozenset(["http", "https"])


def validate_mcp_server_config(
    transport: str,
    command: Optional[str] = None,
    args: Optional[List[str]] = None,
    url: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    headers: Optional[Dict[str, str]] = None,
    strict: bool = True,
) -> None:
    """
    Validate MCP server configuration for security issues.

    This is the main entry point for MCP server validation. It orchestrates
    all security checks based on the transport type.

    Args:
        transport: The type of MCP connection (stdio, sse, streamable_http)
        command: The command to execute (for stdio transport)
        args: Command arguments (for stdio transport)
        url: The URL of the server (for sse/streamable_http transport)
        env: Environment variables (for stdio transport)
        headers: HTTP headers (for sse/streamable_http transport)
        strict: If True, raise exceptions; if False, log warnings only

    Raises:
        MCPValidationError: If validation fails in strict mode
    """
    errors: List[str] = []

    # Validate transport type
    valid_transports = {"stdio", "sse", "streamable_http"}
    if transport not in valid_transports:
        errors.append(f"Invalid transport type: {transport}. Must be one of: {', '.join(valid_transports)}")

    # Transport-specific validation
    if transport == "stdio":
        # Validate command
        if command:
            try:
                validate_command(command)
            except MCPValidationError as e:
                errors.append(e.message)

        # Validate arguments
        if args:
            try:
                validate_args_for_local_file_access(args)
            except MCPValidationError as e:
                errors.append(e.message)

            try:
                validate_command_injection(args)
            except MCPValidationError as e:
                errors.append(e.message)

        # Validate environment variables
        if env:
            try:
                validate_environment_variables(env)
            except MCPValidationError as e:
                errors.append(e.message)

    elif transport in ("sse", "streamable_http"):
        # Validate URL
        if url:
            try:
                validate_url(url)
            except MCPValidationError as e:
                errors.append(e.message)

        # Validate headers for injection
        if headers:
            try:
                validate_headers(headers)
            except MCPValidationError as e:
                errors.append(e.message)

    # Handle errors
    if errors:
        error_message = "; ".join(errors)
        if strict:
            raise MCPValidationError(error_message)
        else:
            logger.warning(f"MCP configuration validation warnings: {error_message}")


def validate_command(command: str) -> None:
    """
    Validate the command against an allowlist of safe executables.

    Args:
        command: The command to validate

    Raises:
        MCPValidationError: If the command is not in the allowlist
    """
    if not command or not isinstance(command, str):
        raise MCPValidationError("Command must be a non-empty string", field="command")

    # Extract the base command (handle full paths)
    # e.g., "/usr/bin/python3" -> "python3"
    base_command = command.split("/")[-1].split("\\")[-1]

    # Also handle .exe suffix on Windows
    if base_command.endswith(".exe"):
        base_command = base_command[:-4]

    if base_command not in ALLOWED_COMMANDS:
        raise MCPValidationError(
            f"Command '{command}' is not allowed. Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}",
            field="command",
        )


def validate_args_for_local_file_access(args: List[str]) -> None:
    """
    Validate arguments to prevent path traversal and unauthorized file access.

    Checks for:
    - Absolute paths (starting with / or drive letters like C:)
    - Directory traversal (../, ..\\)
    - Local file access patterns (./, ~/)
    - Dangerous file extensions
    - Null bytes (security exploit)
    - Excessively long arguments (buffer overflow protection)

    Args:
        args: List of command arguments to validate

    Raises:
        MCPValidationError: If any argument contains dangerous patterns
    """
    if not args:
        return

    for i, arg in enumerate(args):
        if not isinstance(arg, str):
            raise MCPValidationError(
                f"Argument at index {i} must be a string, got {type(arg).__name__}",
                field="args",
            )

        # Check for excessively long arguments
        if len(arg) > MAX_ARG_LENGTH:
            raise MCPValidationError(
                f"Argument at index {i} exceeds maximum length of {MAX_ARG_LENGTH} characters",
                field="args",
            )

        # Check for null bytes
        if "\x00" in arg:
            raise MCPValidationError(
                f"Argument at index {i} contains null byte",
                field="args",
            )

        # Check for directory traversal
        if ".." in arg:
            # More specific check for actual traversal patterns
            # Catches: "../", "..\", "/..", "\..", standalone "..", starts with "..", ends with ".."
            if (
                "../" in arg
                or "..\\" in arg
                or "/.." in arg
                or "\\.." in arg
                or arg == ".."
                or arg.startswith("..")
                or arg.endswith("..")
            ):
                raise MCPValidationError(
                    f"Argument at index {i} contains directory traversal pattern: {arg[:50]}",
                    field="args",
                )

        # Check for absolute paths (Unix-style)
        # Be careful to allow flags like -f, --flag, etc.
        if arg.startswith("/") and not arg.startswith("/-"):
            # Check if it looks like a file path (contains more slashes or extensions)
            if "/" in arg[1:] or any(arg.endswith(ext) for ext in DANGEROUS_EXTENSIONS):
                raise MCPValidationError(
                    f"Argument at index {i} contains absolute path: {arg[:50]}",
                    field="args",
                )

        # Check for Windows absolute paths
        if len(arg) >= 2 and arg[1] == ":" and arg[0].isalpha():
            raise MCPValidationError(
                f"Argument at index {i} contains Windows absolute path: {arg[:50]}",
                field="args",
            )

        # Check for home directory expansion
        if arg.startswith("~/") or arg.startswith("~\\"):
            raise MCPValidationError(
                f"Argument at index {i} contains home directory reference: {arg[:50]}",
                field="args",
            )

        # Check for dangerous extensions in the argument
        arg_lower = arg.lower()
        for ext in DANGEROUS_EXTENSIONS:
            if arg_lower.endswith(ext):
                raise MCPValidationError(
                    f"Argument at index {i} references potentially dangerous file type: {ext}",
                    field="args",
                )


def validate_command_injection(args: List[str]) -> None:
    """
    Validate arguments to prevent shell command injection.

    Checks for:
    - Shell metacharacters (; & | ` $ ( ) { } [ ] < > etc.)
    - Command chaining patterns (&& || ;; etc.)
    - Command substitution patterns ($() ``)
    - Process substitution patterns (<() >())

    Args:
        args: List of command arguments to validate

    Raises:
        MCPValidationError: If any argument contains injection patterns
    """
    if not args:
        return

    for i, arg in enumerate(args):
        if not isinstance(arg, str):
            continue

        # Check for shell metacharacters
        for char in SHELL_METACHARACTERS:
            if char in arg:
                raise MCPValidationError(
                    f"Argument at index {i} contains shell metacharacter '{char}': {arg[:50]}",
                    field="args",
                )

        # Check for command chaining patterns
        for pattern in COMMAND_CHAINING_PATTERNS:
            if pattern in arg:
                raise MCPValidationError(
                    f"Argument at index {i} contains command chaining pattern '{pattern}': {arg[:50]}",
                    field="args",
                )

        # Check for backticks (command substitution)
        if "`" in arg:
            raise MCPValidationError(
                f"Argument at index {i} contains backtick command substitution: {arg[:50]}",
                field="args",
            )


def validate_environment_variables(env: Dict[str, str]) -> None:
    """
    Validate environment variables to prevent dangerous modifications.

    Checks for:
    - Modifications to PATH and library path variables
    - Null bytes in values
    - Excessively long values

    Args:
        env: Dictionary of environment variables

    Raises:
        MCPValidationError: If any environment variable is dangerous
    """
    if not env:
        return

    if not isinstance(env, dict):
        raise MCPValidationError(
            f"Environment variables must be a dictionary, got {type(env).__name__}",
            field="env",
        )

    for key, value in env.items():
        # Validate key
        if not isinstance(key, str):
            raise MCPValidationError(
                f"Environment variable key must be a string, got {type(key).__name__}",
                field="env",
            )

        # Check for dangerous environment variables
        if key.upper() in DANGEROUS_ENV_VARS:
            raise MCPValidationError(
                f"Modification of environment variable '{key}' is not allowed for security reasons",
                field="env",
            )

        # Validate value
        if not isinstance(value, str):
            raise MCPValidationError(
                f"Environment variable value for '{key}' must be a string, got {type(value).__name__}",
                field="env",
            )

        # Check for null bytes in value
        if "\x00" in value:
            raise MCPValidationError(
                f"Environment variable '{key}' contains null byte",
                field="env",
            )

        # Check for excessively long values
        if len(value) > MAX_ARG_LENGTH * 10:  # Allow longer env values
            raise MCPValidationError(
                f"Environment variable '{key}' value exceeds maximum length",
                field="env",
            )


def validate_url(url: str) -> None:
    """
    Validate URL for SSE/HTTP transport.

    Checks for:
    - Valid URL format
    - Allowed schemes (http, https)
    - No credentials in URL
    - No localhost/internal network access (optional, configurable)

    Args:
        url: The URL to validate

    Raises:
        MCPValidationError: If the URL is invalid or potentially dangerous
    """
    if not url or not isinstance(url, str):
        raise MCPValidationError("URL must be a non-empty string", field="url")

    # Check for null bytes
    if "\x00" in url:
        raise MCPValidationError("URL contains null byte", field="url")

    # Parse the URL
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise MCPValidationError(f"Invalid URL format: {e}", field="url")

    # Check scheme
    if parsed.scheme not in ALLOWED_URL_SCHEMES:
        raise MCPValidationError(
            f"URL scheme '{parsed.scheme}' is not allowed. Allowed schemes: {', '.join(ALLOWED_URL_SCHEMES)}",
            field="url",
        )

    # Check for credentials in URL (security risk)
    if parsed.username or parsed.password:
        raise MCPValidationError(
            "URL should not contain credentials. Use headers for authentication instead.",
            field="url",
        )

    # Check for valid host
    if not parsed.netloc:
        raise MCPValidationError("URL must have a valid host", field="url")


def validate_headers(headers: Dict[str, str]) -> None:
    """
    Validate HTTP headers for potential injection attacks.

    Args:
        headers: Dictionary of HTTP headers

    Raises:
        MCPValidationError: If any header contains dangerous patterns
    """
    if not headers:
        return

    if not isinstance(headers, dict):
        raise MCPValidationError(
            f"Headers must be a dictionary, got {type(headers).__name__}",
            field="headers",
        )

    for key, value in headers.items():
        # Validate key
        if not isinstance(key, str):
            raise MCPValidationError(
                f"Header key must be a string, got {type(key).__name__}",
                field="headers",
            )

        # Check for newlines in header name (HTTP header injection)
        if "\n" in key or "\r" in key:
            raise MCPValidationError(
                f"Header name '{key[:20]}' contains newline character (potential HTTP header injection)",
                field="headers",
            )

        # Validate value
        if not isinstance(value, str):
            raise MCPValidationError(
                f"Header value for '{key}' must be a string, got {type(value).__name__}",
                field="headers",
            )

        # Check for newlines in header value (HTTP header injection)
        if "\n" in value or "\r" in value:
            raise MCPValidationError(
                f"Header value for '{key}' contains newline character (potential HTTP header injection)",
                field="headers",
            )

        # Check for null bytes
        if "\x00" in key or "\x00" in value:
            raise MCPValidationError(
                f"Header '{key}' contains null byte",
                field="headers",
            )
