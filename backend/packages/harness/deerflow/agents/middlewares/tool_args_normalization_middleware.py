"""Middleware that normalizes tool-call arguments for models with schema drift.

Local and third-party models occasionally emit tool calls using parameter
names from their own training data rather than the schema DeerFlow's
sandbox tools actually expose. Two patterns have been observed in real
threads and are fixed here:

* ``file_path`` (or ``filepath``) where the schema wants ``path`` — the
  alias is Mistral's generic file-tool convention and surfaces on every
  file-oriented tool the model tries to call.
* Missing ``description`` — DeerFlow's sandbox tools declare this as a
  required first argument for audit-logging purposes; models that were
  trained on schemas without it simply omit the field.

The middleware is registered **unconditionally** (see
``lead_agent/agent.py``) because the pattern is model-agnostic: the same
training quirk can appear on any model that arrives with its own tool-use
convention. For correctly-formed tool calls the middleware is a no-op —
it returns the original response object by identity, so ``wrap_model_call``
adds no measurable overhead on the happy path.

The hook point is :meth:`wrap_model_call`: we intercept the ModelResponse
and mutate the ``tool_calls`` list on each AIMessage before it is
dispatched to the tool executor. The rewritten calls are what ends up
persisted in the thread state, so UI, LangSmith and replay all agree on
what was actually executed. Every mutation is logged at INFO level so
newly-emerging quirks are discoverable via log search rather than having
to register a model in a gate list.

The alias map is intentionally narrow. Only aliases observed on real
responses are translated, so genuine schema violations surface as
ToolErrorHandlingMiddleware errors instead of being silently masked. To
add a new alias, extend ``_FILE_PATH_ALIASES`` (or add a new alias set
with the same pattern) and include a regression test.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage

logger = logging.getLogger(__name__)


AUTO_DESCRIPTION_MARKER = "(auto-filled: model did not provide description)"

_FILE_PATH_ALIASES = {"file_path", "filepath"}


class ToolArgsNormalizationMiddleware(AgentMiddleware[AgentState]):
    """Rewrites tool-call arguments to match DeerFlow's sandbox schema."""

    @staticmethod
    def _normalize_args(tool_name: str, args: dict) -> tuple[dict, bool]:
        """Return (normalized_args, mutated). Pure function, ``args`` is not mutated."""
        if not isinstance(args, dict):
            return args, False

        new_args = dict(args)
        mutated = False

        # Alias: file_path / filepath → path. Only applied if ``path`` isn't
        # already set (schema-correct calls win, conflicts favour the schema).
        for alias in _FILE_PATH_ALIASES:
            if alias in new_args:
                if "path" not in new_args:
                    new_args["path"] = new_args.pop(alias)
                    mutated = True
                else:
                    new_args.pop(alias)
                    mutated = True

        # Missing description — all sandbox tools declare it as required.
        # Only auto-fill for tools that have it in their signature; we
        # conservatively key on tool_name since the schema is stable.
        if tool_name in _TOOLS_REQUIRING_DESCRIPTION and "description" not in new_args:
            new_args["description"] = AUTO_DESCRIPTION_MARKER
            mutated = True

        return new_args, mutated

    @classmethod
    def _normalize_tool_calls(cls, tool_calls: list) -> tuple[list, bool]:
        if not tool_calls:
            return tool_calls, False

        new_calls: list = []
        any_mutated = False
        for tc in tool_calls:
            if not isinstance(tc, dict):
                new_calls.append(tc)
                continue
            tool_name = tc.get("name") or ""
            args = tc.get("args") or {}
            new_args, mutated = cls._normalize_args(tool_name, args)
            if mutated:
                any_mutated = True
                rebuilt = dict(tc)
                rebuilt["args"] = new_args
                new_calls.append(rebuilt)
                logger.info(
                    "tool-args normalized for %s (original keys=%s, final keys=%s)",
                    tool_name,
                    sorted(args.keys()) if isinstance(args, dict) else "n/a",
                    sorted(new_args.keys()),
                )
            else:
                new_calls.append(tc)
        return new_calls, any_mutated

    @classmethod
    def _normalize_messages(cls, messages: list) -> list | None:
        """Return a new list of messages with tool_calls normalized, or None if nothing changed."""
        if not messages:
            return None

        result: list = []
        mutated_any = False
        for msg in messages:
            if not isinstance(msg, AIMessage):
                result.append(msg)
                continue
            tool_calls = getattr(msg, "tool_calls", None) or []
            new_calls, mutated = cls._normalize_tool_calls(tool_calls)
            if not mutated:
                result.append(msg)
                continue
            mutated_any = True
            result.append(
                AIMessage(
                    id=msg.id,
                    content=msg.content,
                    name=msg.name,
                    tool_calls=new_calls,
                    invalid_tool_calls=getattr(msg, "invalid_tool_calls", []),
                    additional_kwargs=msg.additional_kwargs,
                    response_metadata=msg.response_metadata,
                    usage_metadata=msg.usage_metadata,
                )
            )
        return result if mutated_any else None

    @classmethod
    def _normalize_response(cls, response):
        """Normalize a ModelResponse (or bare AIMessage) returned by ``handler(request)``."""
        if isinstance(response, AIMessage):
            normalized = cls._normalize_messages([response])
            if normalized is None:
                return response
            return normalized[0]
        result = getattr(response, "result", None)
        if not isinstance(result, list):
            return response
        normalized = cls._normalize_messages(result)
        if normalized is None:
            return response
        response.result = normalized
        return response

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        response = handler(request)
        return self._normalize_response(response)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        response = await handler(request)
        return self._normalize_response(response)


_TOOLS_REQUIRING_DESCRIPTION = {
    "bash",
    "ls",
    "glob",
    "grep",
    "read_file",
    "write_file",
    "str_replace",
}
