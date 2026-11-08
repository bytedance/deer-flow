"""Structured model response errors shared by providers and middleware."""

from __future__ import annotations

from langchain_core.messages import AIMessage


class EmptyModelResponseError(RuntimeError):
    """The model completed normally without producing persistent content."""

    code = "EMPTY_RESPONSE"

    def __init__(
        self,
        message: str = "Model returned a completed response with no content",
        *,
        response_message: AIMessage | None = None,
    ) -> None:
        super().__init__(message)
        self.response_message = response_message
