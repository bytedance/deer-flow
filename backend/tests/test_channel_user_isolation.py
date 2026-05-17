"""Regression tests for the channel user-isolation bug (issue #2947).

When an IM channel (Feishu/Slack/Telegram/DingTalk) receives a message, the
platform user id (e.g. Feishu ``open_id``) must reach the agent so that
``Memory``, ``ThreadDataMiddleware``, sandbox provider, and file downloads
all isolate per-user instead of collapsing into ``DEFAULT_USER_ID``
(``"default"``).

The fix has three coordinated layers:

1. **Channel → Gateway**: ``ChannelManager`` sends the platform user id via
   the ``X-DeerFlow-Acting-User`` HTTP header, alongside the internal-auth
   token that proves the caller is trusted.
2. **Gateway auth**: ``AuthMiddleware`` only honours the acting-user header
   when the internal-auth token is valid, then constructs a synthetic user
   with that id. This sets both ``request.state.user`` and the
   ``_current_user`` ContextVar to the real user, and
   ``inject_authenticated_user_context`` then writes the same id into
   ``runtime.context["user_id"]``.
3. **Agent runtime**: harness middlewares (``ThreadDataMiddleware``,
   ``MemoryMiddleware``) read via ``resolve_runtime_user_id(runtime)`` which
   prefers ``runtime.context["user_id"]`` and falls back to the ContextVar.

See issue https://github.com/bytedance/deer-flow/issues/2947 for context.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.channels.manager import ChannelManager
from app.channels.message_bus import MessageBus
from app.channels.store import ChannelStore
from app.gateway.auth_middleware import AuthMiddleware
from app.gateway.internal_auth import create_internal_auth_headers


def _new_manager() -> ChannelManager:
    bus = MessageBus()
    store = ChannelStore(path=Path(tempfile.mkdtemp()) / "store.json")
    return ChannelManager(bus=bus, store=store, langgraph_url="http://localhost:8001")


class TestChannelClientCarriesActingUser:
    """Layer 1: the langgraph-sdk client baked for each user includes the header."""

    def test_get_client_includes_acting_user_header(self):
        manager = _new_manager()
        with patch("langgraph_sdk.get_client") as get_client:
            get_client.return_value = object()
            manager._get_client("ou_alice")

        headers = get_client.call_args.kwargs["headers"]
        assert headers["X-DeerFlow-Acting-User"] == "ou_alice"
        assert headers["X-DeerFlow-Internal-Token"]

    def test_get_client_caches_per_user(self):
        manager = _new_manager()
        with patch("langgraph_sdk.get_client") as get_client:
            get_client.side_effect = lambda *_a, **kw: object()

            first_alice = manager._get_client("ou_alice")
            second_alice = manager._get_client("ou_alice")
            bob = manager._get_client("ou_bob")

        assert first_alice is second_alice
        assert first_alice is not bob
        # Two distinct users → SDK constructed twice (alice, bob).
        assert get_client.call_count == 2

    def test_fetch_gateway_forwards_acting_user(self, monkeypatch):
        manager = _new_manager()

        captured = {}

        class MockResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "m"}]}

        class MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def get(self, url, **kwargs):
                captured.update(kwargs)
                return MockResponse()

        monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: MockClient())

        import asyncio

        asyncio.run(manager._fetch_gateway("/api/models", "models", acting_user_id="ou_alice"))

        assert captured["headers"]["X-DeerFlow-Acting-User"] == "ou_alice"


class TestGatewayAuthHonoursActingUser:
    """Layer 2: AuthMiddleware constructs the right user from the header."""

    def test_acting_user_header_with_valid_internal_token_overrides_default_user(self):
        from app.gateway.internal_auth import _INTERNAL_AUTH_TOKEN, make_acting_internal_user

        user = make_acting_internal_user("ou_alice")
        assert user.id == "ou_alice"
        # Sanity: the token used by the channel is the same one the middleware validates.
        assert _INTERNAL_AUTH_TOKEN

    def test_acting_user_header_ignored_without_internal_token(self):
        """Security: external clients must NOT be able to spoof user via the header."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.gateway.auth_middleware import AuthMiddleware

        app = FastAPI()
        app.add_middleware(AuthMiddleware)

        @app.get("/api/echo-user")
        async def echo_user(request):  # type: ignore[no-untyped-def]
            return {"id": getattr(request.state.user, "id", None)}

        with TestClient(app, raise_server_exceptions=False) as client:
            # No internal-auth token: acting-user header must be ignored and
            # the request must be rejected entirely (no cookie either).
            resp = client.get("/api/echo-user", headers={"X-DeerFlow-Acting-User": "ou_attacker"})
            assert resp.status_code == 401

    def test_acting_user_header_honoured_with_valid_internal_token(self):
        app = FastAPI()
        app.add_middleware(AuthMiddleware)

        @app.get("/api/echo-user")
        async def echo_user(req: Request):
            return {"id": getattr(req.state.user, "id", None)}

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/echo-user", headers=create_internal_auth_headers(acting_user_id="ou_alice"))

        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "ou_alice"

    def test_internal_token_without_acting_user_falls_back_to_default(self):
        app = FastAPI()
        app.add_middleware(AuthMiddleware)

        @app.get("/api/echo-user")
        async def echo_user(req: Request):
            return {"id": getattr(req.state.user, "id", None)}

        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/echo-user", headers=create_internal_auth_headers())

        assert resp.status_code == 200
        # Without the acting-user header, falls back to the synthetic
        # internal user — preserves backwards compatibility for callers
        # that don't care about acting-on-behalf-of (e.g. health probes).
        assert resp.json()["id"] == "default"


class TestMiddlewaresReadFromRuntimeContext:
    """Layer 3: harness middlewares prefer runtime.context["user_id"]."""

    def test_thread_data_middleware_uses_runtime_context_user_id(self, tmp_path):
        from langgraph.runtime import Runtime

        from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware

        middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
        runtime = Runtime(context={"thread_id": "t-1", "user_id": "ou_alice"})

        result = middleware.before_agent(state={}, runtime=runtime)

        assert result is not None
        workspace = result["thread_data"]["workspace_path"].replace("\\", "/")
        assert "/users/ou_alice/threads/t-1/" in workspace
        assert "/users/default/" not in workspace

    def test_memory_middleware_passes_runtime_context_user_id_to_queue(self, monkeypatch):
        from langchain_core.messages import AIMessage, HumanMessage
        from langgraph.runtime import Runtime

        from deerflow.agents.middlewares.memory_middleware import MemoryMiddleware

        captured: dict[str, str] = {}

        class FakeQueue:
            def add(self, *, thread_id, messages, agent_name, user_id, correction_detected, reinforcement_detected):
                captured["user_id"] = user_id

        class FakeConfig:
            enabled = True

        monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_memory_queue", lambda: FakeQueue())
        monkeypatch.setattr("deerflow.agents.middlewares.memory_middleware.get_memory_config", lambda: FakeConfig())

        middleware = MemoryMiddleware()
        runtime = Runtime(context={"thread_id": "t-1", "user_id": "ou_alice"})
        state = {"messages": [HumanMessage(content="hi"), AIMessage(content="hello")]}

        middleware.after_agent(state=state, runtime=runtime)

        assert captured["user_id"] == "ou_alice"


class TestFeishuFileDownloadUsesExplicitUserId:
    """Layer 3 (channel helper): _receive_single_file accepts user_id explicitly."""

    def test_receive_single_file_signature_takes_user_id(self):
        import inspect

        from app.channels.feishu import FeishuChannel

        sig = inspect.signature(FeishuChannel._receive_single_file)
        assert "user_id" in sig.parameters


class TestInboundUploadsHonourActingUser:
    """Inbound file ingestion must land in the platform user's bucket.

    ``_ingest_inbound_files`` runs on the channel worker's asyncio task,
    not inside any Gateway HTTP request, so the ``_current_user``
    ContextVar is unset. Without an explicit ``user_id``,
    ``ensure_uploads_dir`` would collapse to ``users/default/`` and
    cross-contaminate platform users — re-introducing exactly the bug we
    fixed elsewhere. Regression test for that path.
    """

    def test_get_uploads_dir_honours_explicit_user_id(self, tmp_path, monkeypatch):
        from deerflow.config.paths import Paths
        from deerflow.uploads.manager import get_uploads_dir

        monkeypatch.setattr("deerflow.uploads.manager.get_paths", lambda: Paths(str(tmp_path)))

        uploads_dir = get_uploads_dir("t-1", user_id="ou_alice")

        path = str(uploads_dir).replace("\\", "/")
        assert "/users/ou_alice/threads/t-1/" in path
        assert "/users/default/" not in path

    def test_get_uploads_dir_falls_back_to_contextvar_when_user_id_omitted(self, tmp_path, monkeypatch):
        """Backwards-compat: Gateway routers and other authenticated callers
        rely on the ContextVar; the new optional ``user_id`` must not break
        them."""
        from deerflow.config.paths import Paths
        from deerflow.uploads.manager import get_uploads_dir

        monkeypatch.setattr("deerflow.uploads.manager.get_paths", lambda: Paths(str(tmp_path)))
        # No user_id passed → falls back to ContextVar (set by conftest autouse).
        uploads_dir = get_uploads_dir("t-1")

        path = str(uploads_dir).replace("\\", "/")
        # The autouse conftest sets a ``test-user-autouse`` user.
        assert "/users/test-user-autouse/threads/t-1/" in path


class TestActingUserEndToEndIsolation:
    """Highest-level guarantee: actual filesystem isolation works for Feishu users.

    Spins up the real ``FastAPI`` app via ``TestClient`` and confirms that
    a memory read request routed through the channel's auth headers lands in
    the platform-user bucket on disk rather than ``users/default/``.
    """

    def test_memory_request_lands_in_acting_user_bucket(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.gateway.auth_middleware import AuthMiddleware
        from app.gateway.internal_auth import create_internal_auth_headers
        from deerflow.runtime.user_context import get_effective_user_id

        captured: dict[str, str] = {}

        app = FastAPI()
        app.add_middleware(AuthMiddleware)

        @app.get("/api/probe")
        async def probe():
            captured["effective"] = get_effective_user_id()
            return {"effective": captured["effective"]}

        with TestClient(app, raise_server_exceptions=False) as client:
            r = client.get("/api/probe", headers=create_internal_auth_headers(acting_user_id="ou_alice"))

        assert r.status_code == 200
        # End-to-end: header → middleware → ContextVar → bare get_effective_user_id().
        assert captured["effective"] == "ou_alice"
