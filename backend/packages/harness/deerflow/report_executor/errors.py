"""Exception classes for direct report execution."""

from __future__ import annotations

from typing import Any


class DirectExecutionError(Exception):
    """Base exception for direct execution errors."""

    def __init__(self, message: str, code: str = "DIRECT_EXECUTION_ERROR", step: str | None = None):
        super().__init__(message)
        self.code = code
        self.step = step

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"code": self.code, "message": str(self)}
        if self.step:
            result["step"] = self.step
        return result


class ScriptFailedError(DirectExecutionError):
    """Raised when a Skill script exits with non-zero or outputs error JSON."""

    def __init__(self, message: str, step: str, stdout: str | None = None):
        super().__init__(message, code="SCRIPT_FAILED", step=step)
        self.stdout = stdout

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.stdout:
            result["stdout"] = self.stdout
        return result


class NoDataError(DirectExecutionError):
    """Raised when data script returns empty results."""

    def __init__(self, message: str, step: str):
        super().__init__(message, code="NO_DATA", step=step)
