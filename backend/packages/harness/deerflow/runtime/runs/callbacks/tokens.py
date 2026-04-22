"""Token and message summary callback for runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler


@dataclass(frozen=True)
class RunCompletionData:
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    llm_call_count: int = 0
    lead_agent_tokens: int = 0
    subagent_tokens: int = 0
    middleware_tokens: int = 0
    message_count: int = 0
    last_ai_message: str | None = None
    first_human_message: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "llm_call_count": self.llm_call_count,
            "lead_agent_tokens": self.lead_agent_tokens,
            "subagent_tokens": self.subagent_tokens,
            "middleware_tokens": self.middleware_tokens,
            "message_count": self.message_count,
            "last_ai_message": self.last_ai_message,
            "first_human_message": self.first_human_message,
        }


class RunTokenCallback(BaseCallbackHandler):
    """Aggregate token and message summary data for one run."""

    def __init__(self, *, track_token_usage: bool = True) -> None:
        super().__init__()
        self._track_token_usage = track_token_usage
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_tokens = 0
        self._llm_call_count = 0
        self._lead_agent_tokens = 0
        self._subagent_tokens = 0
        self._middleware_tokens = 0
        self._message_count = 0
        self._last_ai_message: str | None = None
        self._first_human_message: str | None = None

    def set_first_human_message(self, content: str) -> None:
        self._first_human_message = content[:2000] if content else None

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            return

        self._record_ai_message(message, kwargs)
        if not self._track_token_usage:
            return

        usage = dict(getattr(message, "usage_metadata", None) or {})
        input_tk = usage.get("input_tokens", 0) or 0
        output_tk = usage.get("output_tokens", 0) or 0
        total_tk = usage.get("total_tokens", 0) or input_tk + output_tk
        if total_tk <= 0:
            return

        self._total_input_tokens += input_tk
        self._total_output_tokens += output_tk
        self._total_tokens += total_tk
        self._llm_call_count += 1

        caller = self._identify_caller(kwargs)
        if caller.startswith("subagent:"):
            self._subagent_tokens += total_tk
        elif caller.startswith("middleware:"):
            self._middleware_tokens += total_tk
        else:
            self._lead_agent_tokens += total_tk

    def completion_data(self) -> RunCompletionData:
        return RunCompletionData(
            total_input_tokens=self._total_input_tokens,
            total_output_tokens=self._total_output_tokens,
            total_tokens=self._total_tokens,
            llm_call_count=self._llm_call_count,
            lead_agent_tokens=self._lead_agent_tokens,
            subagent_tokens=self._subagent_tokens,
            middleware_tokens=self._middleware_tokens,
            message_count=self._message_count,
            last_ai_message=self._last_ai_message,
            first_human_message=self._first_human_message,
        )

    def _record_ai_message(self, message: Any, kwargs: dict[str, Any]) -> None:
        if self._identify_caller(kwargs) != "lead_agent":
            return
        if getattr(message, "tool_calls", None):
            return
        content = getattr(message, "content", "")
        if isinstance(content, str) and content:
            self._last_ai_message = content[:2000]
            self._message_count += 1

    def _identify_caller(self, kwargs: dict[str, Any]) -> str:
        for tag in kwargs.get("tags") or []:
            if isinstance(tag, str) and (
                tag.startswith("subagent:")
                or tag.startswith("middleware:")
                or tag == "lead_agent"
            ):
                return tag
        return "lead_agent"
