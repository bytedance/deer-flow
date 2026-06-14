"""Domain-level errors for run lifecycle operations."""

from __future__ import annotations

from .value_objects import RunStatus


class RunDomainError(Exception):
    """Base class for run runtime domain errors."""


class InvalidRunTransition(RunDomainError):
    """Raised when a run status transition violates lifecycle rules."""

    def __init__(self, current: RunStatus, target: RunStatus) -> None:
        super().__init__(f"Cannot transition run from {current.value!r} to {target.value!r}")
        self.current = current
        self.target = target


__all__ = [
    "InvalidRunTransition",
    "RunDomainError",
]
