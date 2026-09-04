"""Unit tests for the mem0 HTTP memory backend (backends/mem0/)."""

from __future__ import annotations

import asyncio
import threading

import httpx
import pytest

from deerflow.agents.memory.backends.mem0.client import Mem0APIError, Mem0AuthError, Mem0Client
from deerflow.agents.memory.backends.mem0.config import Mem0Config


class TestMem0Config:
    def test_defaults(self) -> None:
        cfg = Mem0Config.from_backend_config({})
        assert cfg.api_key_env == "MEM0_API_KEY"
        assert cfg.base_url == "https://api.mem0.ai"
        assert cfg.allow_insecure_http is False
        assert cfg.top_k == 8
        assert cfg.score_threshold == 0.1
        assert cfg.max_injection_chars == 12000
        assert cfg.timeout_seconds == 10.0
        assert cfg.startup_policy == "fail_fast"
        assert cfg.read_policy == "fail_open"
        assert cfg.write_policy == "log_and_drop"

    def test_custom_values_and_nested_failure_policy(self) -> None:
        cfg = Mem0Config.from_backend_config(
            {
                "api_key_env": "MY_MEM0_KEY",
                "base_url": "http://mem0.local:8888/",
                "allow_insecure_http": True,
                "top_k": 5,
                "score_threshold": 0.3,
                "max_injection_chars": 4000,
                "timeout_seconds": 3,
                "startup_policy": "tolerate",
                "failure_policy": {"read": "fail_closed", "write": "raise"},
            }
        )
        assert cfg.api_key_env == "MY_MEM0_KEY"
        assert cfg.base_url == "http://mem0.local:8888"  # trailing slash stripped
        assert cfg.allow_insecure_http is True
        assert cfg.top_k == 5
        assert cfg.score_threshold == 0.3
        assert cfg.max_injection_chars == 4000
        assert cfg.timeout_seconds == 3.0
        assert cfg.startup_policy == "tolerate"
        assert cfg.read_policy == "fail_closed"
        assert cfg.write_policy == "raise"

    def test_unknown_keys_rejected_except_host_injected(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            Mem0Config.from_backend_config({"typo_knob": 1})
        # Host-injected keys must be tolerated (factory injects storage_path
        # into every backend's backend_config).
        cfg = Mem0Config.from_backend_config({"storage_path": "/tmp/x", "should_keep_hidden_message": None})
        assert cfg.base_url == "https://api.mem0.ai"

    def test_insecure_http_requires_explicit_opt_in(self) -> None:
        with pytest.raises(ValueError, match="allow_insecure_http"):
            Mem0Config.from_backend_config({"base_url": "http://mem0.local:8888"})

    @pytest.mark.parametrize("base_url", ["mem0.local:8888", "ftp://mem0.local", "https:///missing-host"])
    def test_invalid_base_url_rejected(self, base_url: str) -> None:
        with pytest.raises(ValueError, match="base_url"):
            Mem0Config.from_backend_config({"base_url": base_url, "allow_insecure_http": True})

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("startup_policy", "sometimes"),
            ("top_k", 0),
            ("top_k", 1001),
            ("score_threshold", 1.5),
            ("max_injection_chars", 0),
            ("timeout_seconds", 0),
            ("timeout_seconds", float("nan")),
            ("timeout_seconds", float("inf")),
            ("timeout_seconds", float("-inf")),
        ],
    )
    def test_invalid_values_rejected(self, key: str, value: object) -> None:
        with pytest.raises(ValueError):
            Mem0Config.from_backend_config({key: value})

    @pytest.mark.parametrize("policy", ["read", "write"])
    def test_invalid_failure_policy_rejected(self, policy: str) -> None:
        with pytest.raises(ValueError, match=policy):
            Mem0Config.from_backend_config({"failure_policy": {policy: "bogus"}})

    def test_resolve_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = Mem0Config.from_backend_config({})
        monkeypatch.delenv("MEM0_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MEM0_API_KEY"):
            cfg.resolve_api_key()
        monkeypatch.setenv("MEM0_API_KEY", "  ")
        with pytest.raises(ValueError, match="MEM0_API_KEY"):
            cfg.resolve_api_key()
        monkeypatch.setenv("MEM0_API_KEY", "secret-key")
        assert cfg.resolve_api_key() == "secret-key"


def _client(handler) -> Mem0Client:
    return Mem0Client(
        base_url="https://api.mem0.ai",
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )


class TestMem0Client:
    def test_add_memories_payload(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["auth"] = request.headers["authorization"]
            seen["body"] = httpx.QueryParams  # placeholder, replaced below
            import json

            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "PENDING", "event_id": "evt-1"})

        client = _client(handler)
        result = client.add_memories(
            messages=[{"role": "user", "content": "hi"}],
            user_id="u1",
            agent_id="lead_agent",
            run_id="t-1",
        )
        assert result["event_id"] == "evt-1"
        assert seen["path"] == "/v3/memories/add/"
        assert seen["auth"] == "Token test-key"
        assert seen["body"] == {
            "messages": [{"role": "user", "content": "hi"}],
            "user_id": "u1",
            "agent_id": "lead_agent",
            "run_id": "t-1",
        }

    def test_search_memories_returns_results(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            import json

            body = json.loads(request.content)
            assert request.url.path == "/v3/memories/search/"
            assert body == {
                "query": "hobbies",
                "filters": {"user_id": "u1"},
                "top_k": 5,
                "threshold": 0.2,
            }
            return httpx.Response(200, json={"results": [{"id": "m1", "memory": "likes cricket", "score": 0.9}]})

        results = _client(handler).search_memories(query="hobbies", filters={"user_id": "u1"}, top_k=5, threshold=0.2)
        assert results == [{"id": "m1", "memory": "likes cricket", "score": 0.9}]

    def test_list_memories_paginates_and_respects_max_items(self) -> None:
        pages = {
            1: {"results": [{"id": "a"}, {"id": "b"}], "next": "https://x/?page=2"},
            2: {"results": [{"id": "c"}], "next": None},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.params["page"])
            return httpx.Response(200, json=pages[page])

        client = _client(handler)
        assert client.list_memories(filters={"user_id": "u1"}) == [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        assert client.list_memories(filters={"user_id": "u1"}, max_items=2) == [{"id": "a"}, {"id": "b"}]

    def test_delete_all_memories_uses_query_params(self) -> None:
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["path"] = request.url.path
            seen["params"] = dict(request.url.params)
            return httpx.Response(200, json={"message": "deleted"})

        _client(handler).delete_all_memories(user_id="u1", agent_id="lead_agent", run_id=None)
        assert seen == {
            "method": "DELETE",
            "path": "/v1/memories/",
            "params": {"user_id": "u1", "agent_id": "lead_agent"},
        }

    def test_401_raises_auth_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"detail": "invalid key"})

        with pytest.raises(Mem0AuthError):
            _client(handler).ping()

    def test_other_4xx_raises_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"})

        with pytest.raises(Mem0APIError, match="400"):
            _client(handler).list_memories(filters={"user_id": "u1"})

    def test_transport_error_raises_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        with pytest.raises(Mem0APIError, match="boom"):
            _client(handler).ping()

    def test_malformed_json_raises_api_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"not json{")

        with pytest.raises(Mem0APIError, match="malformed JSON"):
            _client(handler).list_memories(filters={"user_id": "u1"})


from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from deerflow.agents.memory.backends.mem0.message_filtering import (  # noqa: E402
    extract_message_text,
    filter_messages_for_memory,
)


def _clarification_kwargs() -> dict:
    return {
        "hide_from_ui": True,
        "human_input_response": {
            "version": 1,
            "kind": "human_input_response",
            "source": "clarification",
            "request_id": "req-1",
            "response_kind": "text",
            "value": "the user answered this",
        },
    }


class TestMessageFiltering:
    def test_keeps_user_and_final_assistant(self) -> None:
        msgs = [HumanMessage(content="hello"), AIMessage(content="hi there")]
        assert filter_messages_for_memory(msgs) == msgs

    def test_drops_tool_messages_and_tool_call_ai(self) -> None:
        tool_ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}])
        msgs = [HumanMessage(content="q"), tool_ai, ToolMessage(content="out", tool_call_id="1"), AIMessage(content="a")]
        assert filter_messages_for_memory(msgs) == [msgs[0], msgs[3]]

    def test_drops_hidden_framework_messages_keeps_clarification(self) -> None:
        hidden = HumanMessage(content="todo reminder", additional_kwargs={"hide_from_ui": True})
        clarification = HumanMessage(content="the user answered this", additional_kwargs=_clarification_kwargs())
        assert filter_messages_for_memory([hidden, clarification]) == [clarification]

    def test_upload_only_human_drops_it_and_following_ai(self) -> None:
        upload_only = HumanMessage(content="<current_uploads>\nfile.pdf\n</current_uploads>")
        ack = AIMessage(content="I see your file")
        followup = HumanMessage(content="what is in it?")
        assert filter_messages_for_memory([upload_only, ack, followup]) == [followup]

    def test_upload_block_stripped_from_mixed_message(self) -> None:
        mixed = HumanMessage(content="<current_uploads>\nf.txt\n</current_uploads>\nsummarize this")
        (kept,) = filter_messages_for_memory([mixed])
        assert extract_message_text(kept) == "summarize this"

    def test_extract_message_text_handles_list_content(self) -> None:
        msg = AIMessage(content=[{"type": "text", "text": "part one"}, "part two"])
        assert extract_message_text(msg) == "part one part two"

    def test_extract_message_text_treats_none_as_empty(self) -> None:
        msg = AIMessage(content="")
        msg.content = None
        assert extract_message_text(msg) == ""


from typing import Any  # noqa: E402

from deerflow.agents.memory.backends.mem0.mem0_manager import Mem0Manager  # noqa: E402


class FakeMem0Client:
    """Test double injected as manager._client (records calls, returns fixtures)."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.deleted: list[dict[str, Any]] = []
        self.search_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.pings = 0
        self.search_results: list[dict[str, Any]] = []
        self.list_results: list[dict[str, Any]] = []
        self.error: Exception | None = None
        self.closed = False

    def _maybe_raise(self) -> None:
        if self.error is not None:
            raise self.error

    def add_memories(self, **kwargs: Any) -> dict[str, Any]:
        self._maybe_raise()
        self.added.append(kwargs)
        return {"status": "PENDING", "event_id": "evt-fake"}

    def search_memories(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._maybe_raise()
        self.search_calls.append(kwargs)
        return self.search_results

    def list_memories(self, **kwargs: Any) -> list[dict[str, Any]]:
        self._maybe_raise()
        self.list_calls.append(kwargs)
        return self.list_results

    def delete_all_memories(self, **kwargs: Any) -> None:
        self._maybe_raise()
        self.deleted.append(kwargs)

    def ping(self) -> None:
        self._maybe_raise()
        self.pings += 1

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _mem0_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mem0Manager resolves the API key eagerly at construction; provide a dummy
    so the suite is hermetic (tests that need it missing delete it themselves)."""
    monkeypatch.setenv("MEM0_API_KEY", "test-key")


def _manager(backend_config: dict | None = None, *, mode: str = "middleware") -> tuple[Mem0Manager, FakeMem0Client]:
    mgr = Mem0Manager(backend_config=backend_config or {}, mode=mode)
    fake = FakeMem0Client()
    mgr._client = fake
    return mgr, fake


class TestMem0ManagerConstruction:
    def test_from_config_fail_fast_pings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEM0_API_KEY", "k")
        fake = FakeMem0Client()
        monkeypatch.setattr(
            "deerflow.agents.memory.backends.mem0.mem0_manager.Mem0Client",
            lambda **kwargs: fake,
        )
        Mem0Manager.from_config({}, mode="middleware")
        assert fake.pings == 1

    def test_from_config_tolerate_skips_ping(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MEM0_API_KEY", "k")
        fake = FakeMem0Client()
        monkeypatch.setattr(
            "deerflow.agents.memory.backends.mem0.mem0_manager.Mem0Client",
            lambda **kwargs: fake,
        )
        mgr = Mem0Manager.from_config({"startup_policy": "tolerate"}, mode="tool")
        assert fake.pings == 0
        assert mgr.mode == "tool"

    def test_from_config_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MEM0_API_KEY", raising=False)
        with pytest.raises(ValueError, match="MEM0_API_KEY"):
            Mem0Manager.from_config({})

    def test_supports_search_enables_tool_mode(self) -> None:
        mgr, _fake = _manager(mode="tool")
        assert mgr.supports_search is True

    def test_close_releases_http_client(self) -> None:
        mgr, fake = _manager()
        mgr.close()
        assert fake.closed is True


class TestMem0ManagerAdd:
    def test_add_maps_filtered_messages_and_identity(self) -> None:
        mgr, fake = _manager()
        tool_ai = AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}])
        mgr.add(
            "thread-1",
            [HumanMessage(content="I prefer dark mode"), tool_ai, AIMessage(content="Noted.")],
            agent_name="lead_agent",
            user_id="u1",
        )
        assert len(fake.added) == 1
        call = fake.added[0]
        assert call["user_id"] == "u1"
        assert call["agent_id"] == "lead_agent"
        assert call["run_id"] == "thread-1"
        assert call["messages"] == [
            {"role": "user", "content": "I prefer dark mode"},
            {"role": "assistant", "content": "Noted."},
        ]

    def test_add_without_optional_ids_uses_run_id_only(self) -> None:
        mgr, fake = _manager()
        mgr.add("thread-9", [HumanMessage(content="hello")])
        call = fake.added[0]
        assert call["user_id"] is None
        assert call["agent_id"] is None
        assert call["run_id"] == "thread-9"

    def test_add_empty_after_filter_is_noop(self) -> None:
        mgr, fake = _manager()
        hidden = HumanMessage(content="internal", additional_kwargs={"hide_from_ui": True})
        mgr.add("thread-1", [hidden], user_id="u1")
        assert fake.added == []

    def test_add_write_error_log_and_drop(self, caplog: pytest.LogCaptureFixture) -> None:
        mgr, fake = _manager()
        fake.error = Mem0APIError("server down")
        mgr.add("thread-1", [HumanMessage(content="hi")], user_id="u1")  # must not raise
        assert any("mem0" in r.message for r in caplog.records)

    def test_add_write_error_raise_policy(self) -> None:
        from deerflow.agents.memory.manager import MemoryManagerError

        mgr, fake = _manager({"failure_policy": {"write": "raise"}})
        fake.error = Mem0APIError("server down")
        with pytest.raises(MemoryManagerError):
            mgr.add("thread-1", [HumanMessage(content="hi")], user_id="u1")

    def test_async_add_offloads_sync_http_client(self) -> None:
        mgr, fake = _manager(mode="tool")
        event_loop_thread = threading.get_ident()
        called_from: list[int] = []
        original_add = fake.add_memories

        def recording_add(**kwargs: Any) -> dict[str, Any]:
            called_from.append(threading.get_ident())
            return original_add(**kwargs)

        fake.add_memories = recording_add
        asyncio.run(mgr.aadd("thread-1", [HumanMessage(content="hi")], user_id="u1"))

        assert called_from and called_from[0] != event_loop_thread


class TestMem0ManagerGetContext:
    def test_formats_dedupes_and_scopes(self) -> None:
        mgr, fake = _manager()
        fake.list_results = [
            {"id": "m1", "memory": "likes cricket"},
            {"id": "m1", "memory": "likes cricket"},  # dup by id
            {"id": "m2", "memory": ""},  # empty dropped
            {"id": "m3", "memory": "lives in Austin"},
        ]
        ctx = mgr.get_context("u1", agent_name="lead_agent", thread_id="t-1")
        assert ctx == "- likes cricket\n- lives in Austin"
        call = fake.list_calls[0]
        assert call["filters"] == {"AND": [{"user_id": "u1"}, {"agent_id": "lead_agent"}, {"run_id": "t-1"}]}
        assert call["max_items"] == 8  # default top_k

    def test_no_identity_returns_empty(self) -> None:
        mgr, fake = _manager()
        assert mgr.get_context(None) == ""
        assert fake.list_calls == []

    def test_read_error_fail_open_returns_empty(self) -> None:
        mgr, fake = _manager()
        fake.error = Mem0APIError("down")
        assert mgr.get_context("u1") == ""

    def test_read_error_fail_closed_raises(self) -> None:
        from deerflow.agents.memory.manager import MemoryManagerError

        mgr, fake = _manager({"failure_policy": {"read": "fail_closed"}})
        fake.error = Mem0APIError("down")
        with pytest.raises(MemoryManagerError):
            mgr.get_context("u1")

    def test_truncates_to_max_injection_chars(self) -> None:
        mgr, fake = _manager({"max_injection_chars": 20})
        fake.list_results = [{"id": f"m{i}", "memory": "x" * 30} for i in range(3)]
        ctx = mgr.get_context("u1")
        assert len(ctx) <= 20

    def test_truncates_on_entry_boundary(self) -> None:
        """Budget truncation must keep whole entries, never cut a memory
        mid-line and leave a dangling partial entry in the prompt."""
        mgr, fake = _manager({"max_injection_chars": 20})
        fake.list_results = [
            {"id": "m1", "memory": "a" * 10},  # "- aaaaaaaaaa" = 12 chars, fits
            {"id": "m2", "memory": "b" * 10},  # + "\n" + 12 = 25 > 20, must be dropped whole
        ]
        ctx = mgr.get_context("u1")
        assert ctx == "- " + "a" * 10

    def test_skips_oversized_entry_and_keeps_later_fitting_one(self) -> None:
        """An entry that does not fit whole is skipped; a shorter later entry
        may still fit within the remaining budget."""
        mgr, fake = _manager({"max_injection_chars": 20})
        fake.list_results = [
            {"id": "m1", "memory": "x" * 30},  # 32-char line, does not fit whole
            {"id": "m2", "memory": "short"},  # "- short" = 7 chars, fits
        ]
        ctx = mgr.get_context("u1")
        assert ctx == "- short"

    def test_oversized_entries_return_empty_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """When no memory fits the budget, keep the entry-boundary guarantee by
        returning empty context and logging a diagnosable warning."""
        mgr, fake = _manager({"max_injection_chars": 20})
        fake.list_results = [{"id": "m1", "memory": "x" * 30}]
        ctx = mgr.get_context("u1")
        assert ctx == ""
        assert any("max_injection_chars=20" in r.message and "shortest recalled memory" in r.message for r in caplog.records)

    def test_async_get_context_offloads_sync_http_client(self) -> None:
        mgr, fake = _manager()
        event_loop_thread = threading.get_ident()
        called_from: list[int] = []
        original_list = fake.list_memories

        def recording_list(**kwargs: Any) -> list[dict[str, Any]]:
            called_from.append(threading.get_ident())
            return original_list(**kwargs)

        fake.list_memories = recording_list
        asyncio.run(mgr.aget_context("u1"))

        assert called_from and called_from[0] != event_loop_thread


class TestMem0ManagerSearch:
    def test_maps_results_to_backend_neutral_shape(self) -> None:
        mgr, fake = _manager()
        fake.search_results = [
            {
                "id": "m1",
                "memory": "likes cricket",
                "score": 0.9,
                "categories": ["hobbies"],
                "created_at": "2026-01-15T10:30:00Z",
                "metadata": {"source": "chat"},
            }
        ]
        results = mgr.search("sports", top_k=5, user_id="u1")
        assert results == [
            {
                "id": "m1",
                "content": "likes cricket",
                "category": "hobbies",
                "confidence": 0.9,
                "createdAt": "2026-01-15T10:30:00Z",
                "source": "chat",
            }
        ]
        call = fake.search_calls[0]
        assert call["filters"] == {"user_id": "u1"}
        assert call["threshold"] == 0.1  # default score_threshold

    def test_category_filter_anded_in(self) -> None:
        mgr, fake = _manager()
        mgr.search("q", user_id="u1", agent_name="lead_agent", category="preference")
        assert fake.search_calls[0]["filters"] == {"AND": [{"user_id": "u1"}, {"agent_id": "lead_agent"}, {"categories": {"contains": "preference"}}]}

    def test_no_identity_returns_empty(self) -> None:
        mgr, _fake = _manager()
        assert mgr.search("q") == []

    def test_async_search_offloads_sync_http_client(self) -> None:
        mgr, fake = _manager(mode="tool")
        event_loop_thread = threading.get_ident()
        called_from: list[int] = []
        original_search = fake.search_memories

        def recording_search(**kwargs: Any) -> list[dict[str, Any]]:
            called_from.append(threading.get_ident())
            return original_search(**kwargs)

        fake.search_memories = recording_search
        asyncio.run(mgr.asearch("q", user_id="u1"))

        assert called_from and called_from[0] != event_loop_thread


class TestMem0ManagerManage:
    def test_get_memory_maps_full_bucket(self) -> None:
        mgr, fake = _manager()
        fake.list_results = [{"id": "m1", "memory": "likes cricket", "created_at": "2026-01-15T10:30:00Z"}]
        doc = mgr.get_memory(user_id="u1")
        assert doc["facts"][0]["id"] == "m1"
        assert doc["facts"][0]["content"] == "likes cricket"
        assert fake.list_calls[0].get("max_items") is None  # full listing

    def test_get_memory_no_identity_returns_empty_doc(self) -> None:
        mgr, _fake = _manager()
        assert mgr.get_memory() == {"facts": []}

    def test_clear_memory_deletes_bucket_and_returns_empty(self) -> None:
        mgr, fake = _manager()
        assert mgr.clear_memory(user_id="u1", agent_name="lead_agent") == {"facts": []}
        assert fake.deleted == [{"user_id": "u1", "agent_id": "lead_agent", "run_id": None}]

    def test_clear_memory_user_wide_when_agent_none(self) -> None:
        mgr, fake = _manager()
        mgr.clear_memory(user_id="u1")
        assert fake.deleted[0]["agent_id"] is None

    def test_delete_memory_returns_none(self) -> None:
        mgr, fake = _manager()
        assert mgr.delete_memory(user_id="u1") is None
        assert len(fake.deleted) == 1

    def test_clear_memory_no_identity_is_noop(self) -> None:
        mgr, fake = _manager()
        assert mgr.clear_memory() == {"facts": []}
        assert fake.deleted == []

    def test_delete_memory_no_identity_is_noop(self) -> None:
        mgr, fake = _manager()
        assert mgr.delete_memory() is None
        assert fake.deleted == []

    def test_clear_memory_empty_string_identity_is_noop(self) -> None:
        mgr, fake = _manager()
        assert mgr.clear_memory(user_id="", agent_name="") == {"facts": []}
        assert fake.deleted == []

    def test_export_delegates_to_get_memory(self) -> None:
        mgr, fake = _manager()
        fake.list_results = [{"id": "m1", "memory": "x"}]
        assert mgr.export_memory(user_id="u1")["facts"][0]["id"] == "m1"

    def test_tier3_defaults_raise_not_implemented(self) -> None:
        mgr, _fake = _manager()
        with pytest.raises(NotImplementedError):
            mgr.create_fact("x", user_id="u1")
        with pytest.raises(NotImplementedError):
            mgr.import_memory({"facts": []}, user_id="u1")


class TestMem0Discovery:
    def test_scan_backends_registers_mem0(self) -> None:
        import deerflow.agents.memory.manager as manager_module

        manager_module._backends_cache = None
        try:
            registry = manager_module._scan_backends()
        finally:
            manager_module._backends_cache = None
        assert registry["mem0"] is Mem0Manager

    def test_factory_resolves_mem0(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from deerflow.agents.memory.manager import get_memory_manager, reset_memory_manager
        from deerflow.config.memory_config import MemoryConfig, get_memory_config, set_memory_config

        monkeypatch.setenv("MEM0_API_KEY", "k")
        monkeypatch.setattr(Mem0Client, "ping", lambda self: None)

        original_config = get_memory_config()
        set_memory_config(MemoryConfig(manager_class="mem0"))
        reset_memory_manager()
        try:
            mgr = get_memory_manager()
            assert isinstance(mgr, Mem0Manager)
        finally:
            reset_memory_manager()
            set_memory_config(original_config)
