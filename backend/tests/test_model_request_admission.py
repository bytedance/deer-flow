"""Offline request pacing, queue lifecycle, and model-factory integration."""

import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import yaml
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


@pytest.mark.parametrize(
    "values",
    [
        {"requests_per_minute": "60"},
        {"requests_per_minute": " 60 "},
        {"requests_per_minute": 1, "max_queue_size": "512"},
    ],
)
def test_integer_literal_strings_are_accepted(values):
    """``$VAR`` substitution always yields ``str``; an integer literal must still validate."""
    config = RequestAdmissionConfig(**values)
    assert config.requests_per_minute == int(str(values["requests_per_minute"]).strip())
    assert config.max_queue_size == int(str(values.get("max_queue_size", 256)).strip())
    assert type(config.requests_per_minute) is int
    assert type(config.max_queue_size) is int


@pytest.mark.parametrize(
    "values",
    [
        {"requests_per_minute": 60.0},
        {"requests_per_minute": "60.0"},
        {"requests_per_minute": "sixty"},
        {"requests_per_minute": ""},
        {"requests_per_minute": "0"},
        {"requests_per_minute": 1, "max_queue_size": True},
        {"requests_per_minute": 1, "max_queue_size": 256.0},
        {"requests_per_minute": 1, "max_queue_size": "-1"},
    ],
)
def test_non_integer_inputs_remain_rejected(values):
    """Accepting env-substituted integer strings must not reopen the strict check for bools, floats, or other strings."""
    with pytest.raises(ValidationError):
        RequestAdmissionConfig(**values)


def test_env_substitution_reaches_request_admission_from_config_file(monkeypatch, tmp_path):
    """``config.example.yaml`` promises ``$VAR`` for every field; the two strict integers must honor it end to end."""
    from deerflow.config.app_config import AppConfig

    monkeypatch.setenv("DEER_FLOW_TEST_RPM", "60")
    monkeypatch.setenv("DEER_FLOW_TEST_QUEUE", "512")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "models": [
                    {
                        "name": "paced",
                        "use": "langchain_openai:ChatOpenAI",
                        "model": "gpt-test",
                        "request_admission": {"requests_per_minute": "$DEER_FLOW_TEST_RPM", "max_queue_size": "$DEER_FLOW_TEST_QUEUE"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    policy = AppConfig.from_file(str(path)).get_model_config("paced").request_admission

    assert policy == RequestAdmissionConfig(requests_per_minute=60, max_queue_size=512)


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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [429, 500])
async def test_claude_admission_does_not_retry_inside_provider(registry, mode, status):
    import anthropic
    import httpx

    from deerflow.config.app_config import AppConfig
    from deerflow.models.factory import create_chat_model

    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {
                    "name": "claude-paced",
                    "use": "deerflow.models.claude_provider:ClaudeChatModel",
                    "model": "claude-sonnet-4-6",
                    "api_key": "offline-test-key",
                    "request_admission": {"requests_per_minute": 1, "max_wait_seconds": 0.01},
                    "retry_max_attempts": 7,
                    "max_retries": 7,
                }
            ],
        }
    )
    model = create_chat_model("claude-paced", app_config=config, attach_tracing=False, retry_max_attempts=5, max_retries=5)
    calls = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, headers={"retry-after": "0"}, json={"type": "error", "error": {"type": "rate_limit_error" if status == 429 else "api_error", "message": "synthetic error"}})
        return httpx.Response(
            200,
            json={
                "id": "msg-synthetic",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "unexpected retry"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    error = anthropic.RateLimitError if status == 429 else anthropic.InternalServerError
    if mode == "sync":
        with httpx.Client(transport=httpx.MockTransport(respond)) as client:
            model._client._client = client
            with pytest.raises(error):
                model.invoke("hello")
    else:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            model._async_client._client = client
            with pytest.raises(error):
                await model.ainvoke("hello")
    assert len(calls) == 1
    assert model.max_retries == 0
    assert model.retry_max_attempts == 1
    assert config.get_model_config("claude-paced").retry_max_attempts == 7


@pytest.mark.parametrize("kwargs,attempts", [({}, 3), ({"retry_max_attempts": 7}, 7)])
def test_claude_without_admission_preserves_wrapper_retries(kwargs, attempts):
    from deerflow.models.claude_provider import ClaudeChatModel

    model = ClaudeChatModel(model="claude-sonnet-4-6", api_key="offline-test-key", **kwargs)
    assert model.retry_max_attempts == attempts


def test_claude_custom_rate_limiter_preserves_wrapper_retries():
    from langchain_core.rate_limiters import InMemoryRateLimiter

    from deerflow.models.claude_provider import ClaudeChatModel

    model = ClaudeChatModel(model="claude-sonnet-4-6", api_key="offline-test-key", rate_limiter=InMemoryRateLimiter(), retry_max_attempts=7)
    assert model.retry_max_attempts == 7


@pytest.fixture
def codex_credentials(monkeypatch):
    from deerflow.models import openai_codex_provider as provider
    from deerflow.models.credential_loader import CodexCliCredential

    monkeypatch.setattr(provider, "load_codex_cli_credential", lambda: CodexCliCredential("offline-test-token", "offline-test-account"))


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("status", [429, 500, 529])
@pytest.mark.parametrize("enabled", [False, True])
async def test_codex_factory_retry_policy_respects_admission(monkeypatch, registry, codex_credentials, mode, status, enabled):
    import httpx

    from deerflow.config.app_config import AppConfig
    from deerflow.models import openai_codex_provider as provider
    from deerflow.models.factory import create_chat_model

    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "models": [
                {
                    "name": "codex-paced",
                    "use": "deerflow.models.openai_codex_provider:CodexChatModel",
                    "model": "gpt-5.4",
                    "request_admission": {"requests_per_minute": 1, "max_wait_seconds": 0.01} if enabled else None,
                    "retry_max_attempts": 7,
                }
            ],
        }
    )
    model = create_chat_model("codex-paced", app_config=config, attach_tracing=False, retry_max_attempts=5)
    calls = []
    sleeps = []

    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, json={"error": "synthetic error"})
        event = {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "unexpected retry"}]}], "usage": {}}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {json.dumps(event)}\n\n")

    client_class = httpx.Client
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(provider.time, "sleep", sleeps.append)

    if enabled:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            if mode == "sync":
                model.invoke("hello")
            else:
                await model.ainvoke("hello")
        assert caught.value.response.status_code == status
        assert len(calls) == 1
        assert sleeps == []
        assert isinstance(model.rate_limiter, admission.RequestAdmission)
        assert model.retry_max_attempts == 1
    else:
        result = model.invoke("hello") if mode == "sync" else await model.ainvoke("hello")
        assert result.content == "unexpected retry"
        assert len(calls) == 2
        assert len(sleeps) == 1
        assert model.rate_limiter is None
        assert model.retry_max_attempts == 5
    assert config.get_model_config("codex-paced").retry_max_attempts == 7


def test_codex_without_admission_preserves_default_retries(codex_credentials):
    from deerflow.models.openai_codex_provider import CodexChatModel

    assert CodexChatModel().retry_max_attempts == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["sync", "async"])
@pytest.mark.parametrize("reason_phrase", [b"", b"Upstream error"])
async def test_codex_529_middleware_retry_reenters_admission(monkeypatch, registry, clock, codex_credentials, mode, reason_phrase):
    import httpx
    from langchain.agents import create_agent

    from deerflow.agents.middlewares import llm_error_handling_middleware as errors
    from deerflow.config.app_config import AppConfig
    from deerflow.models import openai_codex_provider as provider
    from deerflow.models.factory import create_chat_model

    monkeypatch.setattr(errors, "_PROCESS_LIMITER", None)
    monkeypatch.setattr(errors, "_CAP_RESOLVED", False)
    config = AppConfig.model_validate(
        {
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "llm_call": {"retry_max_attempts": 2, "retry_base_delay_ms": 25, "retry_cap_delay_ms": 25},
            "models": [
                {
                    "name": "codex-paced",
                    "use": "deerflow.models.openai_codex_provider:CodexChatModel",
                    "model": "gpt-5.4",
                    "request_admission": {"requests_per_minute": 60, "max_wait_seconds": 2},
                }
            ],
        }
    )
    model = create_chat_model("codex-paced", app_config=config, attach_tracing=False)
    calls = []
    sleeps = []

    def respond(request):
        calls.append(clock[0])
        if len(calls) == 1:
            # HTTPStatusError omits this body; retry must recognize the status
            # even when the reason phrase carries no overload/busy wording.
            return httpx.Response(529, extensions={"reason_phrase": reason_phrase}, json={"error": "overloaded"})
        event = {"type": "response.completed", "response": {"output": [{"type": "message", "content": [{"type": "output_text", "text": "recovered"}]}], "usage": {}}}
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=f"data: {json.dumps(event)}\n\n")

    def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    real_async_sleep = asyncio.sleep

    async def async_sleep(delay):
        sleep(delay)
        await real_async_sleep(0)

    client_class = httpx.Client
    monkeypatch.setattr(provider.httpx, "Client", lambda **kwargs: client_class(transport=httpx.MockTransport(respond), **kwargs))
    monkeypatch.setattr(provider.time, "sleep", sleep)
    monkeypatch.setattr(asyncio, "sleep", async_sleep)
    agent = create_agent(model=model, tools=[], middleware=[errors.LLMErrorHandlingMiddleware(app_config=config)])
    inputs = {"messages": [{"role": "user", "content": "hello"}]}
    result = agent.invoke(inputs) if mode == "sync" else await agent.ainvoke(inputs)

    assert result["messages"][-1].content == "recovered"
    assert model.retry_max_attempts == 1
    # Middleware's 25ms backoff alone cannot satisfy the one-second pacing
    # interval: the second HTTP attempt must also wait for admission.
    assert calls == pytest.approx([0, 1])
    assert sleeps[0] == pytest.approx(0.025)
    assert len(sleeps) > 1
    assert all(0 <= delay <= 0.05 for delay in sleeps)


@pytest.mark.parametrize("provider", ["claude", "codex"])
@pytest.mark.parametrize("limiter_kind", ["admission", "custom", "none"])
@pytest.mark.parametrize("attempts", [1, 7])
def test_provider_warns_only_when_admission_overrides_retries(codex_credentials, caplog, provider, limiter_kind, attempts):
    from langchain_core.rate_limiters import InMemoryRateLimiter

    from deerflow.models.claude_provider import ClaudeChatModel
    from deerflow.models.openai_codex_provider import CodexChatModel

    limiter = None
    if limiter_kind == "admission":
        limiter = admission.RequestAdmission(RequestAdmissionConfig(requests_per_minute=60))
    elif limiter_kind == "custom":
        limiter = InMemoryRateLimiter()

    model_class = ClaudeChatModel if provider == "claude" else CodexChatModel
    kwargs = {"model": "claude-sonnet-4-6", "api_key": "offline-test-key"} if provider == "claude" else {}
    logger_name = model_class.__module__
    with caplog.at_level(logging.WARNING, logger=logger_name):
        model = model_class(rate_limiter=limiter, retry_max_attempts=attempts, **kwargs)

    assert model.retry_max_attempts == (1 if limiter_kind == "admission" else attempts)
    if limiter_kind == "admission" and attempts != 1:
        assert caplog.record_tuples == [(logger_name, logging.WARNING, f"Request admission enabled; ignoring configured retry_max_attempts={attempts}; provider retries are handled by middleware")]
    else:
        assert caplog.record_tuples == []


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
