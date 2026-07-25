"""Sandbox-related exceptions with structured error information."""


class SandboxError(Exception):
    """Base exception for all sandbox-related errors."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            detail_str = ", ".join(f"{k}={v}" for k, v in self.details.items())
            return f"{self.message} ({detail_str})"
        return self.message


class SandboxNotFoundError(SandboxError):
    """Raised when a sandbox cannot be found or is not available."""

    def __init__(self, message: str = "Sandbox not found", sandbox_id: str | None = None):
        details = {"sandbox_id": sandbox_id} if sandbox_id else None
        super().__init__(message, details)
        self.sandbox_id = sandbox_id


class SandboxRuntimeError(SandboxError):
    """Raised when sandbox runtime is not available or misconfigured."""

    pass


class SandboxCommandError(SandboxError):
    """Raised when a command execution fails in the sandbox."""

    def __init__(self, message: str, command: str | None = None, exit_code: int | None = None):
        details = {}
        if command:
            details["command"] = command[:100] + "..." if len(command) > 100 else command
        if exit_code is not None:
            details["exit_code"] = exit_code
        super().__init__(message, details)
        self.command = command
        self.exit_code = exit_code


class SandboxFileError(SandboxError):
    """Raised when a file operation fails in the sandbox."""

    def __init__(self, message: str, path: str | None = None, operation: str | None = None):
        details = {}
        if path:
            details["path"] = path
        if operation:
            details["operation"] = operation
        super().__init__(message, details)
        self.path = path
        self.operation = operation


class SandboxPermissionError(SandboxFileError):
    """Raised when a permission error occurs during file operations."""

    pass


class SandboxFileNotFoundError(SandboxFileError):
    """Raised when a file or directory is not found."""

    pass


class SandboxCapacityExceededError(SandboxError):
    """Raised when the sandbox provider has no available capacity.

    The reason distinguishes occupied capacity from provider shutdown.
    The caller controls retry scheduling. DeerFlow does not retry automatically.
    """

    CODE = "SANDBOX_CAPACITY_EXCEEDED"

    def __init__(
        self,
        message: str = "All sandbox replica slots are in use",
        *,
        active: int = 0,
        warm: int = 0,
        reserved: int = 0,
        replicas: int = 0,
        retry_after_seconds: float = 5.0,
        reason: str = "capacity",
    ) -> None:
        details: dict[str, object] = {
            "code": self.CODE,
            "reason": reason,
            "replicas": replicas,
            "retryable": True,
            "retry_after_seconds": retry_after_seconds,
        }
        if active:
            details["active"] = active
        if warm:
            details["warm"] = warm
        if reserved:
            details["reserved"] = reserved
        super().__init__(message, details)
        self.active = active
        self.warm = warm
        self.reserved = reserved
        self.replicas = replicas
        self.retry_after_seconds = retry_after_seconds
        self.reason = reason
