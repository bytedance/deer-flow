"""Tests for deerflow.mcp.auth build_auth_interceptor."""

import asyncio
from unittest.mock import AsyncMock, patch

from deerflow.mcp.auth import (
    HEADER_USER_ID,
    build_auth_interceptor,
)


class _Request:
    def __init__(self, *, headers=None, runtime=None):
        self.server_name = "funds-api"
        self.name = "list_funds"
        self.headers = headers or {}
        self.runtime = runtime

    def override(self, **kwargs):
        updated = _Request(headers=dict(self.headers), runtime=self.runtime)
        updated.server_name = self.server_name
        updated.name = self.name
        if "headers" in kwargs:
            updated.headers = kwargs["headers"]
        return updated


def _make_request(*, headers=None, runtime=None):
    return _Request(headers=headers, runtime=runtime)


async def _run_interceptor(*, config=None, user_id_from_ctxvar=None):
    handler = AsyncMock(side_effect=lambda req: req)
    interceptor = build_auth_interceptor()

    with (
        patch("langgraph.config.get_config", return_value=config or {}),
        patch(
            "deerflow.mcp.auth.get_effective_user_id",
            return_value=user_id_from_ctxvar or "default",
        ),
    ):
        request = _make_request()
        result = await interceptor(request, handler)

    handler.assert_awaited_once()
    return result, handler.await_args.args[0]


def test_injects_user_id_from_configurable_context():
    config = {"configurable": {"context": {"user_id": "alice"}}}
    result, forwarded = asyncio.run(_run_interceptor(config=config))

    assert forwarded.headers[HEADER_USER_ID] == "alice"
    assert result is forwarded


def test_falls_back_to_effective_user_id():
    config = {"configurable": {}}
    _, forwarded = asyncio.run(_run_interceptor(config=config, user_id_from_ctxvar="bob"))

    assert forwarded.headers[HEADER_USER_ID] == "bob"


def test_preserves_existing_headers():
    config = {"configurable": {"context": {"user_id": "alice"}}}
    handler = AsyncMock(side_effect=lambda req: req)
    interceptor = build_auth_interceptor()
    request = _make_request(headers={"Authorization": "Bearer x"})

    with patch("langgraph.config.get_config", return_value=config):
        asyncio.run(interceptor(request, handler))

    forwarded = handler.await_args.args[0]
    assert forwarded.headers["Authorization"] == "Bearer x"
    assert forwarded.headers[HEADER_USER_ID] == "alice"


def test_reads_user_id_from_configurable_context():
    handler = AsyncMock(side_effect=lambda req: req)
    interceptor = build_auth_interceptor()
    request = _make_request()
    config = {
        "context": {},
        "configurable": {
            "thread_id": "cfg-thread",
            "context": {
                "user_id": "cfg-user",
                "run_id": "cfg-run",
            },
        },
    }

    with (
        patch("langgraph.config.get_config", return_value=config),
        patch("deerflow.mcp.auth.get_effective_user_id", return_value="default"),
    ):
        asyncio.run(interceptor(request, handler))

    forwarded = handler.await_args.args[0]
    assert forwarded.headers[HEADER_USER_ID] == "cfg-user"
