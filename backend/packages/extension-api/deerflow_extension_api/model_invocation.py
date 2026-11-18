"""Provider-neutral, non-streaming text model calls granted by the host."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


class ModelInvocationError(RuntimeError):
    """Normalized host error; contains no provider exception or credentials."""


class ModelInvocationUnavailable(ModelInvocationError):
    """The capability has stopped or its configured model is unavailable."""


class ModelInvocationUnauthorized(ModelInvocationError):
    """The requested logical role is not granted to this installation."""


class ModelInvocationFailed(ModelInvocationError):
    """The invocation failed, exceeded a host limit or timed out."""


class ModelOutputValidationError(ModelInvocationFailed):
    """Provider output could not be parsed or validated against the schema."""


@dataclass(frozen=True)
class ModelMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelInvocationRequest:
    messages: Sequence[ModelMessage]
    model_role: str | None = None
    purpose: str | None = None
    response_schema: Mapping[str, object] | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(self.messages))


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class ModelInvocationResult:
    content: str
    structured_output: Mapping[str, object] | None = None
    resolved_model: str | None = None
    usage: ModelUsage | None = None


class ModelInvoker(Protocol):
    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        """Invoke once; schema requests succeed only with validated object data.

        Caller cancellation propagates as asyncio.CancelledError. A timeout
        (including time waiting for host capacity) raises ModelInvocationFailed.
        """
        raise ModelInvocationUnavailable("Model invocation is not supported by this host")
