"""Malformed extractor summaries preserve existing user-global memory."""

import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import (
    FileMemoryStorage,
)
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater

_SUMMARY_SECTIONS = [
    ("user", "workContext"),
    ("user", "personalContext"),
    ("user", "topOfMind"),
    ("user", "cognitiveStyle"),
    ("history", "recentMonths"),
    ("history", "earlierContext"),
    ("history", "longTermBackground"),
]


class _Extractor:
    def __init__(self, response: dict[str, Any]):
        self.response = response
        self.calls = 0

    def invoke(self, prompt: Any, config: Any = None) -> AIMessage:
        self.calls += 1
        return AIMessage(content=json.dumps(self.response))


@pytest.mark.parametrize("group,section", _SUMMARY_SECTIONS)
@pytest.mark.parametrize(
    "summary",
    [
        pytest.param(["Software engineer"], id="list"),
        pytest.param({"occupation": "engineer"}, id="object"),
        pytest.param(42, id="integer"),
        pytest.param(1.5, id="float"),
        pytest.param(True, id="boolean"),
        pytest.param(None, id="null"),
        pytest.param("", id="empty"),
        pytest.param("Updated valid text", id="string"),
    ],
)
def test_extracted_summary_value_preserves_memory_and_consumes_batch(tmp_path: Path, group: str, section: str, summary: Any) -> None:
    config = DeerMemConfig(storage_path=str(tmp_path), retrieval_adapter="")
    storage = FileMemoryStorage(config)
    previous = {
        "summary": "User is a software engineer",
        "updatedAt": "2026-11-01T00:00:00Z",
    }
    storage.update_summaries({group: {section: previous}}, user_id="alice")
    assert storage.reload("researcher", user_id="alice")[group][section] == previous

    # A valid sibling update and fact must still commit beside a bad section.
    sibling_group, sibling_section = ("history", "recentMonths") if group == "user" else ("user", "workContext")
    response: dict[str, Any] = {
        "user": {},
        "history": {},
        "newFacts": [
            {
                "content": "User prefers dark mode",
                "category": "preference",
                "confidence": 0.9,
                "scope": "user",
                "durability": "durable",
                "authority": "descriptive",
            }
        ],
    }
    response[group][section] = {
        "shouldUpdate": True,
        "summary": summary,
        "scope": "user",
        "authority": "descriptive",
    }
    response[sibling_group][sibling_section] = {
        "shouldUpdate": True,
        "summary": "User prefers concise updates",
        "scope": "user",
        "authority": "descriptive",
    }
    model = _Extractor(response)
    messages = [HumanMessage(content="Please remember that I prefer dark mode", id="message-1")]
    updater = MemoryUpdater(config, storage, model)

    assert updater.update_memory(messages, thread_id="thread-1", agent_name="researcher", user_id="alice") is True

    # Reopen real storage so cache state cannot conceal a corrupted manifest.
    reopened = FileMemoryStorage(config)
    document = reopened.reload("researcher", user_id="alice")
    assert [fact["content"] for fact in document["facts"]] == ["User prefers dark mode"]
    assert document[sibling_group][sibling_section]["summary"] == "User prefers concise updates"
    if isinstance(summary, str) and summary:
        assert document[group][section]["summary"] == "Updated valid text"
        assert document[group][section]["updatedAt"] != previous["updatedAt"]
    else:
        assert document[group][section] == previous

    # The persisted watermark also survives a restart, avoiding paid re-extraction.
    restarted_updater = MemoryUpdater(config, reopened, model)
    assert restarted_updater.update_memory(messages, thread_id="thread-1", agent_name="researcher", user_id="alice") is True
    assert model.calls == 1
