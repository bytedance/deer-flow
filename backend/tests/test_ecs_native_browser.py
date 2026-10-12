import importlib
from types import SimpleNamespace

import pytest


def module():
    assert importlib.util.find_spec("ecs_executor.browser") is not None, "Native browser transport is missing"
    return importlib.import_module("ecs_executor.browser")


def test_transport_requires_tls_and_literal_loopback_fixture_exception():
    browser = module()
    assert browser.worker_tunnel_url("https://control.example", False) == "wss://control.example"
    assert browser.worker_tunnel_url("http://127.0.0.1:8888", True) == "ws://127.0.0.1:8888"
    for value in ("http://control.example", "http://localhost:8888", "https://user:secret@control.example", "https://control.example/path"):
        with pytest.raises(ValueError):
            browser.worker_tunnel_url(value, True)


def test_signed_operation_binds_original_headers_and_only_native_operations():
    browser = module()
    from ecs_executor.scope import mint_execution_scope

    args = {"id": "request", "owner": "worker-owner", "user_id": "user", "thread_id": "thread", "incarnation": "inc", "headers": [["cookie", "access_token=secret"]], "query": "", "scheme": "http", "url": "https://example.com"}
    token = mint_execution_scope(secret=b"x" * 48, audience="node", user_id="user", thread_id="thread", incarnation="inc", run_id="request", operation="browser_navigate", arguments=args)
    scope = browser.verify_browser_operation("navigate", args, token, secret="x" * 48, node="node", owner="worker-owner")
    assert scope.thread_id == "thread"
    changed = {**args, "headers": [["cookie", "access_token=changed"]]}
    with pytest.raises(ValueError):
        browser.verify_browser_operation("navigate", changed, token, secret="x" * 48, node="node", owner="worker-owner")
    with pytest.raises(ValueError):
        browser.verify_browser_operation("proxy", args, token, secret="x" * 48, node="node", owner="worker-owner")
    with pytest.raises(ValueError):
        browser.verify_browser_operation("navigate", args, token, secret="x" * 48, node="node", owner="new-worker")


def test_forwarded_headers_preserve_native_auth_origin_without_internal_authority():
    browser = module()
    headers = SimpleNamespace(
        raw=[(b"cookie", b"access_token=secret"), (b"host", b"control.example"), (b"origin", b"https://control.example"), (b"authorization", b"Bearer token"), (b"x-csrf-token", b"csrf"), (b"x-deerflow-internal-token", b"internal")]
    )
    forwarded = browser.forwarded_headers(headers)
    assert ["cookie", "access_token=secret"] in forwarded
    assert ["host", "control.example"] in forwarded
    assert ["origin", "https://control.example"] in forwarded
    assert ["authorization", "Bearer token"] in forwarded
    assert ["x-deerflow-internal-token", "internal"] not in forwarded


@pytest.mark.asyncio
async def test_worker_http_forwarding_supplies_native_asgi_method_and_identity():
    import json
    from unittest.mock import AsyncMock

    from ecs_executor.scope import mint_execution_scope

    from deerflow.community.browser_automation.session import BrowserSessionScope, browser_session_key

    browser = module()
    provider = browser.NativeBrowserControl({"role": "worker", "node_id": "node"}, {})
    provider.host = SimpleNamespace(secret="x" * 48, owner="worker")
    scope = BrowserSessionScope("user", "thread", "inc")
    provider._current_scope = AsyncMock(return_value=scope)

    async def native_asgi(asgi, receive, send):
        assert asgi["method"] == "POST"
        assert asgi["path"] == "/api/threads/thread/browser/navigate"
        assert browser_session_key("thread") == scope.key
        assert (b"cookie", b"access_token=original") in asgi["headers"]
        assert json.loads((await receive())["body"])["url"] == "https://example.com"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"title":"native","url":"https://example.com"}'})

    provider.app = native_asgi
    tunnel = SimpleNamespace(send=AsyncMock())
    args = {"id": "operation", "owner": "worker", "user_id": "user", "thread_id": "thread", "incarnation": "inc", "headers": [["cookie", "access_token=original"]], "query": "", "scheme": "https", "url": "https://example.com"}
    token = mint_execution_scope(secret=b"x" * 48, audience="node", user_id="user", thread_id="thread", incarnation="inc", run_id="operation", operation="browser_navigate", arguments=args)
    await provider.execute_operation(tunnel, {"operation": "navigate", "args": args, "capability": token}, __import__("asyncio").Queue())
    response = tunnel.send.call_args.args[0]
    assert response["kind"] == "http" and response["status"] == 200 and response["body"]["title"] == "native"


def test_native_live_session_disables_secret_bearing_locals(monkeypatch, request):
    from pathlib import Path

    expected = Path(__file__).resolve().with_name("conftest.py")
    plugins = [plugin for plugin in request.config.pluginmanager.get_plugins() if getattr(plugin, "__file__", None) and Path(plugin.__file__).resolve() == expected]
    assert len(plugins) == 1, "Backend privacy conftest plugin must be loaded exactly once"
    conftest = plugins[0]

    assert hasattr(conftest, "pytest_configure"), "Live privacy policy is missing"
    config = SimpleNamespace(option=SimpleNamespace(showlocals=True))
    monkeypatch.setenv("ECS_NATIVE_LIVE", "1")
    conftest.pytest_configure(config)
    assert config.option.showlocals is False
    monkeypatch.delenv("ECS_NATIVE_LIVE")
    ordinary = SimpleNamespace(option=SimpleNamespace(showlocals=True))
    conftest.pytest_configure(ordinary)
    assert ordinary.option.showlocals is True


@pytest.mark.asyncio
async def test_retirement_cancels_only_matching_scope_and_awaits_it(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from deerflow.community.browser_automation.session import BrowserSessionScope

    browser = module()
    provider = browser.NativeBrowserControl({"role": "worker"}, {})
    stale = BrowserSessionScope("old", "old-thread", "inc")
    fresh = BrowserSessionScope("new", "new-thread", "inc")
    finished = asyncio.Event()

    async def pending():
        try:
            await asyncio.Future()
        finally:
            finished.set()

    old_task = asyncio.create_task(pending())
    new_task = asyncio.create_task(asyncio.sleep(60))
    await asyncio.sleep(0)
    provider.operations = {"old": (old_task, asyncio.Queue()), "new": (new_task, asyncio.Queue())}
    provider.operation_scopes = {"old": stale, "new": fresh}
    manager = SimpleNamespace(close_scoped_session=AsyncMock(), retained_session_keys=lambda: frozenset())
    monkeypatch.setattr(browser, "get_browser_session_manager", lambda: manager)
    try:
        await provider._retire_scope(stale)
        assert old_task.cancelled() and finished.is_set()
        assert not new_task.done()
        manager.close_scoped_session.assert_awaited_once_with(stale)
    finally:
        new_task.cancel()
        await asyncio.gather(new_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_native_http_sends_unknown_terminal():
    import asyncio
    from unittest.mock import AsyncMock

    from ecs_executor.scope import mint_execution_scope

    from deerflow.community.browser_automation.session import BrowserSessionScope

    browser = module()
    provider = browser.NativeBrowserControl({"role": "worker", "node_id": "node"}, {})
    provider.host = SimpleNamespace(secret="x" * 48, owner="worker")
    provider._current_scope = AsyncMock(return_value=BrowserSessionScope("user", "thread", "inc"))
    entered = asyncio.Event()

    async def asgi(*args):
        entered.set()
        await asyncio.Future()

    provider.app = asgi
    tunnel = SimpleNamespace(send=AsyncMock())
    args = {"id": "operation", "owner": "worker", "user_id": "user", "thread_id": "thread", "incarnation": "inc", "headers": [], "query": "", "scheme": "https", "url": "https://example.com"}
    token = mint_execution_scope(secret=b"x" * 48, audience="node", user_id="user", thread_id="thread", incarnation="inc", run_id="operation", operation="browser_navigate", arguments=args)
    task = asyncio.create_task(provider.execute_operation(tunnel, {"operation": "navigate", "args": args, "capability": token}, asyncio.Queue()))
    await entered.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert tunnel.send.call_args.args[0] == {"kind": "http", "id": "operation", "status": 503, "body": {"detail": "Browser operation outcome unknown"}}


def test_scope_registry_prunes_unused_but_retains_physical_unknown(monkeypatch):
    from deerflow.community.browser_automation.session import BrowserSessionScope

    browser = module()
    provider = browser.NativeBrowserControl({"role": "worker"}, {})
    retained = BrowserSessionScope("user", "retained", "inc")
    manager = SimpleNamespace(retained_session_keys=lambda: frozenset({retained.key}))
    monkeypatch.setattr(browser, "get_browser_session_manager", lambda: manager)
    provider._remember_scope(retained)
    for index in range(100):
        provider._remember_scope(BrowserSessionScope("user", str(index), "inc"))
    provider._prune_scopes()
    assert provider.scopes == {retained.key: retained}


@pytest.mark.asyncio
async def test_worker_browser_cleanup_is_owned_only_by_native_host(monkeypatch):
    from contextlib import AsyncExitStack
    from unittest.mock import AsyncMock

    from app.gateway import browser_control, deps

    provider = SimpleNamespace(stop=AsyncMock())
    monkeypatch.setattr(browser_control, "get_browser_control", lambda app: provider)
    for role in ("worker", "central"):
        host = SimpleNamespace(stop=AsyncMock())
        app = SimpleNamespace(state=SimpleNamespace(browser_control_snapshot=SimpleNamespace(native_config={"role": role})))
        async with AsyncExitStack() as stack:
            deps._register_native_host_cleanup(stack, app, host)
        host.stop.assert_awaited_once()
        assert provider.stop.await_count == (1 if role == "central" else 0)


def test_scope_registry_has_explicit_bound_for_active_identities(monkeypatch):
    from deerflow.community.browser_automation.session import BrowserSessionScope

    browser = module()
    provider = browser.NativeBrowserControl({"role": "worker"}, {})
    monkeypatch.setattr(browser, "get_browser_session_manager", lambda: SimpleNamespace(retained_session_keys=lambda: frozenset()))
    for index in range(browser.MAX_CHANNELS + 2):
        scope = BrowserSessionScope("user", str(index), "inc")
        provider.execution_scopes[scope.key] = None
        provider._remember_scope(scope)
    with pytest.raises(Exception, match="registry capacity"):
        provider._remember_scope(BrowserSessionScope("user", "overflow", "inc"))


@pytest.mark.asyncio
async def test_native_execution_scope_tracks_task_until_browser_or_finalizer_finishes(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from deerflow.community.browser_automation.session import BrowserSessionScope, browser_session_key

    browser = module()
    scope = BrowserSessionScope("user", "thread", "inc")
    provider = browser.NativeBrowserControl({"role": "worker"}, {})
    provider._current_scope = AsyncMock(return_value=scope)
    monkeypatch.setattr(browser, "get_browser_session_manager", lambda: SimpleNamespace(retained_session_keys=lambda: frozenset()))
    ready = asyncio.Event()
    finish = asyncio.Event()

    async def native_task():
        assert browser_session_key("thread") == scope.key
        ready.set()
        await finish.wait()

    with await provider.execution_scope({"user_id": "user", "thread_id": "thread", "incarnation": "inc"}) as attach:
        task = asyncio.create_task(native_task())
        attach(task)
    await ready.wait()
    provider._prune_scopes()
    assert provider.scopes == {scope.key: scope}
    finish.set()
    await task
    await asyncio.sleep(0)
    assert provider.scopes == {} and provider.execution_scopes == {}


@pytest.mark.asyncio
async def test_central_preserves_only_controlled_unknown_outcome_detail():
    import asyncio
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    browser = module()
    provider = browser.NativeBrowserControl({"role": "central"}, {})
    request = SimpleNamespace(state=SimpleNamespace(auth=SimpleNamespace(user=SimpleNamespace(id="user"))))
    for detail, expected in (("Browser operation outcome unknown", "Browser operation outcome unknown"), ("private worker diagnostic", "Native worker browser operation rejected")):
        queue = asyncio.Queue()
        queue.put_nowait({"kind": "http", "status": 503, "body": {"detail": detail}})
        tunnel = SimpleNamespace(channels={"operation": queue}, send=AsyncMock())
        provider._open = AsyncMock(return_value=("operation", queue, tunnel))
        with pytest.raises(HTTPException) as raised:
            await provider.navigate(request, "thread", "https://example.com")
        assert raised.value.status_code == 503 and raised.value.detail == expected
