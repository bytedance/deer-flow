from __future__ import annotations

import json
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.middlewares.message_archive_hook import MessageArchiveHook, message_archive_hook
from deerflow.agents.middlewares.summarization_middleware import SummarizationEvent
from langgraph.runtime import Runtime


def _event(
    messages_to_summarize,
    thread_id: str | None = "thread-abc",
    agent_name: str | None = None,
) -> SummarizationEvent:
    runtime = Runtime(context={"thread_id": thread_id} if thread_id else {})
    return SummarizationEvent(
        messages_to_summarize=tuple(messages_to_summarize),
        preserved_messages=(),
        thread_id=thread_id,
        agent_name=agent_name,
        runtime=runtime,
    )


def _msgs(*contents: str) -> list:
    msgs = []
    for i, content in enumerate(contents):
        if i % 2 == 0:
            msgs.append(HumanMessage(content=content, id=f"id-{i}"))
        else:
            msgs.append(AIMessage(content=content, id=f"id-{i}"))
    return msgs


# ---------------------------------------------------------------------------
# Basic write
# ---------------------------------------------------------------------------


def test_hook_writes_messages_to_archive(tmp_path):
    hook = MessageArchiveHook()
    msgs = _msgs("hello", "world")

    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="user1"):
        mock_paths.return_value.thread_dir.return_value = tmp_path / "thread-abc"
        hook(_event(msgs))

    archive = tmp_path / "thread-abc" / "message_archive.jsonl"
    assert archive.exists()
    lines = [json.loads(l) for l in archive.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    assert lines[0]["content"] == "hello"
    assert lines[1]["content"] == "world"
    assert lines[0]["id"] == "id-0"
    assert lines[1]["id"] == "id-1"


def test_hook_creates_parent_directory_if_missing(tmp_path):
    hook = MessageArchiveHook()
    msgs = _msgs("hi")
    thread_dir = tmp_path / "users" / "u1" / "threads" / "t1"
    assert not thread_dir.exists()

    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="u1"):
        mock_paths.return_value.thread_dir.return_value = thread_dir
        hook(_event(msgs, thread_id="t1"))

    assert (thread_dir / "message_archive.jsonl").exists()


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_hook_deduplicates_across_cycles(tmp_path):
    hook = MessageArchiveHook()
    cycle1 = [HumanMessage(content="m1", id="id-0"), AIMessage(content="m2", id="id-1")]
    cycle2 = [HumanMessage(content="m3", id="id-2"), AIMessage(content="m4", id="id-3")]

    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="user1"):
        mock_paths.return_value.thread_dir.return_value = tmp_path / "t1"
        hook(_event(cycle1))
        # Second cycle with overlapping + new messages
        hook(_event(cycle1 + cycle2))  # cycle1 already archived

    archive = tmp_path / "t1" / "message_archive.jsonl"
    lines = [json.loads(l) for l in archive.read_text().splitlines() if l.strip()]
    ids = [l["id"] for l in lines]
    # cycle1 messages should appear exactly once
    assert ids.count("id-0") == 1
    assert ids.count("id-2") == 1
    assert len(ids) == 4  # id-0, id-1, id-2, id-3


def test_hook_skips_message_without_id(tmp_path):
    hook = MessageArchiveHook()
    msgs = [HumanMessage(content="no-id-msg")]  # id=None

    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="user1"):
        mock_paths.return_value.thread_dir.return_value = tmp_path / "t1"
        hook(_event(msgs))

    archive = tmp_path / "t1" / "message_archive.jsonl"
    lines = [json.loads(l) for l in archive.read_text().splitlines() if l.strip()]
    assert len(lines) == 1  # written, just no id to dedup on


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_hook_skips_when_thread_id_is_none():
    hook = MessageArchiveHook()
    hook(_event(_msgs("hi"), thread_id=None))


def test_hook_skips_corrupt_lines_on_dedup_read(tmp_path):
    hook = MessageArchiveHook()
    thread_dir = tmp_path / "t1"
    thread_dir.mkdir(parents=True)
    archive = thread_dir / "message_archive.jsonl"
    # Pre-populate with one valid line and one corrupt line
    archive.write_text('{"id": "id-0", "type": "human", "content": "old"}\n{CORRUPT JSON\n')

    # id-0 is pre-existing; id-1 is new
    msgs = [HumanMessage(content="old-msg", id="id-0"), AIMessage(content="new-msg", id="id-1")]
    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="u1"):
        mock_paths.return_value.thread_dir.return_value = thread_dir
        hook(_event(msgs))  # msgs[0] has id "id-0" — should be deduped

    lines = [l for l in archive.read_text().splitlines() if l.strip()]
    ids = []
    for l in lines:
        try:
            ids.append(json.loads(l)["id"])
        except Exception:
            pass
    # id-0 was already present → not duplicated; id-1 is new
    assert ids.count("id-0") == 1
    assert "id-1" in ids


def test_hook_does_not_crash_on_permission_error(tmp_path):
    hook = MessageArchiveHook()
    msgs = _msgs("hi")

    with patch("deerflow.agents.middlewares.message_archive_hook.get_paths") as mock_paths, \
         patch("deerflow.agents.middlewares.message_archive_hook.get_effective_user_id", return_value="u1"):
        mock_paths.return_value.thread_dir.side_effect = ValueError("invalid thread_id")
        hook(_event(msgs))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


def test_module_exposes_singleton():
    assert isinstance(message_archive_hook, MessageArchiveHook)
