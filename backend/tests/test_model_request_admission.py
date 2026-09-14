"""Offline request pacing, queue lifecycle, and model-factory integration."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from deerflow.config.model_config import RequestAdmissionConfig
from deerflow.models import request_admission as admission


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(admission, "monotonic", lambda: now[0])
    return now


def test_pacing_has_no_catch_up_burst(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60))
    assert limiter.acquire(blocking=False)
    assert not limiter.acquire(blocking=False)
    clock[0] = 0.999
    assert not limiter.acquire(blocking=False)
    clock[0] = 1
    assert limiter.acquire(blocking=False)
    clock[0] = 100
    assert limiter.acquire(blocking=False)
    assert not limiter.acquire(blocking=False)


def test_high_rpm_wait_tracks_next_admission(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=6000))
    limiter.acquire()
    assert limiter._delay(300) == pytest.approx(0.01)
    clock[0] = 0.009
    assert limiter._delay(300) == pytest.approx(0.001)
    clock[0] = 0.02
    # A non-head waiter must yield, rather than spin on an overdue schedule.
    assert 0 < limiter._delay(300) <= 0.01


@pytest.mark.asyncio
async def test_fifo_cancellation_and_queue_capacity(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60, max_queue_size=2))
    await limiter.aacquire()
    first = asyncio.create_task(limiter.aacquire())
    second = asyncio.create_task(limiter.aacquire())
    await asyncio.sleep(0)
    try:
        with pytest.raises(admission.AdmissionError, match="queue is full"):
            await limiter.aacquire()
        assert not limiter.acquire(blocking=False)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        clock[0] = 1
        assert await asyncio.wait_for(second, 1)
        assert not limiter._waiters
    finally:
        for task in (first, second):
            task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_wait_deadline_does_not_spend_a_permit(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=1, max_wait_seconds=1))
    await limiter.aacquire()
    waiter = asyncio.create_task(limiter.aacquire())
    await asyncio.sleep(0)
    clock[0] = 2
    with pytest.raises(admission.AdmissionError, match="timed out"):
        await asyncio.wait_for(waiter, 1)
    assert not limiter._waiters
    clock[0] = 60
    assert limiter.acquire(blocking=False)


def test_sync_and_foreign_loops_share_one_budget(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=1))
    barrier = threading.Barrier(8)

    def attempt(index):
        barrier.wait(timeout=5)
        return limiter.acquire(blocking=False) if index % 2 else asyncio.run(limiter.aacquire(blocking=False))

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 1


@pytest.mark.parametrize("values", [{"requests_per_minute": 0}, {"requests_per_minute": True}, {"requests_per_minute": 1, "max_wait_seconds": float("inf")}, {"requests_per_minute": 1, "max_queue_size": 0}])
def test_invalid_configuration(values):
    with pytest.raises(ValidationError):
        RequestAdmissionConfig(**values)


def test_sync_timeout_removes_waiter(clock, monkeypatch):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=1, max_wait_seconds=1))
    limiter.acquire()
    monkeypatch.setattr(admission.time, "sleep", lambda _: clock.__setitem__(0, 2))
    with pytest.raises(admission.AdmissionError, match="timed out"):
        limiter.acquire()
    assert not limiter._waiters


@pytest.mark.asyncio
async def test_fifo_prevents_newcomers_overtaking(clock):
    limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60))
    limiter.acquire()
    order = []

    async def wait(index):
        await limiter.aacquire()
        order.append(index)

    first = asyncio.create_task(wait(1))
    second = asyncio.create_task(wait(2))
    await asyncio.sleep(0)
    try:
        clock[0] = 1
        assert not limiter.acquire(blocking=False)
        await asyncio.wait_for(first, 1)
        assert order == [1]
        clock[0] = 2
        await asyncio.wait_for(second, 1)
        assert order == [1, 2]
    finally:
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(admission, "_registry", {})


def test_group_sharing_isolation_and_conflict(registry, clock):
    config = RequestAdmissionConfig(requests_per_minute=60, group="shared")
    a = admission.get_request_admission("a", config)
    assert admission.get_request_admission("b", config) is a
    assert a.acquire(blocking=False)
    assert not admission.get_request_admission("b", config).acquire(blocking=False)
    # An implicit model named 'shared' must not collide with that group.
    b = admission.get_request_admission("shared", RequestAdmissionConfig(requests_per_minute=60))
    assert b.acquire(blocking=False)
    with pytest.raises(ValueError, match="restart"):
        admission.get_request_admission("a", config.model_copy(update={"requests_per_minute": 30}))


def make_model(monkeypatch, *, name="a", policy=None, provider=False):
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig
    from deerflow.models import factory

    model = ModelConfig(name=name, use="langchain_openai:ChatOpenAI", model="test", api_key="offline-test-key", request_admission=policy)
    config = AppConfig(models=[model], sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    if not provider:
        monkeypatch.setattr(factory, "resolve_class", lambda *args: FakeListChatModel)
    return factory.create_chat_model(name, app_config=config, attach_tracing=False, **({} if provider else {"responses": ["ok"]}))


@pytest.mark.asyncio
async def test_factory_invoke_and_stream_share_budget(monkeypatch, registry, clock):
    policy = RequestAdmissionConfig(requests_per_minute=60, group="account")
    a = make_model(monkeypatch, policy=policy)
    b = make_model(monkeypatch, name="b", policy=policy)
    assert a.rate_limiter is b.rate_limiter
    assert a.invoke("hello").content == "ok"
    pending = asyncio.create_task(b.ainvoke("hello"))
    # Drive the normal BaseChatModel pipeline up to admission, not just a mock.
    for _ in range(100):
        if a.rate_limiter._waiters:
            break
        await asyncio.sleep(0)
    try:
        assert a.rate_limiter._waiters
        assert not pending.done()
        clock[0] = 1
        assert (await asyncio.wait_for(pending, 1)).content == "ok"
        clock[0] = 2
        assert "".join(chunk.content for chunk in a.stream("hello")) == "ok"
        assert not a.rate_limiter.acquire(blocking=False)
        clock[0] = 3
        assert "".join([chunk.content async for chunk in b.astream("hello")]) == "ok"
        assert not a.rate_limiter.acquire(blocking=False)
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


def test_real_openai_factory_does_not_forward_policy_or_retry_inside_sdk(monkeypatch, registry):
    model = make_model(monkeypatch, policy=RequestAdmissionConfig(requests_per_minute=30), provider=True)
    assert isinstance(model.rate_limiter, admission.RequestAdmission)
    assert model.max_retries == 0
    assert "request_admission" not in model.model_kwargs
    assert "request_admission" not in model._default_params


def test_disabled_factory_preserves_default(monkeypatch, registry):
    model = make_model(monkeypatch)
    assert model.rate_limiter is None
    assert not admission._registry


def test_admission_failures_are_not_retried_as_provider_errors(monkeypatch):
    from deerflow.agents.middlewares import llm_error_handling_middleware as errors
    from deerflow.config.app_config import AppConfig
    from deerflow.config.sandbox_config import SandboxConfig

    monkeypatch.setattr(errors, "_PROCESS_LIMITER", None)
    monkeypatch.setattr(errors, "_CAP_RESOLVED", False)
    middleware = errors.LLMErrorHandlingMiddleware(app_config=AppConfig(sandbox=SandboxConfig(use="test")))
    for message in (
        "LLM admission queue is full; reduce workload or increase queue capacity.",
        "LLM admission timed out before dispatch; increase max_wait_seconds or reduce workload.",
        "rate limit exceeded locally",
        "provider quota",
        "server busy",
    ):
        retry, _ = middleware._classify_error(admission.AdmissionError(message))
        assert retry is False
