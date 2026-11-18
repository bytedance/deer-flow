"""Tests for the extraction watermark (skip already-extracted messages).

The updater keeps a bounded in-process LRU and, with file storage, persists the
same watermark to ``agents/{agent}/.metadata/watermarks.json`` so a restarted
process or a peer replica on the same storage root does not re-extract turns.
"""

from __future__ import annotations

import errno
import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.agents.memory.backends.deermem.deermem.config import DeerMemConfig
from deerflow.agents.memory.backends.deermem.deermem.core.storage import FileMemoryStorage, MemoryStorage
from deerflow.agents.memory.backends.deermem.deermem.core.updater import MemoryUpdater, _message_identity


class _FakeLLM:
    """Returns a canned empty-update response; counts invocations."""

    def __init__(self) -> None:
        self.invoke_count = 0
        self._response = _EmptyResponse()

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.invoke_count += 1
        return self._response


class _EmptyResponse:
    content = json.dumps(
        {
            "user": {},
            "history": {},
            "newFacts": [],
            "factsToRemove": [],
            "staleFactsToRemove": [],
            "staleFactsToExtend": [],
            "factsToConsolidate": [],
        }
    )
    usage_metadata: dict[str, int] | None = None


class _FakeStorage(MemoryStorage):
    """Minimal in-memory storage stub (load/save) for the save() path."""

    def __init__(self) -> None:
        self.memory: dict[str, Any] = {"version": "2.0", "revision": 0, "user": {}, "history": {}, "facts": []}

    def load(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return json.loads(json.dumps(self.memory))

    def reload(self, agent_name: str | None = None, *, user_id: str | None = None) -> dict[str, Any]:
        return self.load(agent_name, user_id=user_id)

    def save(self, memory_data: dict[str, Any], agent_name: str | None = None, *, user_id: str | None = None, expected_revision: int | None = None) -> bool:
        self.memory = json.loads(json.dumps(memory_data))
        return True


def _config(**overrides: Any) -> DeerMemConfig:
    base: dict[str, Any] = {}
    base.update(overrides)
    return DeerMemConfig(**base)


def _msgs(*texts: str) -> list[Any]:
    out: list[Any] = []
    for t in texts:
        out.append(HumanMessage(content=t))
        out.append(AIMessage(content=f"reply-{t}"))
    return out


def test_watermark_skips_already_extracted_messages() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")

    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1

    # Same messages again -> nothing new since the watermark -> skipped, no LLM call.
    result = updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert result is True
    assert llm.invoke_count == 1


def test_watermark_feeds_only_new_messages_on_growth() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1

    # Append a new turn; only the new turn is fed (watermark = prior length).
    messages += _msgs("second")
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_is_per_thread() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    messages = _msgs("first")
    # Thread t1 extracts; thread t2 has its own watermark (starts at 0).
    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(messages, thread_id="t2", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_resets_when_conversation_shrinks() -> None:
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    long_msgs = _msgs("first", "second", "third")
    updater.update_memory(long_msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    # A shorter message list (e.g. after summarization) must not get stuck at a
    # watermark past the end; it re-extracts from the start.
    short_msgs = _msgs("only")
    updater.update_memory(short_msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_front_removal_does_not_skip_pending_tail() -> None:
    """Regression: an index watermark skips un-extracted turns when
    summarization removes the conversation front. The watermark is
    content/identity based, so after a front removal it finds the last-extracted
    message at its NEW index and feeds the real pending tail instead of slicing
    past the (now shorter) list.

    Setup: 6 messages; pre-set the watermark to msg[3] so msgs[0..3] are
    "already extracted" and msgs[4..5] are pending. Summarization then removes
    the front pair (msgs[0..1]). The surviving 4-message list must still feed
    the pending pair (msgs[4..5]) -- an index watermark (=4) would slice [4:]
    on a 4-element list and feed nothing, losing them.
    """
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b", "c")  # [H a, A ra, H b, A rb, H c, A rc]
    updater._watermarks[("t1", "u", "a")] = _message_identity(msgs[3])  # ...A rb extracted
    surviving = msgs[2:]  # summarization removed the front pair
    updater.update_memory(surviving, thread_id="t1", agent_name="a", user_id="u")
    # The pending tail (H c, A rc) was fed -> exactly one extraction.
    assert llm.invoke_count == 1


def test_emergency_flush_bypasses_watermark_and_does_not_regress() -> None:
    """Regression: the emergency (summarization) flush path
    bypasses the watermark -- it extracts its subset in full and does NOT
    advance the conversation watermark (advancing from the subset's own last
    message, which is older than the conversation's latest, would regress it
    and skip the real tail on the next normal feed)."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(), _FakeStorage(), llm)
    msgs = _msgs("a", "b")  # [H a, A ra, H b, A rb]
    key = ("t1", "u", "a")
    updater._watermarks[key] = _message_identity(msgs[1])  # ...A ra extracted; H b, A rb pending
    # Emergency flush of the front subset about to be removed.
    updater.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1  # subset extracted in full
    # Watermark did not regress to the subset's last message.
    assert updater._watermarks[key] == _message_identity(msgs[1])
    # A subsequent normal feed of the full conversation still extracts the tail.
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2


def test_watermark_cache_is_bounded_lru() -> None:
    """The watermark cache is a bounded LRU: over capacity it drops the
    least-recently-used key, and a dropped key re-extracts one batch on the
    next turn for that thread (no loss)."""
    llm = _FakeLLM()
    updater = MemoryUpdater(_config(watermark_max_keys=2), _FakeStorage(), llm)
    msgs = _msgs("first")
    # Three distinct threads fill the cache (cap=2); the least-recently-used
    # key (t1) is evicted.
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    updater.update_memory(msgs, thread_id="t2", agent_name="a", user_id="u")
    updater.update_memory(msgs, thread_id="t3", agent_name="a", user_id="u")
    assert len(updater._watermarks) == 2
    assert ("t1", "u", "a") not in updater._watermarks  # evicted (LRU)
    # t1's next turn finds no watermark -> re-extracts one batch (not skipped).
    updater.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 4  # t1, t2, t3, then t1 re-extract


# ── Persisted watermark (``.metadata/watermarks.json``) ──────────────────


class _RecordingLLM(_FakeLLM):
    """``_FakeLLM`` that also keeps each prompt, to check what was fed."""

    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def invoke(self, prompt: Any, config: Any = None) -> Any:
        self.prompts.append(str(prompt))
        return super().invoke(prompt, config)


def _file_updater(root: Path, llm: _FakeLLM | None = None, **overrides: Any) -> MemoryUpdater:
    """Build an updater over real file storage, the way a fresh process or a
    peer replica sharing ``storage_path`` would."""
    config = _config(storage_path=str(root), retrieval_adapter="", **overrides)
    return MemoryUpdater(config, FileMemoryStorage(config), llm or _RecordingLLM())


def _sidecar(root: Path, *, user_id: str = "u", agent_name: str = "a") -> Path:
    return root / "users" / user_id / "agents" / agent_name / ".metadata" / "watermarks.json"


def test_watermark_survives_a_restart(tmp_path: Path) -> None:
    messages = _msgs("first")
    first_llm = _RecordingLLM()
    _file_updater(tmp_path, first_llm).update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert first_llm.invoke_count == 1

    # A new process starts with an empty LRU but reads the persisted watermark.
    llm = _RecordingLLM()
    restarted = _file_updater(tmp_path, llm)
    assert restarted.update_memory(messages, thread_id="t1", agent_name="a", user_id="u") is True
    assert llm.invoke_count == 0

    messages += _msgs("second")
    restarted.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    assert "reply-second" in llm.prompts[0]
    assert "reply-first" not in llm.prompts[0]


def test_peer_updaters_continue_from_each_others_watermark(tmp_path: Path) -> None:
    """Two replicas on one storage root: whichever runs the next update starts
    from the furthest watermark either recorded, even when its own cached entry
    for the thread is stale."""
    llm_a, llm_b = _RecordingLLM(), _RecordingLLM()
    replica_a = _file_updater(tmp_path, llm_a)
    replica_b = _file_updater(tmp_path, llm_b)
    messages = _msgs("first")
    replica_a.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")

    messages += _msgs("second")
    replica_b.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm_b.invoke_count == 1
    assert "reply-first" not in llm_b.prompts[0]

    # Replica A's cache still points at the first turn; the sidecar is further.
    messages += _msgs("third")
    replica_a.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm_a.invoke_count == 2
    assert "reply-third" in llm_a.prompts[1]
    assert "reply-second" not in llm_a.prompts[1]


def test_clearing_memory_removes_the_persisted_watermark(tmp_path: Path) -> None:
    """Scoped and user-wide clears delete the watermark sidecar together with
    the other ``.metadata`` sidecars of the cleared agent."""
    messages = _msgs("first")
    updater = _file_updater(tmp_path)

    updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert _sidecar(tmp_path).is_file()
    updater.clear_memory_data("a", user_id="u")
    assert not _sidecar(tmp_path).exists()

    updater.update_memory(messages, thread_id="t2", agent_name="a", user_id="u")
    assert _sidecar(tmp_path).is_file()
    updater.clear_all_memory_data(user_id="u")
    assert not _sidecar(tmp_path).parent.exists()

    # A fresh process finds no watermark for the cleared scope.
    llm = _RecordingLLM()
    _file_updater(tmp_path, llm).update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1


def test_persisted_watermarks_are_capped_by_watermark_max_keys(tmp_path: Path) -> None:
    messages = _msgs("first")
    updater = _file_updater(tmp_path, watermark_max_keys=2)
    for thread_id in ("t1", "t2", "t3"):
        updater.update_memory(messages, thread_id=thread_id, agent_name="a", user_id="u")
    assert sorted(json.loads(_sidecar(tmp_path).read_text(encoding="utf-8"))) == ["t2", "t3"]

    llm = _RecordingLLM()
    restarted = _file_updater(tmp_path, llm, watermark_max_keys=2)
    restarted.update_memory(messages, thread_id="t3", agent_name="a", user_id="u")
    assert llm.invoke_count == 0
    # The least-recently-advanced thread was dropped: it re-extracts one batch.
    restarted.update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1


def test_persisted_watermark_is_scoped_to_its_user_and_agent(tmp_path: Path) -> None:
    messages = _msgs("first")
    _file_updater(tmp_path).update_memory(messages, thread_id="t1", agent_name="a", user_id="u1")

    llm = _RecordingLLM()
    other = _file_updater(tmp_path, llm)
    other.update_memory(messages, thread_id="t1", agent_name="a", user_id="u2")
    other.update_memory(messages, thread_id="t1", agent_name="b", user_id="u1")
    assert llm.invoke_count == 2

    other.update_memory(messages, thread_id="t1", agent_name="a", user_id="u1")
    assert llm.invoke_count == 2


def test_emergency_flush_neither_reads_nor_advances_the_persisted_watermark(tmp_path: Path) -> None:
    msgs = _msgs("a", "b")
    _file_updater(tmp_path).update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u")
    before = _sidecar(tmp_path).read_bytes()

    llm = _RecordingLLM()
    restarted = _file_updater(tmp_path, llm)
    restarted.update_memory(msgs[:2], thread_id="t1", agent_name="a", user_id="u", bypass_watermark=True)
    assert llm.invoke_count == 1
    assert _sidecar(tmp_path).read_bytes() == before

    restarted.update_memory(msgs, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 2
    assert "reply-a" not in llm.prompts[1]


def test_an_unidentifiable_last_message_keeps_the_persisted_watermark(tmp_path: Path) -> None:
    """A last message with neither id nor text has no identity. Writing that
    through would delete a persisted watermark a peer may have advanced and
    force a full feed on every replica."""
    messages = _msgs("first")
    _file_updater(tmp_path).update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    before = _sidecar(tmp_path).read_bytes()

    llm = _RecordingLLM()
    updater = _file_updater(tmp_path, llm)
    updater.update_memory(messages + _msgs("second") + [AIMessage(content="")], thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 1
    assert _sidecar(tmp_path).read_bytes() == before


def test_persisted_watermark_stores_no_message_text(tmp_path: Path) -> None:
    """Messages without an id fall back to a content identity, which is
    persisted as a digest so the sidecar never holds conversation text."""
    messages = [HumanMessage(content="My passport number is X1234567"), AIMessage(content="Noted, I will remember it.")]
    _file_updater(tmp_path).update_memory(messages, thread_id="t1", agent_name="a", user_id="u")

    raw = _sidecar(tmp_path).read_text(encoding="utf-8")
    assert "X1234567" not in raw
    assert "remember" not in raw
    llm = _RecordingLLM()
    _file_updater(tmp_path, llm).update_memory(messages, thread_id="t1", agent_name="a", user_id="u")
    assert llm.invoke_count == 0


def test_watermark_sidecar_failures_fall_back_to_the_process_cache(tmp_path: Path) -> None:
    class _BrokenSidecarStorage(FileMemoryStorage):
        def get_extraction_watermark(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("sidecar unavailable")

        def set_extraction_watermark(self, *args: Any, **kwargs: Any) -> None:
            raise OSError("sidecar unavailable")

    config = _config(storage_path=str(tmp_path), retrieval_adapter="")
    llm = _RecordingLLM()
    updater = MemoryUpdater(config, _BrokenSidecarStorage(config), llm)
    messages = _msgs("first")

    assert updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u") is True
    assert updater.update_memory(messages, thread_id="t1", agent_name="a", user_id="u") is True
    assert llm.invoke_count == 1


def test_file_storage_round_trips_extraction_watermarks_without_a_manifest_write(tmp_path: Path) -> None:
    storage = FileMemoryStorage(_config(storage_path=str(tmp_path), retrieval_adapter=""))
    assert storage.get_extraction_watermark("t1", agent_name="a", user_id="u") is None

    storage.set_extraction_watermark("t1", ["id", "m1"], agent_name="a", user_id="u")
    storage.set_extraction_watermark("t2", ["id", "m2"], agent_name="a", user_id="u")
    assert storage.get_extraction_watermark("t1", agent_name="a", user_id="u") == ["id", "m1"]
    # A watermark is not memory content: no manifest (and no revision) is written.
    assert not (tmp_path / "users" / "u" / "memory.json").exists()

    storage.set_extraction_watermark("t1", None, agent_name="a", user_id="u")
    storage.set_extraction_watermark("t2", None, agent_name="a", user_id="u")
    assert storage.get_extraction_watermark("t1", agent_name="a", user_id="u") is None
    assert not _sidecar(tmp_path).exists()


def test_malformed_watermark_sidecar_entries_are_ignored(tmp_path: Path) -> None:
    storage = FileMemoryStorage(_config(storage_path=str(tmp_path), retrieval_adapter=""))
    sidecar = _sidecar(tmp_path)
    sidecar.parent.mkdir(parents=True)
    sidecar.write_text("not json", encoding="utf-8")
    assert storage.get_extraction_watermark("t1", agent_name="a", user_id="u") is None

    sidecar.write_text(json.dumps({"t1": "id", "t2": ["id", 2], "t3": []}), encoding="utf-8")
    for thread_id in ("t1", "t2", "t3"):
        assert storage.get_extraction_watermark(thread_id, agent_name="a", user_id="u") is None

    storage.set_extraction_watermark("t4", ["id", "m4"], agent_name="a", user_id="u")
    assert json.loads(sidecar.read_text(encoding="utf-8")) == {"t4": ["id", "m4"]}


def test_unreadable_watermark_sidecar_is_never_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A read error is not an empty sidecar: every write rewrites the whole
    file, so treating it as empty would drop the other threads' watermarks."""
    config = _config(storage_path=str(tmp_path), retrieval_adapter="")
    storage = FileMemoryStorage(config)
    storage.set_extraction_watermark("t1", ["id", "m1"], agent_name="a", user_id="u")
    storage.set_extraction_watermark("t2", ["id", "m2"], agent_name="a", user_id="u")
    sidecar = _sidecar(tmp_path)
    before = sidecar.read_bytes()

    def _fail_on_sidecar(read: Any) -> Any:
        def wrapper(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self.name == "watermarks.json":
                raise OSError(errno.EIO, "Input/output error", str(self))
            return read(self, *args, **kwargs)

        return wrapper

    monkeypatch.setattr(Path, "read_bytes", _fail_on_sidecar(Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", _fail_on_sidecar(Path.read_text))

    with pytest.raises(OSError):
        storage.set_extraction_watermark("t3", ["id", "m3"], agent_name="a", user_id="u")
    with pytest.raises(OSError):
        storage.set_extraction_watermark("t1", None, agent_name="a", user_id="u")
    # Through the updater the extraction still succeeds; only the write-through is skipped.
    llm = _RecordingLLM()
    assert MemoryUpdater(config, storage, llm).update_memory(_msgs("first"), thread_id="t3", agent_name="a", user_id="u") is True
    assert llm.invoke_count == 1

    monkeypatch.undo()
    assert sidecar.read_bytes() == before
    assert storage.get_extraction_watermark("t1", agent_name="a", user_id="u") == ["id", "m1"]
    assert storage.get_extraction_watermark("t2", agent_name="a", user_id="u") == ["id", "m2"]
