"""Memory retention must not depend on lexical guesses about user intent."""

from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from test_memory_updater import _make_memory, _make_updater, _memory_config

from deerflow.agents.memory.backends.deermem.deer_mem import DeerMem
from deerflow.agents.memory.backends.deermem.deermem.core.updater import _strip_upload_mentions_from_memory


def test_short_contextual_confirmation_is_preserved(tmp_path):
    messages = [HumanMessage(content="What are my preferences?"), AIMessage(content="Do you always prefer Chinese replies?"), HumanMessage(content="\u662f\u7684"), AIMessage(content="Understood.")]
    memory = DeerMem(backend_config={"storage_path": str(tmp_path)})

    prepared = memory._prepare_update(messages)

    assert prepared is not None
    assert prepared[0] == messages


@pytest.mark.parametrize("content", ["User builds file upload systems for a living.", "User prefers uploading documents through the browser."])
def test_upload_words_cannot_delete_stored_memory(content):
    memory = _make_memory([{"id": "a", "content": content}])
    memory["user"]["workContext"]["summary"] = content
    expected = deepcopy(memory)
    assert _strip_upload_mentions_from_memory(memory) == expected


def test_regex_reinforcement_cannot_confirm_existing_fact():
    updater = _make_updater(config=_memory_config(fact_eviction_policy="hybrid-v1"))
    memory = _make_memory([{"id": "a", "content": "User prefers concise replies", "category": "preference", "confidence": 0.9}])
    result = updater._apply_updates(memory, {"factsToReinforce": [{"id": "a", "scope": "user", "reason": "quoted positive phrase"}]}, signals=frozenset({"reinforcement"}))
    assert result["facts"][0].get("confirmationCount", 0) == 0


def test_extraction_prompt_does_not_prescribe_confirmation_or_confidence():
    updater = _make_updater()
    _, prompt = updater._prepare_update_prompt(
        [HumanMessage(content="The phrase 'yes, exactly' was quoted from a book.")],
        agent_name=None,
        signals=frozenset({"reinforcement"}),
    )
    system = "\n".join(message.content for message in prompt if message.type == "system")
    assert '"factsToReinforce": []' in system
    assert "confidence >= 0.95" not in system
    assert "3-5 concurrent focus themes" not in system
