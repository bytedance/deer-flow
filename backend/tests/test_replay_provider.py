from __future__ import annotations

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict
from replay_provider import ReplayChatModel, caller_identity, hash_messages, hash_replay_input


def _write_fixture(path: Path, turns: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "scenario": "unit",
                "mode": "unit",
                "model": "replay",
                "prompt": "unit",
                "context": {},
                "turns": turns,
            }
        ),
        encoding="utf-8",
    )


def test_replay_key_includes_caller_identity(tmp_path: Path):
    messages = [HumanMessage(content="same conversation")]
    lead_output = AIMessage(content="lead")
    suggest_output = AIMessage(content="suggest")
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "lead_agent",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="lead_agent"),
                "output": messages_to_dict([lead_output])[0],
            },
            {
                "caller": "suggest_agent",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="suggest_agent"),
                "output": messages_to_dict([suggest_output])[0],
            },
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert model.invoke(messages, config={"run_name": "suggest_agent"}).content == "suggest"
    assert model.invoke(messages, config={"run_name": "lead_agent"}).content == "lead"


def test_replay_supports_legacy_conversation_only_fixture(tmp_path: Path):
    messages = [HumanMessage(content="legacy conversation")]
    fixture_path = tmp_path / "legacy.json"

    _write_fixture(
        fixture_path,
        [
            {
                "input_hash": hash_messages(messages),
                "output": messages_to_dict([AIMessage(content="legacy")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert model.invoke(messages, config={"run_name": "suggest_agent"}).content == "legacy"


def test_title_run_name_uses_middleware_caller_namespace(tmp_path: Path):
    messages = [HumanMessage(content="title prompt")]
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "middleware:title",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="middleware:title"),
                "output": messages_to_dict([AIMessage(content="generated title")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))

    assert caller_identity(name="title_agent") == "middleware:title"
    assert model.invoke(messages, config={"run_name": "title_agent"}).content == "generated title"


def test_replay_uses_single_pending_capture_when_run_manager_is_missing(tmp_path: Path):
    messages = [HumanMessage(content="title prompt")]
    fixture_path = tmp_path / "fixture.json"

    _write_fixture(
        fixture_path,
        [
            {
                "caller": "middleware:title",
                "conversation_hash": hash_messages(messages),
                "input_hash": hash_replay_input(messages, caller="middleware:title"),
                "output": messages_to_dict([AIMessage(content="generated title")])[0],
            }
        ],
    )

    model = ReplayChatModel(fixture=str(fixture_path))
    model._run_callers["captured-run"] = caller_identity(name="title_agent", tags=["middleware:title"])

    assert model._match(messages, run_manager=None).content == "generated title"
