"""Tests for the Honcho memory backend (config + manager)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from deerflow.agents.memory.backends.honcho.client import HonchoClient, HonchoRequestError
from deerflow.agents.memory.backends.honcho.config import HonchoConfig, sanitize_id
from deerflow.agents.memory.backends.honcho.honcho_manager import HonchoMemoryManager, _stable_id
from deerflow.agents.memory.manager import MemoryManagerError


class TestHonchoConfig:
    def test_defaults(self):
        cfg = HonchoConfig.from_backend_config(None)
        assert cfg.base_url == "http://localhost:8000"
        assert cfg.api_key is None
        assert cfg.workspace_prefix == "deerflow-u-"
        assert cfg.workspace_overrides == {}
        assert cfg.user_peer_overrides == {}
        assert cfg.assistant_peer == "deerflow"
        assert cfg.message_char_limit == 8000
        assert cfg.max_injection_chars == 6000
        assert cfg.read_fail_closed is False

    def test_parses_knobs_and_ignores_unknown_keys(self):
        cfg = HonchoConfig.from_backend_config(
            {
                "base_url": "https://api.honcho.dev/",
                "api_key": "sk-test",
                "workspace_prefix": "df-",
                "workspace_overrides": {"user-1": "shared"},
                "user_peer_overrides": {"user-1": "alice"},
                "assistant_peer": "deer",
                "failure_policy": {"read": "fail_closed"},
                "storage_path": "/tmp/x",
                "unknown_key": True,
            }
        )
        assert cfg.base_url == "https://api.honcho.dev"  # trailing slash stripped
        assert cfg.workspace_overrides == {"user-1": "shared"}
        assert cfg.user_peer_overrides == {"user-1": "alice"}
        assert cfg.read_fail_closed is True
        assert cfg.storage_path == "/tmp/x"

    def test_http_with_api_key_requires_opt_in(self):
        with pytest.raises(ValueError, match="allow_insecure_http"):
            HonchoConfig.from_backend_config({"base_url": "http://internal:8000", "api_key": "sk-x"})
        cfg = HonchoConfig.from_backend_config({"base_url": "http://internal:8000", "api_key": "sk-x", "allow_insecure_http": True})
        assert cfg.api_key == "sk-x"

    def test_http_without_api_key_is_fine(self):
        cfg = HonchoConfig.from_backend_config({"base_url": "http://host.docker.internal:8000"})
        assert cfg.api_key is None

    def test_empty_override_values_rejected(self):
        """An override entry with an empty/null value is a config mistake: silently
        falling through to the default derivation (empty string is falsy) or
        stringifying YAML null into a workspace literally named "None" would both
        mask the operator's intent. Fail fast at parse time instead."""
        with pytest.raises(ValueError, match="workspace_overrides"):
            HonchoConfig.from_backend_config({"workspace_overrides": {"alice": ""}})
        with pytest.raises(ValueError, match="workspace_overrides"):
            HonchoConfig.from_backend_config({"workspace_overrides": {"alice": None}})
        with pytest.raises(ValueError, match="user_peer_overrides"):
            HonchoConfig.from_backend_config({"user_peer_overrides": {"bob": "  "}})


class TestSanitizeId:
    def test_passthrough_and_cleanup(self):
        assert sanitize_id("user_1-ok") == "user_1-ok"
        assert sanitize_id("weird id@example.com") == "weird-id-example-com"
        assert len(sanitize_id("x" * 200)) == 64
        assert sanitize_id("") == ""


def _client_with_handler(handler, **cfg_over):
    cfg = HonchoConfig.from_backend_config({"base_url": "http://honcho.test", **cfg_over})
    return HonchoClient(cfg, transport=httpx.MockTransport(handler))


class TestHonchoClient:
    def test_paths_and_payloads(self):
        seen: list[tuple[str, str, bytes]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.content))
            if request.url.path.endswith("/representation"):
                return httpx.Response(200, json={"representation": "knows things"})
            if request.url.path.endswith("/search"):
                return httpx.Response(200, json=[{"content": "hit", "peer_id": "p", "session_id": "s", "created_at": "t"}])
            return httpx.Response(200, json={"id": "x"})

        c = _client_with_handler(handler)
        c.get_or_create_peer("ws1", "alice")
        c.get_or_create_session("ws1", "df-t1")
        c.set_session_peers("ws1", "df-t1", ["alice", "deerflow"])
        c.add_messages("ws1", "df-t1", [{"peer_id": "alice", "content": "hi"}])
        assert c.working_representation("ws1", "alice", max_conclusions=10) == "knows things"
        assert c.search("ws1", "q", limit=5)[0]["content"] == "hit"

        paths = [p for _, p, _ in seen]
        assert paths == [
            "/v3/workspaces/ws1/peers",
            "/v3/workspaces/ws1/sessions",
            "/v3/workspaces/ws1/sessions/df-t1/peers",
            "/v3/workspaces/ws1/sessions/df-t1/messages",
            "/v3/workspaces/ws1/peers/alice/representation",
            "/v3/workspaces/ws1/search",
        ]
        assert b'"alice"' in seen[2][2] and b'"deerflow"' in seen[2][2]
        assert b'"messages"' in seen[3][2]

    def test_errors_wrap_as_honcho_request_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        c = _client_with_handler(handler)
        with pytest.raises(HonchoRequestError):
            c.get_or_create_peer("ws1", "alice")

    def test_non_json_200_response_wraps_as_honcho_request_error(self):
        """A 200 with a non-JSON body (e.g. a maintenance page from a proxy in
        front of Honcho) must not let a bare JSONDecodeError escape -- it has
        to surface through the same HonchoRequestError contract as any other
        transport failure so callers have exactly one exception type to
        handle."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        c = _client_with_handler(handler)
        with pytest.raises(HonchoRequestError):
            c.get_or_create_peer("ws1", "alice")

    def test_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("Authorization") == "Bearer sk-h"
            return httpx.Response(200, json={"id": "x"})

        c = _client_with_handler(handler, api_key="sk-h", allow_insecure_http=True)
        c.get_or_create_peer("ws1", "alice")


class _FakeClient:
    """Records calls; canned returns. Replaces the real HonchoClient in tests."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.representation_text = "ajayr likes concise answers"
        self.raise_on: str | None = None
        # Which exception type _maybe_raise raises; default matches the real
        # HonchoClient's contract. Tests override this to a non-HonchoRequestError
        # (e.g. RuntimeError) to prove the manager's boundary excepts are broad,
        # not narrowly typed to the client's own exception class.
        self.raise_exc_cls: type[BaseException] = HonchoRequestError
        self.closed = False

    def _maybe_raise(self, name):
        if self.raise_on == name:
            raise self.raise_exc_cls(name)

    def get_or_create_peer(self, ws, pid):
        self._maybe_raise("peer")
        self.calls.append(("peer", (ws, pid)))

    def get_or_create_session(self, ws, sid):
        self._maybe_raise("session")
        self.calls.append(("session", (ws, sid)))

    def set_session_peers(self, ws, sid, pids):
        self._maybe_raise("peers")
        self.calls.append(("set_peers", (ws, sid, tuple(pids))))

    def add_messages(self, ws, sid, msgs):
        self._maybe_raise("messages")
        self.calls.append(("messages", (ws, sid, tuple((m["peer_id"], m["content"]) for m in msgs))))

    def working_representation(self, ws, pid, *, max_conclusions=25):
        self._maybe_raise("representation")
        self.calls.append(("rep", (ws, pid)))
        return self.representation_text

    def search(self, ws, query, *, limit=5):
        self._maybe_raise("search")
        self.calls.append(("search", (ws, query, limit)))
        return [{"content": "found", "peer_id": "deerflow", "session_id": "df-t", "created_at": "2026-01-01"}]

    def close(self):
        self.closed = True


def _manager(**backend_config):
    mgr = HonchoMemoryManager.from_config({"base_url": "http://honcho.test", **backend_config})
    fake = _FakeClient()
    mgr._client = fake
    return mgr, fake


def _msg(msg_type, content):
    return SimpleNamespace(type=msg_type, content=content)


class TestHonchoClientTransport:
    def test_constructor_accepts_transport_for_tests(self):
        """Tests inject httpx.MockTransport through the constructor (Mem0Client
        precedent) instead of rebuilding and overwriting client._http."""
        seen: list[str] = []

        def handler(request):
            seen.append(request.url.path)
            return httpx.Response(200)

        cfg = HonchoConfig.from_backend_config({"base_url": "http://honcho.test"})
        client = HonchoClient(cfg, transport=httpx.MockTransport(handler))
        client.get_or_create_peer("w1", "p1")
        assert seen == ["/v3/workspaces/w1/peers"]


class TestHonchoManagerWrite:
    def test_add_maps_messages_to_peers(self):
        mgr, fake = _manager(workspace_overrides={"u1": "shared"}, user_peer_overrides={"u1": "alice"})
        mgr.add("t-1", [_msg("human", "please check the deploy"), _msg("ai", "deploy is green"), _msg("tool", "ignored")], user_id="u1")
        # Session ids share the user-id path's collision-resistant derivation;
        # computed, not hardcoded (see test_add_prefix_workspace_for_unmapped_user).
        sid = f"df-{_stable_id('t-1')}"
        assert ("messages", ("shared", sid, (("alice", "please check the deploy"), ("deerflow", "deploy is green")))) in fake.calls
        assert ("set_peers", ("shared", sid, ("alice", "deerflow"))) in fake.calls

    def test_add_without_user_is_noop(self):
        mgr, fake = _manager()
        mgr.add("t-1", [_msg("human", "hello")], user_id=None)
        assert fake.calls == []

    def test_add_with_empty_string_user_is_noop(self):
        mgr, fake = _manager()
        mgr.add("t-1", [_msg("human", "hello")], user_id="")
        assert fake.calls == []

    def test_add_prefix_workspace_for_unmapped_user(self):
        mgr, fake = _manager()
        mgr.add("t-2", [_msg("human", "x")], user_id="bob@example.com")
        # Computed via the same _stable_id formula the manager uses, not
        # hardcoded, so this test doesn't silently drift from the real
        # collision-resistant derivation (see TestHonchoIdentityDerivation).
        expected_peer = _stable_id("bob@example.com")
        assert fake.calls[0] == ("peer", (f"deerflow-u-{expected_peer}", expected_peer))

    def test_add_swallows_backend_errors(self):
        mgr, fake = _manager()
        fake.raise_on = "messages"
        mgr.add("t-3", [_msg("human", "x")], user_id="u1")  # must not raise

    def test_add_swallows_non_honcho_exceptions(self):
        """The boundary except is broad (except Exception), not narrowly typed
        to HonchoRequestError -- any client failure (e.g. a bug surfacing as a
        bare RuntimeError, or the non-JSON-response case in TestHonchoClient)
        must not escape add() and crash MemoryMiddleware.after_agent."""
        mgr, fake = _manager()
        fake.raise_on = "messages"
        fake.raise_exc_cls = RuntimeError
        mgr.add("t-6", [_msg("human", "x")], user_id="u1")  # must not raise

    def test_add_truncates_long_content(self):
        mgr, fake = _manager(message_char_limit=10)
        mgr.add("t-4", [_msg("human", "0123456789ABCDEF")], user_id="u1")
        sent = [c for c in fake.calls if c[0] == "messages"][0][1][2][0][1]
        assert len(sent) == 10

    def test_add_normalizes_list_content(self):
        mgr, fake = _manager()
        mgr.add("t-5", [_msg("human", [{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}])], user_id="u1")
        sent = [c for c in fake.calls if c[0] == "messages"][0][1][2][0][1]
        assert "part1" in sent and "part2" in sent

    def test_session_ids_resist_sanitize_collisions(self):
        """Same lossy-sanitization hazard as user ids, one tier down: thread ids
        "t.1" and "t-1" both sanitize to "t-1", so bare sanitize_id would merge
        two threads' histories into one Honcho session. Session ids must use the
        same collision-resistant _stable_id derivation as the user-id path."""
        mgr, fake = _manager()
        mgr.add("t.1", [_msg("human", "x")], user_id="u1")
        mgr.add("t-1", [_msg("human", "y")], user_id="u1")
        session_ids = {c[1][1] for c in fake.calls if c[0] == "session"}
        assert len(session_ids) == 2


class TestHonchoManagerRead:
    def test_get_context_returns_representation(self):
        mgr, fake = _manager(workspace_overrides={"u1": "shared"})
        assert "concise answers" in mgr.get_context("u1")

    def test_get_context_without_user_is_empty(self):
        mgr, _ = _manager()
        assert mgr.get_context(None) == ""

    def test_get_context_with_empty_string_user_is_empty(self):
        mgr, fake = _manager()
        assert mgr.get_context("") == ""
        assert fake.calls == []

    def test_get_context_truncates(self):
        mgr, fake = _manager(max_injection_chars=10)
        fake.representation_text = "y" * 100
        assert len(mgr.get_context("u1")) <= 10

    def test_get_context_fail_open_by_default(self):
        mgr, fake = _manager()
        fake.raise_on = "representation"
        assert mgr.get_context("u1") == ""

    def test_get_context_fail_closed_raises_contract_error(self):
        mgr, fake = _manager(failure_policy={"read": "fail_closed"})
        fake.raise_on = "representation"
        with pytest.raises(MemoryManagerError):
            mgr.get_context("u1")

    def test_get_context_fail_open_swallows_non_honcho_exceptions(self):
        mgr, fake = _manager()
        fake.raise_on = "representation"
        fake.raise_exc_cls = RuntimeError
        assert mgr.get_context("u1") == ""

    def test_get_context_fail_closed_wraps_non_honcho_exceptions(self):
        mgr, fake = _manager(failure_policy={"read": "fail_closed"})
        fake.raise_on = "representation"
        fake.raise_exc_cls = RuntimeError
        with pytest.raises(MemoryManagerError):
            mgr.get_context("u1")

    def test_search_maps_results(self):
        mgr, _ = _manager()
        results = mgr.search("deploy", top_k=3, user_id="u1")
        assert results[0]["content"] == "found"

    def test_search_without_user_is_empty(self):
        mgr, _ = _manager()
        assert mgr.search("q", user_id=None) == []

    def test_supports_search_flag_matches_override(self):
        mgr, _ = _manager()
        assert type(mgr).supports_search is True

    def test_search_fail_open_by_default(self):
        mgr, fake = _manager()
        fake.raise_on = "search"
        assert mgr.search("q", user_id="u1") == []

    def test_search_fail_closed_raises_contract_error(self):
        """search() is a recall op (the tool-mode memory_search path): it must
        honor failure_policy.read like get_context() does, not silently return
        [] and mask an outage from the model and the operator."""
        mgr, fake = _manager(failure_policy={"read": "fail_closed"})
        fake.raise_on = "search"
        with pytest.raises(MemoryManagerError):
            mgr.search("q", user_id="u1")

    def test_search_fail_closed_wraps_non_honcho_exceptions(self):
        mgr, fake = _manager(failure_policy={"read": "fail_closed"})
        fake.raise_on = "search"
        fake.raise_exc_cls = RuntimeError
        with pytest.raises(MemoryManagerError):
            mgr.search("q", user_id="u1")

    def test_get_memory_minimal_shape(self):
        mgr, _ = _manager()
        doc = mgr.get_memory(user_id="u1")
        assert doc["facts"] == []
        assert doc["user"]["workContext"]["summary"]
        assert doc["lastUpdated"]

    def test_get_memory_without_user_is_empty_with_no_calls(self):
        mgr, fake = _manager()
        doc = mgr.get_memory(user_id=None)
        assert doc["facts"] == []
        assert doc["user"] == {}
        assert doc["history"] == {}
        assert doc["lastUpdated"]
        assert fake.calls == []

    def test_get_memory_fail_open_by_default(self):
        mgr, fake = _manager()
        fake.raise_on = "representation"
        doc = mgr.get_memory(user_id="u1")
        assert doc["facts"] == []
        assert doc["user"] == {}

    def test_get_memory_fail_closed_raises_contract_error(self):
        """get_memory() backs the /memory gateway endpoint — a recall op, so it
        follows failure_policy.read like get_context() and search()."""
        mgr, fake = _manager(failure_policy={"read": "fail_closed"})
        fake.raise_on = "representation"
        with pytest.raises(MemoryManagerError):
            mgr.get_memory(user_id="u1")


class TestHonchoManagerAsync:
    def test_async_entrypoints_delegate(self):
        mgr, fake = _manager()

        async def run():
            await mgr.aadd("t-1", [_msg("human", "x")], user_id="u1")
            ctx = await mgr.aget_context("u1")
            hits = await mgr.asearch("q", user_id="u1")
            return ctx, hits

        ctx, hits = asyncio.run(run())
        assert "concise" in ctx and hits


class TestHonchoManagerLifecycle:
    def test_shutdown_flush_true(self):
        mgr, _ = _manager()
        assert mgr.shutdown_flush(1.0) is True

    def test_tool_mode_accepted(self):
        mgr = HonchoMemoryManager.from_config({"base_url": "http://honcho.test"}, mode="tool")
        assert mgr.mode == "tool"

    def test_requires_passive_writes_in_tool_mode(self):
        """Honcho's only write path is passive add(); fact CRUD is intentionally
        unsupported, so tool mode must keep MemoryMiddleware writes flowing to
        Honcho's deriver alongside model-directed search(). Mirrors mem0's
        identical ClassVar (mem0_manager.py)."""
        assert HonchoMemoryManager.requires_passive_writes_in_tool_mode is True

    def test_close_releases_http_client(self):
        """close() is the gateway shutdown hook (manager.py base default is a
        no-op); Honcho must override it to release the underlying HTTP client,
        mirroring mem0_manager.py's identical close()."""
        mgr, fake = _manager()
        mgr.close()
        assert fake.closed is True


class TestHonchoIdentityDerivation:
    """Pins the collision-resistant default (non-override) identity derivation.

    ``sanitize_id`` alone is lossy: distinct raw ids can sanitize to the same
    string, which would merge two different users' memory into one Honcho
    workspace/peer if used bare. ``_stable_id`` (workspace/peer default path)
    must keep such inputs apart.
    """

    def test_default_workspace_and_peer_resist_sanitize_collisions(self):
        mgr, _ = _manager()
        raw_a = "user.name@example.com"
        raw_b = "user-name@example.com"
        # Precondition: these two distinct raw ids really do collide under
        # plain sanitize_id -- otherwise this test would not exercise the bug
        # the collision-resistant derivation fixes.
        assert sanitize_id(raw_a) == sanitize_id(raw_b)

        ws_a, ws_b = mgr._workspace(raw_a), mgr._workspace(raw_b)
        peer_a, peer_b = mgr._user_peer(raw_a), mgr._user_peer(raw_b)
        assert ws_a != ws_b
        assert peer_a != peer_b

    def test_user_peer_never_empty_for_degenerate_raw_id(self):
        mgr, _ = _manager()
        # "!!!" sanitizes to "" (every character stripped); the default
        # derivation must still produce a non-empty, usable peer/workspace id.
        assert sanitize_id("!!!") == ""
        peer = mgr._user_peer("!!!")
        assert peer != ""
        ws = mgr._workspace("!!!")
        assert ws is not None
        assert ws != mgr._config.workspace_prefix


class TestFactoryDiscovery:
    def test_manager_class_resolves(self):
        from deerflow.agents.memory.backends.honcho import MANAGER_CLASS

        assert MANAGER_CLASS is HonchoMemoryManager
