"""A conversation URL is matched against the host the client addressed.

Gateway runs behind nginx and often behind a TLS proxy too. uvicorn only
applies ``X-Forwarded-Proto`` from ``FORWARDED_ALLOW_IPS`` (``127.0.0.1`` by
default), so with nginx in another container or pod the request URL stays
``http`` while the browser's link is ``https``. A local nginx resends its own
``$scheme``. These cases send the request through uvicorn's real
``ProxyHeadersMiddleware`` and the real ``prepare_conversation_reader``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from langgraph.store.memory import InMemoryStore
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.gateway.authz import AuthContext
from app.gateway.conversation_access import prepare_conversation_reader
from deerflow.config.app_config import AppConfig
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.events.store.memory import MemoryRunEventStore
from deerflow.runtime.runs.manager import EditReplayVisibility

pytestmark = pytest.mark.asyncio

_NGINX_CONTAINER = "172.18.0.5"
_CHAT = "/workspace/chats/source"


def _app() -> FastAPI:
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "tools": [{"name": "read_conversation", "group": "conversation", "use": "deerflow.tools.conversation:read_conversation"}],
        }
    )
    manager = AsyncMock()
    manager.list_edit_replay_visibility.return_value = EditReplayVisibility()
    run_context = SimpleNamespace(event_store=MemoryRunEventStore(), thread_store=MemoryThreadMetaStore(InMemoryStore()))
    app = FastAPI()

    @app.post("/api/threads/current/runs")
    async def create_run(request: Request, body: dict) -> dict:
        request.state.auth = AuthContext(SimpleNamespace(id="alice", system_role="user"), ["runs:read"])
        try:
            _, ids = prepare_conversation_reader(body["references"], request=request, user_id="alice", run_context=run_context, run_manager=manager, app_config=config)
        except HTTPException as exc:
            return {"status": exc.status_code}
        return {"status": 200, "ids": list(ids)}

    return app


async def _submit(reference: str, headers: dict[str, str], *, peer: str = _NGINX_CONTAINER, trusted: str = "127.0.0.1") -> dict:
    # ``trusted`` is uvicorn's FORWARDED_ALLOW_IPS; ``peer`` is the address nginx connects from.
    transport = httpx.ASGITransport(app=ProxyHeadersMiddleware(_app(), trusted_hosts=trusted), client=(peer, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway:8001") as client:
        response = await client.post("/api/threads/current/runs", json={"references": [reference]}, headers=headers)
    return response.json()


_TLS_EDGE = {"host": "deerflow.example", "x-forwarded-proto": "https", "x-forwarded-for": "203.0.113.9"}


@pytest.mark.parametrize(
    ("reference", "headers", "peer", "trusted"),
    [
        pytest.param(f"https://deerflow.example{_CHAT}", _TLS_EDGE, _NGINX_CONTAINER, "127.0.0.1", id="docker-nginx-untrusted-peer"),
        pytest.param(f"https://deerflow.example{_CHAT}", {**_TLS_EDGE, "x-forwarded-proto": "http"}, "127.0.0.1", "127.0.0.1", id="local-nginx-resends-http"),
        pytest.param(f"https://deerflow.example{_CHAT}", _TLS_EDGE, _NGINX_CONTAINER, _NGINX_CONTAINER, id="trusted-proxy"),
        pytest.param(f"https://deerflow.example{_CHAT}", {**_TLS_EDGE, "host": "gateway:8001", "x-forwarded-host": "deerflow.example"}, _NGINX_CONTAINER, "127.0.0.1", id="forwarded-host"),
        pytest.param(f"https://deerflow.example:443{_CHAT}", _TLS_EDGE, _NGINX_CONTAINER, "127.0.0.1", id="explicit-default-port"),
        pytest.param(f"https://DeerFlow.Example{_CHAT}", _TLS_EDGE, _NGINX_CONTAINER, "127.0.0.1", id="host-case"),
        pytest.param(f"http://localhost:2026{_CHAT}", {"host": "localhost:2026", "x-forwarded-proto": "http"}, "127.0.0.1", "127.0.0.1", id="plain-http-dev"),
        pytest.param(f"https://deerflow.example:8443{_CHAT}", {**_TLS_EDGE, "x-forwarded-port": "8443"}, _NGINX_CONTAINER, "127.0.0.1", id="forwarded-port"),
        pytest.param(f"http://[::1]:2026{_CHAT}", {"host": "[::1]:2026", "x-forwarded-proto": "http"}, "127.0.0.1", "127.0.0.1", id="ipv6-host"),
    ],
)
async def test_a_link_from_the_addressed_host_is_accepted(reference, headers, peer, trusted) -> None:
    assert await _submit(reference, headers, peer=peer, trusted=trusted) == {"status": 200, "ids": ["source"]}


@pytest.mark.parametrize(
    "reference",
    [
        pytest.param(f"https://other.example{_CHAT}", id="other-host"),
        pytest.param(f"https://deerflow.example:8443{_CHAT}", id="other-port"),
        pytest.param(f"https://alice@deerflow.example{_CHAT}", id="credentials"),
        pytest.param(f"ftp://deerflow.example{_CHAT}", id="other-scheme"),
        pytest.param(f"https://deerflow.example:notaport{_CHAT}", id="bad-port"),
        pytest.param(f"https://{_CHAT}", id="no-host"),
        pytest.param(f"https://deerflow.example{_CHAT}?tab=1", id="query"),
        pytest.param(f"https://deerflow.example{_CHAT}#tab", id="fragment"),
    ],
)
async def test_a_link_from_anywhere_else_is_still_rejected(reference) -> None:
    assert await _submit(reference, _TLS_EDGE) == {"status": 422}
