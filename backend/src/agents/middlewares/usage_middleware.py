"""Middleware to normalize and accumulate token usage into thread state."""

from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langgraph.runtime import Runtime

from src.agents.thread_state import UsageSummaryState


class UsageMiddlewareState(AgentState):
    """Compatible with the `ThreadState` schema."""

    usage: NotRequired[UsageSummaryState]


def _to_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _extract_from_dict(payload: dict, input_keys: tuple[str, ...], output_keys: tuple[str, ...], total_keys: tuple[str, ...]) -> tuple[int, int, int, bool]:
    has_any = False

    input_tokens = 0
    for key in input_keys:
        if key in payload:
            has_any = True
            input_tokens = _to_int(payload.get(key))
            break

    output_tokens = 0
    for key in output_keys:
        if key in payload:
            has_any = True
            output_tokens = _to_int(payload.get(key))
            break

    total_tokens = 0
    for key in total_keys:
        if key in payload:
            has_any = True
            total_tokens = _to_int(payload.get(key))
            break

    if total_tokens == 0 and (input_tokens > 0 or output_tokens > 0):
        total_tokens = input_tokens + output_tokens

    return input_tokens, output_tokens, total_tokens, has_any


def _extract_model_name(message: object) -> str:
    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        for key in ("model_name", "model", "model_id"):
            value = response_metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    additional_kwargs = getattr(message, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        for key in ("model_name", "model", "model_id"):
            value = additional_kwargs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return "unknown"


def _extract_tool_calls_delta(message: object) -> dict[str, int]:
    tool_calls = getattr(message, "tool_calls", None)
    if not isinstance(tool_calls, list):
        return {}

    counts: dict[str, int] = {}
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name")
        if not isinstance(name, str) or not name:
            continue
        counts[name] = counts.get(name, 0) + 1
    return counts


def extract_usage_delta(message: object) -> UsageSummaryState | None:
    """Extract normalized usage/tool-call deltas from one AI message."""
    if getattr(message, "type", None) != "ai":
        return None

    model_name = _extract_model_name(message)
    tool_calls_delta = _extract_tool_calls_delta(message)

    # Prefer LangChain standardized usage metadata when available.
    usage_metadata = getattr(message, "usage_metadata", None)
    if isinstance(usage_metadata, dict):
        i, o, t, has_any = _extract_from_dict(
            usage_metadata,
            input_keys=("input_tokens", "prompt_tokens", "input"),
            output_keys=("output_tokens", "completion_tokens", "output"),
            total_keys=("total_tokens", "total"),
        )
        if has_any:
            return {
                "models": [
                    {
                        "model": model_name,
                        "prompt_tokens": i,
                        "completion_tokens": o,
                        "total_tokens": t,
                    }
                ],
                "tool_calls": tool_calls_delta,
            }

    # Fallback to provider-specific response metadata.
    response_metadata = getattr(message, "response_metadata", None)
    if isinstance(response_metadata, dict):
        token_usage = response_metadata.get("token_usage")
        if not isinstance(token_usage, dict):
            token_usage = response_metadata.get("usage")
        if not isinstance(token_usage, dict):
            token_usage = response_metadata

        if isinstance(token_usage, dict):
            i, o, t, has_any = _extract_from_dict(
                token_usage,
                input_keys=("prompt_tokens", "input_tokens", "prompt_token_count", "input"),
                output_keys=("completion_tokens", "output_tokens", "candidates_token_count", "output"),
                total_keys=("total_tokens", "total_token_count", "total"),
            )
            if has_any:
                return {
                    "models": [
                        {
                            "model": model_name,
                            "prompt_tokens": i,
                            "completion_tokens": o,
                            "total_tokens": t,
                        }
                    ],
                    "tool_calls": tool_calls_delta,
                }

    if tool_calls_delta:
        return {
            "models": [],
            "tool_calls": tool_calls_delta,
        }

    return None


class UsageMiddleware(AgentMiddleware[UsageMiddlewareState]):
    """Accumulates token usage from each AI model response into `state.usage`."""

    state_schema = UsageMiddlewareState

    @override
    async def aafter_model(self, state: UsageMiddlewareState, runtime: Runtime) -> dict | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        # aafter_model runs after each model completion, so the last message is the newest AI sample.
        delta = extract_usage_delta(messages[-1])
        if delta is None:
            return None

        return {"usage": delta}
