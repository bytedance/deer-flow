"""Honcho captures checkpoint history incrementally through the real HTTP client."""

import asyncio
import json
import math
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.memory.backends.honcho import honcho_manager
from deerflow.agents.memory.backends.honcho.client import HonchoClient
from deerflow.agents.middlewares import memory_middleware
from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware
from deerflow.config.memory_config import MemoryConfig

SOURCE_ID = "deerflow_source_id"


class MessageStore:
    """Emulate append-only messages and Honcho's metadata-filtered offset pages."""

    def __init__(self):
        self.messages = defaultdict(list)
        self.batches = []
        self.lookups = []
        self.fail_write = None
        self.write_count = 0
        self.lose_response = False
        self.list_error = None
        self.page_size = 2

    def receive(self, request):
        path = request.url.path
        body = json.loads(request.content)
        if path.endswith("/messages/list"):
            self.lookups.append(request)
            if self.list_error is not None:
                return self.list_error
            filters = body["filters"]["OR"]
            assert 0 < len(filters) <= 100
            keys = {entry["metadata"][SOURCE_ID] for entry in filters}
            items = [item for item in self.messages[path.removesuffix("/list")] if item.get("metadata", {}).get(SOURCE_ID) in keys]
            page = int(request.url.params["page"])
            size = min(int(request.url.params["size"]), self.page_size)
            return httpx.Response(200, json={"items": items[(page - 1) * size : page * size], "page": page, "pages": math.ceil(len(items) / size), "total": len(items)})
        if path.endswith("/messages"):
            incoming = body["messages"]
            if not 0 < len(incoming) <= 100:
                return httpx.Response(422, json={"detail": "message batch size"})
            self.write_count += 1
            if self.write_count == self.fail_write and not self.lose_response:
                return httpx.Response(503, json={"detail": "unavailable"})
            self.messages[path].extend(incoming)
            self.batches.append(incoming)
            if self.write_count == self.fail_write:
                raise httpx.ReadTimeout("response lost after commit", request=request)
        return httpx.Response(200, json={})

    def contents(self):
        return [item["content"] for batch in self.batches for item in batch]


@pytest.fixture
def capture(monkeypatch):
    store = MessageStore()
    managers = []
    monkeypatch.setattr(honcho_manager, "HonchoClient", lambda config: HonchoClient(config, transport=httpx.MockTransport(store.receive)))

    def create(**config):
        manager = honcho_manager.HonchoMemoryManager.from_config({"base_url": "https://honcho.invalid", **config})
        managers.append(manager)
        monkeypatch.setattr(memory_middleware, "get_memory_manager", lambda: manager)
        return manager

    create()
    yield create, store
    for manager in managers:
        manager.close()


def run_turns(*, asynchronous, repeat_text=False, separate_threads=False, turns=3):
    agent = create_agent(
        model=FakeMessagesListChatModel(responses=[AIMessage(content=f"Answer {n}") for n in range(turns)]),
        middleware=[MemoryMiddleware(memory_config=MemoryConfig(enabled=True))],
        checkpointer=InMemorySaver(),
    )

    async def run():
        for n in range(turns):
            thread_id = f"thread-{n}" if separate_threads else "thread-1"
            state = {"messages": [HumanMessage(content="Please continue" if repeat_text else f"Question {n}")]}
            config = {"configurable": {"thread_id": thread_id}}
            context = {"thread_id": thread_id, "user_id": "repro-user"}
            if asynchronous:
                await agent.ainvoke(state, config, context=context)
            else:
                agent.invoke(state, config, context=context)

    asyncio.run(run())


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_acknowledged_history_is_not_resubmitted(capture, asynchronous):
    _, store = capture
    run_turns(asynchronous=asynchronous)
    assert [len(batch) for batch in store.batches] == [2, 2, 2]


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_same_text_in_distinct_turns_is_preserved_once_per_turn(capture, asynchronous):
    _, store = capture
    run_turns(asynchronous=asynchronous, repeat_text=True)
    assert store.contents().count("Please continue") == 3


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_first_turn_control(capture, asynchronous):
    _, store = capture
    run_turns(asynchronous=asynchronous, turns=1)
    assert [len(batch) for batch in store.batches] == [2]


@pytest.mark.parametrize("asynchronous", [False, True], ids=["sync", "async"])
def test_independent_threads_control(capture, asynchronous):
    _, store = capture
    run_turns(asynchronous=asynchronous, separate_threads=True, repeat_text=True)
    assert [len(batch) for batch in store.batches] == [2, 2, 2]
    assert len(store.messages) == 3


def test_restart_and_compacted_overlap_use_remote_identity(capture):
    create, store = capture
    messages = [HumanMessage("question", id="h1"), AIMessage("answer", id="a1"), HumanMessage("next", id="h2")]
    original = messages_to_dict(messages)
    first = create()
    first.add("thread", messages[:2], user_id="alice")
    first.close()
    second = create()
    second.add("thread", messages[1:], user_id="alice")
    second.add_nowait("thread", messages, user_id="alice")
    assert store.contents() == ["question", "answer", "next"]
    assert any(request.url.params["page"] == "2" for request in store.lookups)
    assert messages_to_dict(messages) == original


def test_distinct_sources_edits_and_roles_are_not_text_deduplicated(capture):
    create, store = capture
    manager = create()
    h1 = HumanMessage("same", id="h1")
    messages = [h1, h1, HumanMessage("same", id="h2"), HumanMessage("edited", id="h1"), AIMessage("same", id="h1")]
    manager.add("thread", messages, user_id="alice")
    manager.add("thread", messages, user_id="alice")
    assert store.contents() == ["same", "same", "edited", "same"]
    assert len({item["metadata"][SOURCE_ID] for item in store.batches[0]}) == 4


def test_shared_workspace_peer_and_message_ids_still_preserve_each_user(capture):
    create, store = capture
    manager = create(workspace_overrides={"alice": "shared", "bob": "shared"}, user_peer_overrides={"alice": "shared-peer", "bob": "shared-peer"})
    messages = [HumanMessage("same", id="same")]
    for user in ("alice", "bob", "alice", "bob"):
        manager.add("thread", messages, user_id=user)
    assert store.contents() == ["same", "same"]


def test_idless_callers_keep_append_behavior(capture):
    create, store = capture
    manager = create()
    for _ in range(2):
        manager.add("thread", [HumanMessage("same")], user_id="alice")
    assert store.contents() == ["same", "same"]
    assert not store.lookups


def test_same_source_id_in_independent_threads_is_not_suppressed(capture):
    create, store = capture
    manager = create()
    message = HumanMessage("same", id="h1")
    for thread_id in ("first", "second", "first", "second"):
        manager.add(thread_id, [message], user_id="alice")
    assert store.contents() == ["same", "same"]


def test_malformed_later_lookup_page_does_not_publish_partial_results(capture, monkeypatch):
    create, store = capture
    manager = create()
    messages = [HumanMessage(str(n), id=str(n)) for n in range(4)]
    manager.add("thread", messages[:3], user_id="alice")
    original = manager._client._post

    def post(path, payload):
        if "/messages/list?page=2" in path:
            return {"items": [None], "page": 2, "pages": 2}
        return original(path, payload)

    monkeypatch.setattr(manager._client, "_post", post)
    manager.add("thread", messages, user_id="alice")
    assert store.contents() == ["0", "1", "2"]
    monkeypatch.setattr(manager._client, "_post", original)
    manager.add("thread", messages, user_id="alice")
    assert store.contents() == ["0", "1", "2", "3"]


@pytest.mark.parametrize("lost_response", [False, True])
def test_retry_reconciles_failed_or_committed_writes(capture, lost_response, caplog):
    create, store = capture
    messages = [HumanMessage("first", id="h1"), AIMessage("reply", id="a1"), HumanMessage("next", id="h2")]
    store.fail_write = 1
    store.lose_response = lost_response
    create().add("thread", messages[:2], user_id="alice")
    assert "write failed for thread thread" in caplog.text
    assert "capture lookup failed" not in caplog.text
    create().add("thread", messages, user_id="alice")
    assert store.contents() == ["first", "reply", "next"]


def test_batched_retry_preserves_already_committed_prefix(capture):
    create, store = capture
    store.page_size = 10
    messages = [HumanMessage(f"message {n}", id=f"h{n}") for n in range(105)]
    store.fail_write = 2
    create().add("thread", messages, user_id="alice")
    assert len(store.contents()) == 100
    create().add("thread", messages, user_id="alice")
    assert store.contents() == [message.content for message in messages]
    assert [len(batch) for batch in store.batches] == [100, 5]


@pytest.mark.parametrize("growing", [False, True], ids=["excessive-total", "growing-total"])
def test_lookup_page_limit_aborts_capture_without_partial_results(capture, monkeypatch, caplog, growing):
    create, store = capture
    manager = create()
    message = HumanMessage("private-history", id="h1")
    manager.add("thread", [message], user_id="alice")
    original = manager._client._post
    requested_pages = []

    def post(path, payload):
        if "/messages/list?" not in path:
            return original(path, payload)
        page = int(httpx.URL(path).params["page"])
        requested_pages.append(page)
        # Keep the pre-fix implementation finite without providing its bound.
        if len(requested_pages) > 10:
            raise AssertionError("lookup exceeded the test's request budget")
        return {"items": store.batches[0], "page": page, "pages": page + 1 if growing else 1_000_000}

    monkeypatch.setattr(manager._client, "_post", post)
    manager.add("thread", [message, HumanMessage("next", id="h2")], user_id="alice")
    assert requested_pages == (list(range(1, 11)) if growing else [1])
    assert store.write_count == 1
    assert store.contents() == ["private-history"]
    assert "capture lookup failed" in caplog.text
    assert "page limit" in caplog.text
    assert "private-history" not in caplog.text
    monkeypatch.setattr(manager._client, "_post", original)
    manager.add("thread", [message, HumanMessage("next", id="h2")], user_id="alice")
    assert store.contents() == ["private-history", "next"]


def test_lookup_accepts_duplicate_source_records_through_last_allowed_page(capture):
    create, store = capture
    manager = create()
    message = HumanMessage("first", id="h1")
    manager.add("thread", [message], user_id="alice")
    records = next(iter(store.messages.values()))
    records.extend([records[0]] * 9)
    store.page_size = 1
    store.lookups.clear()
    manager.add("thread", [message, HumanMessage("next", id="h2")], user_id="alice")
    assert [int(request.url.params["page"]) for request in store.lookups] == list(range(1, 11))
    assert store.contents() == ["first", "next"]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, json={"detail": "session read permission required"}),
        httpx.Response(503, json={"detail": "unavailable"}),
        httpx.Response(200, json={}),
        httpx.Response(200, json={"items": "invalid", "page": 1, "pages": 1}),
        httpx.Response(200, json={"items": [], "page": 1, "pages": True}),
        httpx.Response(200, json={"items": [], "page": 2, "pages": 2}),
        httpx.Response(200, json={"items": [{"metadata": {SOURCE_ID: "not-requested"}}], "page": 1, "pages": 1}),
    ],
)
def test_lookup_failure_does_not_blindly_replay(capture, response, caplog):
    create, store = capture
    manager = create()
    messages = [HumanMessage("private-history", id="h1")]
    manager.add("thread", messages, user_id="alice")
    store.list_error = response
    manager.add("thread", messages + [HumanMessage("next", id="h2")], user_id="alice")
    assert store.contents() == ["private-history"]
    assert store.write_count == 1
    assert "capture lookup failed for thread thread" in caplog.text
    assert "write failed" not in caplog.text
    assert "private-history" not in caplog.text
    store.list_error = None
    manager.add("thread", messages + [HumanMessage("next", id="h2")], user_id="alice")
    assert store.contents() == ["private-history", "next"]


def test_concurrent_managers_share_session_capture_lock(capture, monkeypatch):
    create, store = capture
    managers = [create(), create()]
    start = Barrier(2)
    messages = [HumanMessage("hello", id="h1")]
    original = HonchoClient.add_messages

    def write(client, *args):
        # The publication must still own the same session lock as the lookup.
        lock = honcho_manager._capture_lock("https://honcho.invalid", args[0], args[1])
        with ThreadPoolExecutor(max_workers=1) as probe:

            def acquire_elsewhere():
                acquired = lock.acquire(blocking=False)
                if acquired:
                    lock.release()
                return acquired

            assert not probe.submit(acquire_elsewhere).result(timeout=5)
        original(client, *args)

    monkeypatch.setattr(HonchoClient, "add_messages", write)

    def run(manager):
        start.wait(timeout=5)
        manager.add("thread", messages, user_id="alice")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(run, managers))
    assert store.contents() == ["hello"]
