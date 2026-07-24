"""Tests for MCP OAuth support."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from deerflow.config.extensions_config import ExtensionsConfig
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
        # because OAuthTokenManager iterates _oauth_by_server in dict order
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


def test_get_authorization_header_cancelled_while_waiting_does_not_leak_lock(monkeypatch):
    """A caller cancelled while waiting on the per-server lock must not leak it.

    ``get_authorization_header`` runs ``lock.acquire()`` on a real OS thread via
    ``asyncio.to_thread`` so a blocking wait never blocks the event loop. Once that
    thread has actually started running ``lock.acquire()``, Python cannot interrupt
    it: cancelling the *caller* only stops the caller from continuing, it does not
    stop the thread. If cancellation at that await let the thread go on to acquire
    the lock unobserved (nobody left holding a reference that will call
    ``release()`` for it), the lock would stay held forever and every subsequent
    call for this server would block permanently at the same line -- the very
    cross-thread deadlock this file's lock was introduced to fix, reintroduced via
    a different path.

    This test holds the per-server lock (simulating another in-flight caller),
    starts a second caller that has to wait for it, cancels that waiter while it
    is genuinely blocked in its executor thread, releases the original holder, and
    then asserts a third caller completes within a bounded timeout and performs
    exactly one token fetch. Every potentially-hanging await is wrapped in a
    bounded timeout so a regression fails this test quickly instead of hanging the
    suite.
    """
    post_calls: list[dict[str, Any]] = []

    def _client_factory(*args, **kwargs):
        return _MockAsyncClient(
            payload={
                "access_token": "after-cancel-token",
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
    lock = manager._locks["secure-http"]

    async def scenario() -> None:
        # Simulate another in-flight caller already holding the per-server lock
        # (uncontended, so this succeeds immediately without blocking).
        lock.acquire()
        try:
            waiter = asyncio.create_task(manager.get_authorization_header("secure-http"))

            # Let the waiter's asyncio.to_thread(lock.acquire) actually get
            # scheduled onto an executor thread and start genuinely blocking on
            # the real lock before cancelling it -- otherwise the cancellation
            # could land before the thread even starts, which would not exercise
            # the bug.
            await asyncio.sleep(0.2)

            waiter.cancel()
            # The original holder finishes its own work and releases *before* we
            # wait on the cancelled waiter: a correct fix must keep the lock's
            # eventual acquisition shielded from this coroutine's cancellation and
            # wait for it to actually land before releasing, so awaiting the
            # cancelled waiter can legitimately block until the lock is free
            # either way.
            lock.release()

            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(waiter, timeout=5)

            # The crux of the regression: under the bug, the waiter's abandoned
            # executor thread went on to acquire the lock with nobody left to
            # release it, so this third call would block forever. Bound it so a
            # regression fails fast instead of hanging the test itself.
            third = await asyncio.wait_for(manager.get_authorization_header("secure-http"), timeout=5)
            assert third == "Bearer after-cancel-token"
        finally:
            # Test-only safety net, independent of the assertions above: under
            # the bug, the lock is left permanently locked with a background
            # thread (from whichever caller's orphaned acquisition landed last)
            # still parked on a *subsequent* acquire() that will now never
            # return. asyncio.run()'s own teardown joins every thread the
            # default executor ever created before it returns, so leaving that
            # thread stuck would hang this test process at interpreter/loop
            # shutdown even after the failure above is already reported. Forcing
            # the lock open here lets any such thread finish so the process can
            # exit; it is a no-op once the fix keeps the lock correctly balanced.
            if lock.locked():
                lock.release()

    asyncio.run(scenario())

    # Exactly one real token fetch: the cancelled waiter must never reach
    # _fetch_token, so the third call is the only one that performs it.
    assert len(post_calls) == 1
