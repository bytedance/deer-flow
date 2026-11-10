"""A memory-update response cut off at the output token cap is reported as such.

When the extractor model stops at ``max_tokens`` the returned JSON is
necessarily incomplete, so parsing fails the same way a malformed answer does.
The updater used to emit only the generic parse warning, which sent operators
looking for a bad prompt when the fix was a larger ``max_tokens``.

Providers spell the cap differently, so the diagnostic relies on the shared
middleware detectors and must fire for every one of those shapes. These tests
also pin the unchanged failure semantics (``update_memory`` still returns
``False`` and writes nothing) and keep apply-gate rejections out of the
truncation branch.
"""

import logging
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

_LOGGER = "deerflow.agents.memory.backends.deermem.deermem.core.updater"
_PARSE_FAIL = "Failed to parse LLM response for memory update"
_TRUNCATED = "truncated at the output token limit"

# Same four provider shapes the middleware detectors cover.
_CAP_SIGNALS = {
    "openai_compatible": ({"finish_reason": "length"}, "finish_reason='length'"),
    "anthropic": ({"stop_reason": "max_tokens"}, "stop_reason='max_tokens'"),
    "gemini": ({"finish_reason": "MAX_TOKENS"}, "finish_reason='MAX_TOKENS'"),
    "openai_responses": (
        {"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}},
        "incomplete_details.reason='max_output_tokens'",
    ),
}


class _CannedResponse:
    def __init__(self, content: Any, metadata: dict[str, Any] | None = None) -> None:
        self.content = content
        self.usage_metadata: dict[str, int] | None = None
        self.response_metadata = dict(metadata or {})


class _CannedLLM:
    def __init__(self, response: Any) -> None:
        self._response = response
        self.invoke_count = 0

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.invoke_count += 1
        return self._response


class _Storage(MemoryStorage):
    def __init__(self) -> None:
        self.memory: dict[str, Any] = {"version": "2.0", "revision": 0, "user": {}, "history": {}, "facts": []}
        self.save_calls = 0

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.memory

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(
        self,
        memory_data: dict[str, Any],
        agent_name: str | None = None,
        *,
        user_id: str | None = None,
        expected_revision: int | None = None,
    ) -> bool:
        self.save_calls += 1
        self.memory = memory_data
        return True


def _messages() -> list[Any]:
    return [
        HumanMessage(content="请记住：我的项目代号是 Orion-77。"),
        AIMessage(content="已记住。"),
    ]


def _run(response: Any) -> tuple[bool, _Storage, _CannedLLM]:
    storage = _Storage()
    llm = _CannedLLM(response)
    updater = MemoryUpdater(DeerMemConfig(), storage, llm)
    result = updater.update_memory(_messages(), thread_id="t-trunc", agent_name="a", user_id="u")
    return result, storage, llm


def _truncation_messages(caplog: Any) -> list[str]:
    return [record.getMessage() for record in caplog.records if _TRUNCATED in record.getMessage()]


@pytest.mark.parametrize("metadata,expected_signal", list(_CAP_SIGNALS.values()), ids=list(_CAP_SIGNALS))
def test_truncated_response_is_reported_for_each_provider_shape(
    caplog: Any, metadata: dict[str, Any], expected_signal: str
) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    result, storage, llm = _run(_CannedResponse("", metadata))

    assert result is False
    assert storage.save_calls == 0
    assert llm.invoke_count == 1
    truncated = _truncation_messages(caplog)
    assert len(truncated) == 1
    assert expected_signal in truncated[0]
    assert "max_tokens" in truncated[0]
    assert not [record for record in caplog.records if record.getMessage().startswith(_PARSE_FAIL)]


def test_malformed_response_keeps_the_generic_parse_warning(caplog: Any) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    result, storage, llm = _run(_CannedResponse("这不是 JSON", {"finish_reason": "stop"}))

    assert result is False
    assert storage.save_calls == 0
    assert llm.invoke_count == 1
    assert [record for record in caplog.records if record.getMessage().startswith(_PARSE_FAIL)]
    assert not _truncation_messages(caplog)


def test_missing_metadata_falls_back_to_the_generic_warning(caplog: Any) -> None:
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    result, _, _ = _run(_CannedResponse(""))

    assert result is False
    assert [record for record in caplog.records if record.getMessage().startswith(_PARSE_FAIL)]
    assert not _truncation_messages(caplog)


def test_apply_gate_rejection_is_not_reported_as_truncation(caplog: Any) -> None:
    """A parsed-but-unsafe payload is rejected after parsing, not truncated."""
    caplog.set_level(logging.WARNING, logger=_LOGGER)

    payload = (
        '{"user": {}, "history": {}, "newFacts": "not-a-list", '
        '"factsToRemove": [{"id": "fact-123"}]}'
    )
    result, storage, _ = _run(_CannedResponse(payload, {"finish_reason": "length"}))

    assert result is False
    assert storage.save_calls == 0
    assert [record for record in caplog.records if record.getMessage().startswith(_PARSE_FAIL)]
    assert not _truncation_messages(caplog)
