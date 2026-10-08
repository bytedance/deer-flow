"""Tests for MCP OAuth support."""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from deerflow.config.extensions_config import ExtensionsConfig, McpOAuthConfig
from deerflow.mcp.oauth import OAuthTokenManager, build_oauth_tool_interceptor, get_initial_oauth_headers


class _MockResponse:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockAsyncClient:
    def __init__(self, payload: dict[str, Any], post_calls: list[dict[str, Any]], **kwargs):
        self._payload = payload
        self._post_calls = post_calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, data: dict[str, Any]):
        self._post_calls.append({"url": url, "data": data})
        return _MockResponse(self._payload)


def test_oauth_token_manager_fetches_and_caches_token(monkeypatch):
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "token-123",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)

    first = asyncio.run(manager.get_authorization_header("secure-http"))
    second = asyncio.run(manager.get_authorization_header("secure-http"))

    assert first == "Bearer token-123"
    assert second == "Bearer token-123"
    assert len(post_calls) == 1
    assert post_calls[0]["url"] == "https://auth.example.com/oauth/token"
    assert post_calls[0]["data"]["grant_type"] == "client_credentials"


@pytest.fixture
def oauth_now(monkeypatch):
    now = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=UTC)

    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz):
            return now

    monkeypatch.setattr("deerflow.mcp.oauth.datetime", _FixedDatetime)
    return now


@pytest.mark.parametrize(
    "expires_in",
    [
        float("inf"),
        float("-inf"),
        float("nan"),
        1e30,
        10**30,
        pytest.param(86_400_000_000_000, id="rounded-timedelta-limit"),
        pytest.param(10**12, id="datetime-overflow"),
        "not-a-number",
    ],
)
def test_unusable_expires_in_falls_back_to_the_default_lifetime(monkeypatch, oauth_now, expires_in):
    """A malformed ``expires_in`` must not abort the token fetch.

    Cover conversion, ``timedelta`` construction and ``datetime`` addition:
    each can reject a lifetime that the token endpoint returns.
    """
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "token-123",
                "token_type": "Bearer",
                "expires_in": expires_in,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )
    manager = OAuthTokenManager.from_extensions_config(config)

    header = asyncio.run(manager.get_authorization_header("secure-http"))

    assert header == "Bearer token-123"
    token = manager._states["secure-http"].token
    assert token is not None
    assert token.expires_at == oauth_now + timedelta(hours=1)


@pytest.mark.parametrize("offset", [-1, 0, 1], ids=["below-limit", "at-limit", "above-limit"])
def test_expires_in_at_datetime_limit(monkeypatch, oauth_now, offset):
    # Integer division preserves the last whole second that can be added,
    # without the rounding in timedelta.total_seconds().
    ceiling = (datetime.max.replace(tzinfo=UTC) - oauth_now) // timedelta(seconds=1)
    expires_in = ceiling + offset
    _token_endpoint_returns(monkeypatch, {"access_token": "token-123", "expires_in": expires_in})
    manager = OAuthTokenManager.from_extensions_config(_oauth_server_config())

    header = asyncio.run(manager.get_authorization_header("secure-http"))

    assert header == "Bearer token-123"
    token = manager._states["secure-http"].token
    assert token is not None
    expected_lifetime = 3600 if offset > 0 else expires_in
    assert token.expires_at == oauth_now + timedelta(seconds=expected_lifetime)


def test_oauth_extra_token_params_cannot_override_grant_type(monkeypatch):
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "token-123",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                        # A careless copy-paste from another OAuth config.
                        "extra_token_params": {
                            "grant_type": "password",
                            "resource": "https://api.example.com",
                        },
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)

    asyncio.run(manager.get_authorization_header("secure-http"))

    # The reserved grant_type must win over the operator-supplied param so
    # the value sent to the token endpoint matches the branch logic that
    # picked client_credentials below. Other extension params still pass
    # through unchanged.
    assert post_calls[0]["data"]["grant_type"] == "client_credentials"
    assert post_calls[0]["data"]["resource"] == "https://api.example.com"


def test_build_oauth_interceptor_injects_authorization_header(monkeypatch):
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "token-abc",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-sse": {
                    "enabled": True,
                    "type": "sse",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )

    interceptor = build_oauth_tool_interceptor(config)
    assert interceptor is not None

    class _Request:
        def __init__(self):
            self.server_name = "secure-sse"
            self.headers = {"X-Test": "1"}

        def override(self, **kwargs):
            updated = _Request()
            updated.server_name = self.server_name
            updated.headers = kwargs.get("headers")
            return updated

    captured: dict[str, Any] = {}

    async def _handler(request):
        captured["headers"] = request.headers
        return "ok"

    result = asyncio.run(interceptor(_Request(), _handler))

    assert result == "ok"
    assert captured["headers"]["Authorization"] == "Bearer token-abc"
    assert captured["headers"]["X-Test"] == "1"


def test_get_initial_oauth_headers(monkeypatch):
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "token-initial",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                },
                "no-oauth": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://example.com/mcp",
                },
            }
        }
    )

    headers = asyncio.run(get_initial_oauth_headers(config))

    assert headers == {"secure-http": "Bearer token-initial"}
    assert len(post_calls) == 1


def test_get_initial_oauth_headers_one_failing_server_does_not_drop_others(monkeypatch):
    """A single OAuth server whose token endpoint fails must not drop headers
    (and therefore tools) from healthy servers."""

    class _FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, data: dict[str, Any]):
            raise RuntimeError("token endpoint unreachable")

    class _OkClient:
        def __init__(self, post_calls: list[dict[str, Any]], **kwargs):
            self._post_calls = post_calls

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, data: dict[str, Any]):
            self._post_calls.append({"url": url, "data": data})
            return _MockResponse(
                payload={
                    "access_token": "token-ok",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )

    ok_post_calls: list[dict[str, Any]] = []

    def _client_factory(**kwargs):
        # The first call is for the failing server, second for the healthy one,
        # because OAuthTokenManager iterates the configured servers in dict order
        # ('broken-http' < 'secure-http').
        if not hasattr(_client_factory, "_count"):
            _client_factory._count = 0  # type: ignore[attr-defined]
        _client_factory._count += 1  # type: ignore[attr-defined]
        if _client_factory._count == 1:  # type: ignore[attr-defined]
            return _FailingClient()
        return _OkClient(post_calls=ok_post_calls)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "broken-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://broken.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.broken.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                },
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id-2",
                        "client_secret": "client-secret-2",
                    },
                },
            }
        }
    )

    headers = asyncio.run(get_initial_oauth_headers(config))

    # The healthy server's header must still be present.
    assert headers == {"secure-http": "Bearer token-ok"}
    assert len(ok_post_calls) == 1


def test_oauth_refresh_token_rotation_persists_rotated_value(monkeypatch):
    """When a provider rotates the refresh_token, _fetch_token must capture
    the new value so the next refresh uses it instead of the stale original."""
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "at-1",
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": "rt-rotated-1",
            },
            post_calls=post_calls,
            **kwargs,
        )

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "rotating-srv": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "refresh_token",
                        "refresh_token": "rt-original-seed",
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)

    # Force the _is_expiring check to always return True so we hit _fetch_token.
    monkeypatch.setattr(OAuthTokenManager, "_is_expiring", lambda self, token, oauth: True)

    first = asyncio.run(manager.get_authorization_header("rotating-srv"))
    assert first == "Bearer at-1"
    assert len(post_calls) == 1
    # First call posted the original seed token.
    assert post_calls[0]["data"]["refresh_token"] == "rt-original-seed"

    # On the second call, the rotated refresh_token from the first response
    # must be used.
    second = asyncio.run(manager.get_authorization_header("rotating-srv"))
    assert second == "Bearer at-1"
    assert len(post_calls) == 2
    assert post_calls[1]["data"]["refresh_token"] == "rt-rotated-1"


def test_refresh_waiters_leave_default_executor_available(monkeypatch):
    """Waiting for one refresh must not starve DNS or unrelated executor work."""
    post_calls: list[dict[str, Any]] = []

    async def scenario():
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        refreshing = asyncio.Event()
        release_refresh = asyncio.Event()

        class HeldClient(_MockAsyncClient):
            async def post(self, url, data):
                refreshing.set()
                await release_refresh.wait()
                return await super().post(url, data)

        monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: HeldClient(payload={"access_token": "shared-token", "expires_in": 3600}, post_calls=post_calls, **kwargs))
        manager = OAuthTokenManager({"secure-http": McpOAuthConfig(enabled=True, token_url="https://auth.example.com/token", client_id="client-id", client_secret="client-secret")})
        callers = [asyncio.create_task(manager.get_authorization_header("secure-http"))]
        try:
            await asyncio.wait_for(refreshing.wait(), timeout=5)
            callers.extend(asyncio.create_task(manager.get_authorization_header("secure-http")) for _ in range(2))
            # Let both callers reach their wait. The loop marker is queued after
            # their tasks, so any acquisition jobs they schedule precede the probe.
            waiting = loop.create_future()
            loop.call_soon(waiting.set_result, None)
            await waiting
            assert await asyncio.wait_for(asyncio.to_thread(lambda: "executor-ready"), timeout=5) == "executor-ready"
            release_refresh.set()
            assert await asyncio.wait_for(asyncio.gather(*callers), timeout=5) == ["Bearer shared-token"] * 3
        finally:
            release_refresh.set()
            for caller in callers:
                caller.cancel()
            await asyncio.gather(*callers, return_exceptions=True)
            executor.shutdown(wait=True, cancel_futures=True)

    asyncio.run(scenario())
    assert len(post_calls) == 1


def test_get_authorization_header_concurrent_threads_no_deadlock(monkeypatch):
    """Concurrent callers on different event loops/threads must not deadlock.

    The embedded/TUI sync tool-call path (``DeerFlowClient.stream()`` ->
    LangGraph's ``ToolNode._func`` -> a ``ThreadPoolExecutor`` ->
    ``deerflow.tools.sync.make_sync_tool_wrapper``'s per-call ``asyncio.run()``)
    invokes ``get_authorization_header`` from a fresh event loop on a fresh OS
    thread for every concurrent tool call. A per-server ``asyncio.Lock`` binds
    to whichever loop first contends on it; when a caller on a *different*
    loop later releases/wakes a waiter, it does so without
    ``call_soon_threadsafe``, so the waiting loop's selector is never woken
    and that caller hangs forever with no exception (a silent hang). A third
    concurrent caller instead hits a synchronous ``RuntimeError: ... is bound
    to a different event loop``. Both failure modes are reproducible with the
    old ``asyncio.Lock``-per-server implementation.

    This test uses a bounded thread-join timeout so that a regression back to
    the old behavior fails this test quickly instead of hanging the whole
    suite.
    """
    post_calls: list[dict[str, Any]] = []
    post_calls_guard = threading.Lock()
    holder_in_critical_section = threading.Event()

    class _SlowMockAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, data: dict[str, Any]):
            with post_calls_guard:
                post_calls.append({"url": url, "data": data})
            # Signal that this call is inside the critical section (the lock
            # is held) and stay there briefly so the other threads have time
            # to reach their own acquire() and genuinely contend, rather than
            # racing to also take an uncontended fast path.
            holder_in_critical_section.set()
            await asyncio.sleep(0.3)
            return _MockResponse(
                {
                    "access_token": "concurrent-token",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                }
            )

    monkeypatch.setattr("httpx.AsyncClient", _SlowMockAsyncClient)

    config = ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )

    manager = OAuthTokenManager.from_extensions_config(config)
    results: dict[str, Any] = {}

    def run_in_own_loop(name: str, wait_for_holder: bool) -> None:
        if wait_for_holder:
            # Only start once another thread is confirmed to be holding the
            # lock, guaranteeing this call contends instead of racing for
            # the uncontended fast path itself.
            assert holder_in_critical_section.wait(timeout=5), "holder thread never entered critical section"
        try:
            results[name] = asyncio.run(manager.get_authorization_header("secure-http"))
        except BaseException as exc:  # noqa: BLE001 - captured to assert absence below
            results[name] = exc

    threads = [
        threading.Thread(target=run_in_own_loop, args=("holder", False), name="holder", daemon=True),
        threading.Thread(target=run_in_own_loop, args=("waiter-1", True), name="waiter-1", daemon=True),
        threading.Thread(target=run_in_own_loop, args=("waiter-2", True), name="waiter-2", daemon=True),
    ]

    for t in threads:
        t.start()

    # Bounded timeout: under the old per-server asyncio.Lock, at least one of
    # these threads would never return. Joining with a timeout keeps a
    # regression from hanging the test suite forever; it fails fast instead.
    for t in threads:
        t.join(timeout=5)

    still_alive = [t.name for t in threads if t.is_alive()]
    assert not still_alive, f"deadlock: thread(s) still blocked after bounded timeout: {still_alive}"

    for name, result in results.items():
        assert not isinstance(result, BaseException), f"{name} raised instead of completing: {result!r}"
        assert result == "Bearer concurrent-token"

    # De-duplication must be preserved: three concurrent callers racing for
    # the same (initially uncached) server must still only perform ONE real
    # token fetch, not one per caller.
    assert len(post_calls) == 1


@pytest.mark.parametrize("failure", ["cancel", "error"])
def test_failed_refresh_owner_allows_waiter_to_retry(monkeypatch, failure):
    """A refresh failure belongs to its caller; a waiting caller can retry."""

    async def scenario():
        entered = asyncio.Event()
        release = asyncio.Event()
        attempts = 0

        class HeldClient(_MockAsyncClient):
            async def post(self, url, data):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    entered.set()
                    await release.wait()
                    raise RuntimeError("first refresh failed")
                return await super().post(url, data)

        monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: HeldClient(payload={"access_token": "recovered-token", "expires_in": 3600}, post_calls=[], **kwargs))
        manager = OAuthTokenManager({"secure-http": McpOAuthConfig(enabled=True, token_url="https://auth.example.com/token", client_id="client-id", client_secret="client-secret")})
        owner = asyncio.create_task(manager.get_authorization_header("secure-http"))
        callers = [owner]
        try:
            await asyncio.wait_for(entered.wait(), 5)
            waiter = asyncio.create_task(manager.get_authorization_header("secure-http"))
            callers.append(waiter)
            waiting = asyncio.get_running_loop().create_future()
            asyncio.get_running_loop().call_soon(waiting.set_result, None)
            await waiting
            if failure == "cancel":
                owner.cancel()
            else:
                release.set()
            with pytest.raises(asyncio.CancelledError if failure == "cancel" else RuntimeError):
                await owner
            assert await asyncio.wait_for(waiter, 5) == "Bearer recovered-token"
            assert await manager.get_authorization_header("secure-http") == "Bearer recovered-token"
            assert attempts == 2
        finally:
            release.set()
            for caller in callers:
                caller.cancel()
            await asyncio.gather(*callers, return_exceptions=True)

    asyncio.run(scenario())


def test_cancelled_waiter_can_close_its_loop_during_refresh(monkeypatch, caplog):
    """A cancelled sync wrapper can close its loop without disturbing the owner."""
    entered = threading.Event()
    release = threading.Event()
    post_calls: list[dict[str, Any]] = []

    class HeldClient(_MockAsyncClient):
        async def post(self, url, data):
            entered.set()
            assert await asyncio.to_thread(release.wait, 5), "test did not release refresh"
            return await super().post(url, data)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kwargs: HeldClient(payload={"access_token": "shared-token", "expires_in": 3600}, post_calls=post_calls, **kwargs))
    manager = OAuthTokenManager({"secure-http": McpOAuthConfig(enabled=True, token_url="https://auth.example.com/token", client_id="client-id", client_secret="client-secret")})

    async def cancel_waiter():
        waiter = asyncio.create_task(manager.get_authorization_header("secure-http"))
        waiting = asyncio.get_running_loop().create_future()
        asyncio.get_running_loop().call_soon(waiting.set_result, None)
        await waiting
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter

    with ThreadPoolExecutor(max_workers=2) as callers:
        owner = callers.submit(asyncio.run, manager.get_authorization_header("secure-http"))
        try:
            assert entered.wait(5), "refresh did not start"
            cancelled = callers.submit(asyncio.run, cancel_waiter())
            cancelled.result(timeout=2)
            assert not owner.done(), "owner should still be waiting on the token response"
        finally:
            release.set()
        assert owner.result(timeout=5) == "Bearer shared-token"
    assert asyncio.run(manager.get_authorization_header("secure-http")) == "Bearer shared-token"
    assert len(post_calls) == 1
    assert not any(record.name == "concurrent.futures" and record.levelno >= logging.ERROR for record in caplog.records)


# --- Illegal header values ---------------------------------------------------
#
# What the token endpoint returns is not this process's to control. An
# access_token or token_type carrying a newline reaches h11, which raises with
# the full value in the message, and ToolErrorHandlingMiddleware copies that
# message into a model-visible ToolMessage. Every one of these asserts the
# token never appears in what the caller sees.


def _oauth_server_config() -> ExtensionsConfig:
    return ExtensionsConfig.model_validate(
        {
            "mcpServers": {
                "secure-http": {
                    "enabled": True,
                    "type": "http",
                    "url": "https://api.example.com/mcp",
                    "oauth": {
                        "enabled": True,
                        "token_url": "https://auth.example.com/oauth/token",
                        "grant_type": "client_credentials",
                        "client_id": "client-id",
                        "client_secret": "client-secret",
                    },
                }
            }
        }
    )


def _token_endpoint_returns(monkeypatch, payload: dict[str, Any]) -> list[dict[str, Any]]:
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(payload=payload, post_calls=post_calls, **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _client_factory)
    return post_calls


@pytest.mark.parametrize(
    ("payload", "secret"),
    [
        (
            {"access_token": "oauth-secret-123\n", "token_type": "Bearer", "expires_in": 3600},
            "oauth-secret-123",
        ),
        (
            {"access_token": "oauth-secret-456", "token_type": "Bearer\r", "expires_in": 3600},
            "oauth-secret-456",
        ),
        (
            {"access_token": "oauth-secret-caf\u00e9", "token_type": "Bearer", "expires_in": 3600},
            "oauth-secret-caf\u00e9",
        ),
        (
            {"access_token": "oauth-secret-789 ", "token_type": "Bearer", "expires_in": 3600},
            "oauth-secret-789",
        ),
    ],
    ids=["trailing-newline", "cr-in-token-type", "non-ascii", "trailing-space"],
)
def test_illegal_oauth_token_is_denied_without_leaking(monkeypatch, payload, secret):
    _token_endpoint_returns(monkeypatch, payload)
    manager = OAuthTokenManager.from_extensions_config(_oauth_server_config())

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(manager.get_authorization_header("secure-http"))

    message = str(excinfo.value)
    assert secret not in message
    assert "secure-http" in message


def test_oauth_token_kept_legal_by_the_space_after_token_type_is_accepted(monkeypatch):
    # The rendered value is the boundary, not the two fields on their own: this
    # access_token carries leading whitespace, which the transport tolerates
    # once it follows "Bearer ". Denying it would refuse a token the server
    # would have accepted.
    _token_endpoint_returns(monkeypatch, {"access_token": " leading-space-token", "token_type": "Bearer", "expires_in": 3600})
    manager = OAuthTokenManager.from_extensions_config(_oauth_server_config())

    assert asyncio.run(manager.get_authorization_header("secure-http")) == "Bearer  leading-space-token"


def test_oauth_interceptor_denies_illegal_token_without_calling_the_handler(monkeypatch):
    _token_endpoint_returns(monkeypatch, {"access_token": "oauth-secret-abc\n", "token_type": "Bearer", "expires_in": 3600})
    config = _oauth_server_config()
    interceptor = build_oauth_tool_interceptor(config)
    assert interceptor is not None

    class _Request:
        server_name = "secure-http"
        headers: dict[str, str] = {}

        def override(self, **kwargs):  # pragma: no cover - denied before reached
            raise AssertionError("the request must never be forwarded with an illegal token")

    handler_calls: list[Any] = []

    async def _handler(request):  # pragma: no cover - denied before reached
        handler_calls.append(request)
        return "ok"

    with pytest.raises(ValueError) as excinfo:
        asyncio.run(interceptor(_Request(), _handler))

    assert "oauth-secret-abc" not in str(excinfo.value)
    assert handler_calls == []


def test_initial_oauth_headers_skips_server_with_illegal_token(monkeypatch, caplog):
    _token_endpoint_returns(monkeypatch, {"access_token": "oauth-secret-xyz\n", "token_type": "Bearer", "expires_in": 3600})
    config = _oauth_server_config()

    with caplog.at_level(logging.WARNING, logger="deerflow.mcp.oauth"):
        headers = asyncio.run(get_initial_oauth_headers(config))

    # No header at all rather than a broken one: the connection then fails
    # authentication at the server, which says nothing about the token.
    assert headers == {}
    assert "oauth-secret-xyz" not in caplog.text
