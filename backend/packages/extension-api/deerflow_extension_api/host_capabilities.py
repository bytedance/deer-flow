"""Dependency-free errors shared by optional host capabilities."""

from __future__ import annotations


class HostCapabilityError(RuntimeError):
    """A stable machine-readable failure, optionally carrying retry guidance."""

    def __init__(self, code: str, message: str = "", *, retry_after: float | None = None) -> None:
        self.code = code
        self.retry_after = retry_after
        super().__init__(f"{code}: {message}" if message else code)
