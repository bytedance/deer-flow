"""Tests for the Honcho memory backend (config + manager)."""

from __future__ import annotations

import httpx
import pytest

from deerflow.agents.memory.backends.honcho.client import HonchoClient, HonchoRequestError
from deerflow.agents.memory.backends.honcho.config import HonchoConfig, sanitize_id


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


class TestSanitizeId:
    def test_passthrough_and_cleanup(self):
        assert sanitize_id("user_1-ok") == "user_1-ok"
        assert sanitize_id("weird id@example.com") == "weird-id-example-com"
        assert len(sanitize_id("x" * 200)) == 64
        assert sanitize_id("") == ""


def _client_with_handler(handler, **cfg_over):
    from deerflow.agents.memory.backends.honcho.config import HonchoConfig

    cfg = HonchoConfig.from_backend_config({"base_url": "http://honcho.test", **cfg_over})
    client = HonchoClient(cfg)
    headers = {"Content-Type": "application/json"}
    if cfg.api_key:
        headers["Authorization"] = f"Bearer {cfg.api_key}"
    client._http = httpx.Client(base_url=cfg.base_url, headers=headers, transport=httpx.MockTransport(handler))
    return client


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

    def test_api_key_header(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers.get("Authorization") == "Bearer sk-h"
            return httpx.Response(200, json={"id": "x"})

        c = _client_with_handler(handler, api_key="sk-h", allow_insecure_http=True)
        c.get_or_create_peer("ws1", "alice")
