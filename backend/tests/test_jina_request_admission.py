"""Offline Jina admission regressions through the real HTTPX transport boundary."""

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.jina_ai import request_admission as admission_module
from deerflow.community.jina_ai import tools
from deerflow.community.jina_ai.jina_client import JinaClient

pytestmark = pytest.mark.anyio
POLICY = {"max_concurrent_requests": 1, "max_queue_size": 3, "max_wait_seconds": 5}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_policy(monkeypatch):
    monkeypatch.setattr(admission_module, "_admission", None)
    yield
    budget = admission_module._admission
    if budget is not None:
        assert budget._active == 0
        assert not budget._queue


@pytest.fixture
def install_transport(monkeypatch):
    original = httpx.AsyncClient
    monkeypatch.setenv("JINA_API_KEY", "dummy-test-key")

    def install(handler):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), trust_env=False))

    return install


async def test_tool_rejects_full_queue_before_dispatch(monkeypatch, install_transport):
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def handle(request):
        nonlocal calls
        calls += 1
        entered.set()
        if calls == 1:
            await release.wait()
        return httpx.Response(401, text="offline status")

    install_transport(handle)
    config = SimpleNamespace(model_extra={"request_admission": {**POLICY, "max_queue_size": 0}})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))
    first = asyncio.create_task(tools.web_fetch_tool.ainvoke("https://example.com/first"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        result = await tools.web_fetch_tool.ainvoke("https://example.com/second")
        assert result == "Error: Local Jina request admission rejected: queue full"
        assert calls == 1
        assert set(tools.web_fetch_tool.args) == {"url"}
    finally:
        release.set()
        await first


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0)


def queued(count):
    budget = admission_module._admission
    if budget is None:
        return False
    with budget._lock:
        return len(budget._queue) == count


def crawl(name="page", policy=POLICY, **kwargs):
    return JinaClient().crawl(f"https://example.com/{name}", request_admission=policy, **kwargs)


class Stream(httpx.AsyncByteStream):
    def __init__(self, *, chunks=(b"ok",), read_error=None, close_error=None, hold_read=False, hold_close=False):
        self.chunks = chunks
        self.read_error = read_error
        self.close_error = close_error
        self.hold_read = hold_read
        self.hold_close = hold_close
        self.reading = asyncio.Event()
        self.closing = asyncio.Event()
        self.release_read = asyncio.Event()
        self.release_close = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        self.reading.set()
        if self.hold_read:
            await self.release_read.wait()
        if self.read_error:
            raise self.read_error
        for chunk in self.chunks:
            yield chunk

    async def aclose(self):
        self.closing.set()
        if self.hold_close:
            await self.release_close.wait()
        self.closed = True
        if self.close_error:
            raise self.close_error


@pytest.mark.parametrize("policy", [None, POLICY])
@pytest.mark.parametrize("cap", [None, 2])
async def test_default_concurrency_and_enabled_fifo(install_transport, policy, cap):
    entered = []
    releases = [asyncio.Event() for _ in range(8)]

    async def handle(request):
        number = int(json.loads(request.content)["url"].rsplit("/", 1)[1])
        entered.append(number)
        await releases[number].wait()
        return httpx.Response(200, text="ok")

    install_transport(handle)
    options = None if policy is None else {**policy, "max_queue_size": 7}
    tasks = []
    try:
        for i in range(8):
            tasks.append(asyncio.create_task(crawl(str(i), options, max_response_bytes=cap)))
            await until(lambda: len(entered) == i + 1 if policy is None else len(entered) == 1 and queued(i))
        assert entered == (list(range(8)) if policy is None else [0])
        for i in range(8):
            releases[i].set()
            assert await tasks[i] == "ok"
            if policy is not None and i < 7:
                await until(lambda: len(entered) == i + 2)
                assert entered == list(range(i + 2))
    finally:
        for event in releases:
            event.set()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("cancel_index", [0, 1])
async def test_queued_cancellation_removes_head_or_middle(install_transport, cancel_index):
    stream = Stream(hold_read=True)
    names = []

    def handle(request):
        names.append(json.loads(request.content)["url"].rsplit("/", 1)[1])
        return httpx.Response(200, stream=stream) if len(names) == 1 else httpx.Response(200, text="ok")

    install_transport(handle)
    active = asyncio.create_task(crawl("active"))
    await stream.reading.wait()
    tasks = []
    try:
        for i in range(3):
            tasks.append(asyncio.create_task(crawl(str(i))))
            await until(lambda: queued(i + 1))
        tasks[cancel_index].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[cancel_index]
        assert queued(2)
        stream.release_read.set()
        await active
        await asyncio.gather(*tasks, return_exceptions=True)
        assert names == ["active"] + [str(i) for i in range(3) if i != cancel_index]
    finally:
        stream.release_read.set()
        await asyncio.gather(active, *tasks, return_exceptions=True)


@pytest.mark.parametrize("retry_budget", [None, 0.02])
async def test_wait_timeout_is_terminal_and_consumes_retry_budget(install_transport, retry_budget):
    stream = Stream(hold_read=True)
    calls = []
    install_transport(lambda request: calls.append(request) or httpx.Response(200, stream=stream))
    policy = {**POLICY, "max_wait_seconds": 0.02 if retry_budget is None else 5}
    first = asyncio.create_task(crawl(policy=policy))
    await stream.reading.wait()
    try:
        options = {} if retry_budget is None else {"max_retries": 2, "retry_budget_seconds": retry_budget}
        result = await asyncio.wait_for(crawl(policy=policy, **options), 1)
        assert result == "Error: Local Jina request admission rejected: wait expired"
        assert len(calls) == 1
        assert queued(0)
    finally:
        stream.release_read.set()
        await first


@pytest.mark.parametrize("cap", [None, 2])
@pytest.mark.parametrize("failure", ["transport", "status", "read", "close", "byte_cap"])
async def test_failures_release_lease(install_transport, cap, failure):
    calls = 0
    stream = Stream(
        chunks=(b"oversize",) if failure == "byte_cap" else (b"ok",),
        read_error=httpx.ReadError("read failed") if failure == "read" else None,
        close_error=RuntimeError("close failed") if failure == "close" else None,
    )

    def handle(request):
        nonlocal calls
        calls += 1
        if calls > 1:
            return httpx.Response(200, text="ok")
        if failure == "transport":
            raise httpx.ConnectError("connect failed")
        return httpx.Response(401 if failure == "status" else 200, stream=stream)

    install_transport(handle)
    result = await crawl(max_response_bytes=cap)
    if failure == "byte_cap" and cap is None:
        assert result == "oversize"
    else:
        assert result.startswith("Error:")
    if failure != "transport":
        assert stream.closed
    assert await crawl(max_response_bytes=cap) == "ok"


@pytest.mark.parametrize("at_close", [False, True])
async def test_repeated_active_cancel_waits_for_cleanup(install_transport, at_close):
    stream = Stream(hold_read=not at_close, hold_close=True)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream) if len(calls) == 1 else httpx.Response(200, text="ok")

    install_transport(handle)
    first = asyncio.create_task(crawl())
    second = None
    try:
        await (stream.closing if at_close else stream.reading).wait()
        first.cancel()
        await stream.closing.wait()
        second = asyncio.create_task(crawl())
        await until(lambda: queued(1))
        first.cancel()
        await asyncio.sleep(0)
        assert len(calls) == 1 and not first.done()
        stream.release_close.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert stream.closed
        assert await second == "ok"
    finally:
        stream.release_read.set()
        stream.release_close.set()
        await asyncio.gather(*[task for task in (first, second) if task], return_exceptions=True)


@pytest.mark.parametrize(
    "field,values",
    [
        ("max_concurrent_requests", [True, False, 0, -1, 1.5, "2", None]),
        ("max_queue_size", [True, False, -1, 1.5, "2", None]),
        ("max_wait_seconds", [True, False, 0, -1, float("inf"), float("nan"), "2", None, 10**400]),
    ],
)
async def test_invalid_policy_before_client_activity(monkeypatch, field, values):
    def unexpected(**kwargs):
        pytest.fail("invalid policy created a client")

    monkeypatch.setattr(httpx, "AsyncClient", unexpected)
    for value in values:
        result = await crawl(policy={**POLICY, field: value})
        assert result.startswith("Error:") and field in result
    assert admission_module._admission is None


@pytest.mark.parametrize("value", [False, True, 1, [], {}, {**POLICY, "typo": 1}])
async def test_malformed_policy_before_client_activity(monkeypatch, value):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("invalid policy created a client"))
    assert "request_admission requires" in await crawl(policy=value)


async def test_enabled_policy_is_immutable_and_applies_to_later_null_calls(install_transport):
    calls = []
    stream = Stream(hold_read=True)

    def handle(request):
        name = json.loads(request.content)["url"].rsplit("/", 1)[1]
        calls.append(name)
        return httpx.Response(200, stream=stream) if name == "enabled" else httpx.Response(200, text="ok")

    install_transport(handle)
    assert await crawl("before", policy=None) == "ok"
    assert admission_module._admission is None
    active = asyncio.create_task(crawl("enabled"))
    omitted = None
    try:
        await stream.reading.wait()
        budget = admission_module._admission
        omitted = asyncio.create_task(crawl("omitted", policy=None))
        await until(lambda: queued(1))
        assert calls == ["before", "enabled"]
        assert "restart required" in await crawl(policy={**POLICY, "max_concurrent_requests": 2})
        assert admission_module._admission is budget
        stream.release_read.set()
        assert await active == "ok"
        assert await omitted == "ok"
        assert calls == ["before", "enabled", "omitted"]
    finally:
        stream.release_read.set()
        await asyncio.gather(*[task for task in (active, omitted) if task], return_exceptions=True)


async def test_threads_and_event_loops_share_one_budget(install_transport):
    entered = []
    lock = threading.Lock()
    release = threading.Event()
    policy = {**POLICY, "max_queue_size": 7}

    async def handle(request):
        with lock:
            entered.append(json.loads(request.content)["url"])
        assert await asyncio.to_thread(release.wait, 3)
        return httpx.Response(200, text="ok")

    install_transport(handle)
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(asyncio.run, crawl(str(i), policy)) for i in range(8)]
        try:
            await until(lambda: admission_module._admission is not None and queued(7))
            with lock:
                assert len(entered) == 1
            release.set()
            results = await asyncio.gather(*(asyncio.wrap_future(f) for f in futures))
            assert results == ["ok"] * 8
        finally:
            release.set()


async def test_grant_cancel_race_returns_reserved_permit(install_transport, monkeypatch):
    stream = Stream(hold_read=True)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream) if len(calls) == 1 else httpx.Response(200, text="ok")

    install_transport(handle)
    first = asyncio.create_task(crawl())
    await stream.reading.wait()
    second = asyncio.create_task(crawl())
    await until(lambda: queued(1))
    original = admission_module._Ticket.wake

    def cancel_at_grant(ticket):
        second.cancel()
        original(ticket)

    monkeypatch.setattr(admission_module._Ticket, "wake", cancel_at_grant)
    stream.release_read.set()
    await first
    with pytest.raises(asyncio.CancelledError):
        await second
    assert await crawl() == "ok"


async def test_expired_grant_never_dispatches(install_transport, monkeypatch):
    stream = Stream(hold_read=True)
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream) if len(calls) == 1 else httpx.Response(200, text="ok")

    install_transport(handle)
    first = asyncio.create_task(crawl())
    await stream.reading.wait()
    second = asyncio.create_task(crawl())
    await until(lambda: queued(1))
    original = admission_module._Ticket.wake

    def expire_at_grant(ticket):
        ticket.deadline = 0
        original(ticket)

    monkeypatch.setattr(admission_module._Ticket, "wake", expire_at_grant)
    stream.release_read.set()
    await first
    assert "wait expired" in await second
    assert len(calls) == 1
    assert await crawl() == "ok"


@pytest.mark.parametrize("expired", [False, True])
async def test_closed_owner_loop_returns_reserved_permit(expired):
    budget = admission_module.get_admission(POLICY)
    main_loop = asyncio.get_running_loop()
    active = admission_module._Ticket(main_loop, main_loop.create_future(), float("inf"), state="granted")

    def closed_loop_ticket():
        loop = asyncio.new_event_loop()
        try:
            return admission_module._Ticket(loop, loop.create_future(), 0 if expired else float("inf"))
        finally:
            loop.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        ticket = await asyncio.wrap_future(executor.submit(closed_loop_ticket))

    with budget._lock:
        budget._active = 1
        budget._queue.append(ticket)

    budget._finish(active)
    assert ticket.state == "released"
    assert budget._active == 0
    assert not budget._queue

    # Finishing the orphan again must not decrement a granted or expired ticket.
    budget._finish(ticket)
    assert budget._active == 0
    async with budget.attempt(None):
        assert budget._active == 1
    assert budget._active == 0


async def test_retry_releases_during_backoff_and_rejoins_fifo(install_transport, monkeypatch):
    from deerflow.community.jina_ai import jina_client

    backoff, resume = asyncio.Event(), asyncio.Event()
    holding = Stream(hold_read=True)
    order = []
    original_sleep = asyncio.sleep

    async def sleep(delay):
        if delay > 0:
            backoff.set()
            await resume.wait()
        else:
            await original_sleep(delay)

    def handle(request):
        name = json.loads(request.content)["url"].rsplit("/", 1)[1]
        order.append(name)
        if order == ["retry"]:
            return httpx.Response(503, text="retry", headers={"Retry-After": "0"})
        return httpx.Response(200, stream=holding) if name == "holding" else httpx.Response(200, text="ok")

    monkeypatch.setattr(jina_client.asyncio, "sleep", sleep)
    install_transport(handle)
    retry = asyncio.create_task(crawl("retry", max_retries=1))
    await backoff.wait()
    active = asyncio.create_task(crawl("holding"))
    await holding.reading.wait()
    earlier = asyncio.create_task(crawl("earlier"))
    await until(lambda: queued(1))
    resume.set()
    await until(lambda: queued(2))
    holding.release_read.set()
    assert await asyncio.gather(retry, active, earlier) == ["ok"] * 3
    assert order == ["retry", "holding", "earlier", "retry"]


async def test_readability_failure_holds_no_permit(install_transport, monkeypatch):
    install_transport(lambda request: httpx.Response(200, text="<p>ok</p>"))
    config = SimpleNamespace(model_extra={"request_admission": POLICY})
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda name: config))

    def extract(*args, **kwargs):
        assert admission_module._admission._active == 0
        raise RuntimeError("extraction failed")

    monkeypatch.setattr(tools.readability_extractor, "extract_article", extract)
    with pytest.raises(RuntimeError, match="extraction failed"):
        await tools.web_fetch_tool.ainvoke("https://example.com")
    assert await crawl() == "<p>ok</p>"


async def test_capacity_greater_than_one_and_nonempty_full_queue(install_transport):
    streams = [Stream(hold_read=True) for _ in range(3)]
    calls = []
    policy = {**POLICY, "max_concurrent_requests": 3, "max_queue_size": 2}

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=streams[len(calls) - 1]) if len(calls) <= 3 else httpx.Response(200, text="ok")

    install_transport(handle)
    tasks = [asyncio.create_task(crawl(str(i), policy)) for i in range(5)]
    try:
        await until(lambda: queued(2))
        assert len(calls) == 3
        assert "queue full" in await crawl("full", policy, max_retries=2)
        assert len(calls) == 3
        for stream in streams:
            stream.release_read.set()
        assert await asyncio.gather(*tasks) == ["ok"] * 5
    finally:
        for stream in streams:
            stream.release_read.set()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_enabled_retries_reuse_one_client(monkeypatch):
    original_client = httpx.AsyncClient
    clients = []
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="retry", headers={"Retry-After": "0"})
        return httpx.Response(200, text="ok")

    def client(**kwargs):
        result = original_client(transport=httpx.MockTransport(handle), trust_env=False)
        clients.append(result)
        return result

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert await crawl(max_retries=1, retry_budget_seconds=2) == "ok"
    assert calls == 2
    assert len(clients) == 1


async def test_client_pool_close_does_not_hold_attempt_permit(monkeypatch):
    original_client = httpx.AsyncClient
    closing, release = asyncio.Event(), asyncio.Event()
    calls = []
    clients = []

    class Client(original_client):
        async def aclose(self):
            if self is clients[0]:
                closing.set()
                await release.wait()
            await super().aclose()

    def handle(request):
        calls.append(request)
        return httpx.Response(200, text="ok")

    def client(**kwargs):
        result = Client(transport=httpx.MockTransport(handle), trust_env=False)
        clients.append(result)
        return result

    monkeypatch.setattr(httpx, "AsyncClient", client)
    first = asyncio.create_task(crawl())
    try:
        await closing.wait()
        assert await crawl("second") == "ok"
        assert len(calls) == 2
        assert queued(0)
        release.set()
        assert await first == "ok"
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)


async def test_cancel_with_response_and_client_close_failures_preserves_cancel_and_permit(monkeypatch):
    original_client = httpx.AsyncClient
    stream = Stream(hold_read=True, close_error=RuntimeError("response close failed"))
    clients = []
    calls = []

    class Client(original_client):
        async def aclose(self):
            await super().aclose()
            if self is clients[0]:
                raise RuntimeError("client close failed")

    def handle(request):
        calls.append(request)
        return httpx.Response(200, stream=stream) if len(calls) == 1 else httpx.Response(200, text="ok")

    def client(**kwargs):
        result = Client(transport=httpx.MockTransport(handle), trust_env=False)
        clients.append(result)
        return result

    monkeypatch.setattr(httpx, "AsyncClient", client)
    first = asyncio.create_task(crawl("cancelled"))
    second = None
    try:
        await stream.reading.wait()
        second = asyncio.create_task(crawl("next"))
        await until(lambda: queued(1))
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert stream.closed
        assert await second == "ok"
        assert len(calls) == 2
    finally:
        stream.release_read.set()
        await asyncio.gather(*[task for task in (first, second) if task], return_exceptions=True)


async def test_successful_queue_wait_reduces_original_http_budget(install_transport, monkeypatch):
    loop = asyncio.get_running_loop()
    now = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: now[0])
    holding = Stream(hold_read=True)
    second_stream = Stream(hold_read=True)
    calls = []

    def handle(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, stream=holding)
        assert request.extensions["timeout"]["read"] == pytest.approx(0.25)
        return httpx.Response(200, stream=second_stream)

    install_transport(handle)
    first = asyncio.create_task(crawl())
    await holding.reading.wait()
    second = asyncio.create_task(crawl(max_retries=1, retry_budget_seconds=0.5))
    try:
        await until(lambda: queued(1))
        now[0] += 0.25
        holding.release_read.set()
        await first
        await second_stream.reading.wait()
        now[0] += 0.3
        assert "retry time budget exhausted" in await second
        assert second_stream.closed
        assert len(calls) == 2
    finally:
        holding.release_read.set()
        second_stream.release_read.set()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.parametrize("limit", [1, 2])
async def test_admission_preserves_decoded_byte_cap(install_transport, limit):
    import gzip

    stream = Stream(chunks=(gzip.compress(b"ok"),))
    install_transport(lambda request: httpx.Response(200, stream=stream, headers={"Content-Encoding": "gzip"}))
    result = await crawl(max_response_bytes=limit)
    assert ("max_response_bytes" in result) if limit == 1 else result == "ok"
    assert stream.closed


async def test_client_close_failure_returns_permit(monkeypatch):
    original_client = httpx.AsyncClient
    clients = []

    class Client(original_client):
        async def aclose(self):
            await super().aclose()
            if self is clients[0]:
                raise RuntimeError("client close failed")

    def client(**kwargs):
        result = Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, text="ok")), trust_env=False)
        clients.append(result)
        return result

    monkeypatch.setattr(httpx, "AsyncClient", client)
    assert "client close failed" in await crawl()
    assert await crawl() == "ok"
