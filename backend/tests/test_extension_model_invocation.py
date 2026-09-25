"""Granted extension calls exercise the loader, service lifecycle and host adapter."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from deerflow_extension_api import (
    ExtensionRuntimeDeps,
    ModelInvocationFailed,
    ModelInvocationRequest,
    ModelInvocationUnauthorized,
    ModelInvocationUnavailable,
    ModelMessage,
    ModelOutputValidationError,
)
from langchain_core.messages import AIMessage

from deerflow.extensions.gateway import start_services, stop_services
from deerflow.extensions.loader import ExtensionSpec, load_extensions


class Service:
    async def start(self, deps):
        self.deps = deps

    async def stop(self):
        pass


@pytest.fixture
def host(monkeypatch):
    from deerflow.extensions import model_invocation

    model = SimpleNamespace(ainvoke=AsyncMock(return_value=AIMessage(content='{"label":"positive"}', usage_metadata={"input_tokens": 8, "output_tokens": 4, "total_tokens": 12})))
    factory = Mock(return_value=model)
    monkeypatch.setattr(model_invocation, "create_chat_model", factory)
    config = SimpleNamespace(get_model_config=lambda name: object() if name == "host-model" else None)

    async def start(grants, *, services_per_install=1, service_type=Service):
        services = []

        def install(registry, config):
            for _ in range(services_per_install):
                service = service_type()
                services.append(service)
                registry.service(service)

        monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", lambda _: install)
        specs = [ExtensionSpec(use="example:install", host_access={"model_invocation": grant} if grant else {}) for grant in grants]
        loaded, diagnostics = load_extensions(specs)
        assert not diagnostics
        diagnostics = await start_services(loaded, config, None)
        return loaded, services, diagnostics

    return SimpleNamespace(start=start, model=model, factory=factory)


GRANT = {"roles": {"default": "host-model"}}
SCHEMA = {"type": "object", "properties": {"label": {"enum": ["positive", "negative"]}}, "required": ["label"]}


def request(**kwargs):
    return ModelInvocationRequest(messages=[ModelMessage("user", "Classify this text")], **kwargs)


def test_old_extension_has_no_capability():
    assert ExtensionRuntimeDeps().model_invoker is None


@pytest.mark.asyncio
async def test_grant_is_bound_to_installation_not_entrypoint(host):
    loaded, services, diagnostics = await host.start([GRANT, None, {"roles": {"fast": "host-model"}}])
    assert not diagnostics
    assert services[1].deps.model_invoker is None
    result = await services[0].deps.model_invoker.invoke(request(response_schema=SCHEMA, purpose="classify"))
    assert result.content == '{"label":"positive"}'
    assert result.structured_output == {"label": "positive"}
    assert result.resolved_model == "host-model"
    assert result.usage.total_tokens == 12
    with pytest.raises(ModelInvocationUnauthorized):
        await services[2].deps.model_invoker.invoke(request())
    assert host.factory.call_count == 1
    metadata = host.model.ainvoke.call_args.kwargs["config"]["metadata"]
    assert metadata["extension_source"] == "example:install"
    assert metadata["extension_purpose"] == "classify"
    messages = host.model.ainvoke.call_args.args[0]
    assert messages[0].type == "system"
    assert '"properties"' not in messages[0].content
    assert messages[-1].type == "human"
    assert '"properties"' in messages[-1].content
    await stop_services(loaded)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["not JSON", '{"label":"unknown"}', "[]", '{"label":"positive", "score":NaN}', '{"label":"positive", "score":1e999}'])
async def test_schema_failure_never_returns_success(host, content):
    host.model.ainvoke.return_value = AIMessage(content=content)
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelOutputValidationError):
        await services[0].deps.model_invoker.invoke(request(response_schema=SCHEMA))
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_provider_errors_do_not_expose_credentials(host):
    host.model.ainvoke.side_effect = RuntimeError("secret-key in provider URL")
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelInvocationFailed) as error:
        await services[0].deps.model_invoker.invoke(request())
    assert "secret-key" not in str(error.value)
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_missing_model_and_disallowed_role_fail_before_provider(host):
    loaded, services, _ = await host.start([{"roles": {"default": "missing"}}])
    with pytest.raises(ModelInvocationUnavailable):
        await services[0].deps.model_invoker.invoke(request())
    with pytest.raises(ModelInvocationUnauthorized):
        await services[0].deps.model_invoker.invoke(request(model_role="host-model"))
    host.factory.assert_not_called()
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_concurrency_shared_across_services_and_queue_timeout(host):
    started = asyncio.Event()
    release = asyncio.Event()

    async def invoke(*args, **kwargs):
        started.set()
        await release.wait()
        return AIMessage(content="ok")

    host.model.ainvoke.side_effect = invoke
    loaded, services, _ = await host.start([{**GRANT, "max_concurrency": 1}], services_per_install=2)
    first = asyncio.create_task(services[0].deps.model_invoker.invoke(request()))
    await started.wait()
    with pytest.raises(ModelInvocationFailed, match="timed out"):
        await services[1].deps.model_invoker.invoke(request(timeout_seconds=0.01))
    assert host.model.ainvoke.call_count == 1
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert (await services[1].deps.model_invoker.invoke(request())).content == "ok"
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_stop_revokes_retained_capability_and_cancels_inflight(host):
    started = asyncio.Event()
    release = asyncio.Event()

    async def invoke(*args, **kwargs):
        started.set()
        await release.wait()

    host.model.ainvoke.side_effect = invoke
    loaded, services, _ = await host.start([GRANT])
    invoker = services[0].deps.model_invoker
    task = asyncio.create_task(invoker.invoke(request()))
    await started.wait()
    await stop_services(loaded)
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(ModelInvocationUnavailable):
        await invoker.invoke(request())
    release.set()
    await asyncio.gather(*invoker._budget.workers)


@pytest.mark.asyncio
async def test_start_failure_revokes_only_failed_service(host):
    class Broken(Service):
        async def start(self, deps):
            await super().start(deps)
            raise ValueError("broken")

    instances = iter([Broken(), Service()])
    loaded, services, diagnostics = await host.start([GRANT], services_per_install=2, service_type=instances.__next__)
    assert len(diagnostics) == 1
    with pytest.raises(ModelInvocationUnavailable):
        await services[0].deps.model_invoker.invoke(request())
    assert (await services[1].deps.model_invoker.invoke(request())).content == '{"label":"positive"}'
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_doc_classification_example_uses_public_contract(host):
    from pathlib import Path

    doc = (Path(__file__).resolve().parents[1] / "docs" / "extension-model-invocation.md").read_text(encoding="utf-8")
    code = doc.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(code, "extension-model-invocation.md", "exec"), namespace)
    loaded, services, _ = await host.start([GRANT], service_type=namespace["Classifier"])
    assert await services[0].classify("Excellent work") == "positive"
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_real_host_factory_preserves_tracing_and_text_contract(monkeypatch):
    from langchain_core.callbacks import BaseCallbackHandler

    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.config.sandbox_config import SandboxConfig

    traces = []

    class Observer(BaseCallbackHandler):
        def on_chat_model_start(self, serialized, messages, **kwargs):
            traces.append(kwargs["metadata"])

    config = AppConfig(
        models=[ModelConfig(name="host-model", model="fake", use="langchain_core.language_models.fake_chat_models:FakeListChatModel", responses=['{"label":"negative"}'])],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
    )
    service = Service()
    monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", lambda _: lambda registry, _: registry.service(service))
    monkeypatch.setattr("deerflow.models.factory.build_tracing_callbacks", lambda: [Observer()])
    loaded, diagnostics = load_extensions([ExtensionSpec(use="real:install", host_access={"model_invocation": GRANT})])
    assert not diagnostics
    assert not await start_services(loaded, config, None)
    result = await service.deps.model_invoker.invoke(request(response_schema=SCHEMA))
    assert result.structured_output == {"label": "negative"}
    assert traces[0]["extension_source"] == "real:install"
    await stop_services(loaded)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object", "properties": {"x": {"$ref": "https://example.com/schema"}}},
        {"type": "object", "$ref": "#/properties/x"},
        {"type": "array"},
        {"type": "object", "required": "label"},
        {"type": "object", "$schema": "http://json-schema.org/draft-07/schema#"},
    ],
)
async def test_invalid_schema_rejected_without_provider_call(host, schema):
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelInvocationFailed):
        await services[0].deps.model_invoker.invoke(request(response_schema=schema))
    host.factory.assert_not_called()
    await stop_services(loaded)


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), True, "60"])
async def test_invalid_timeout_rejected_before_provider(host, timeout):
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelInvocationFailed):
        await services[0].deps.model_invoker.invoke(request(timeout_seconds=timeout))
    host.factory.assert_not_called()
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_host_timeout_caps_request_and_preserves_running_provider(host):
    cancelled = asyncio.Event()
    release = asyncio.Event()

    async def invoke(*args, **kwargs):
        try:
            await release.wait()
        finally:
            cancelled.set()

    host.model.ainvoke.side_effect = invoke
    loaded, services, _ = await host.start([{**GRANT, "timeout_seconds": 0.05}])
    with pytest.raises(ModelInvocationFailed, match="timed out"):
        await services[0].deps.model_invoker.invoke(request(timeout_seconds=500))
    assert not cancelled.is_set()
    release.set()
    await asyncio.wait_for(cancelled.wait(), 1)
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_input_and_output_limits(host):
    loaded, services, _ = await host.start([{**GRANT, "max_input_chars": 5, "max_output_chars": 2}])
    invoker = services[0].deps.model_invoker
    with pytest.raises(ModelInvocationFailed, match="input"):
        await invoker.invoke(request())
    host.factory.assert_not_called()
    with pytest.raises(ModelInvocationFailed, match="output"):
        await invoker.invoke(ModelInvocationRequest([ModelMessage("user", "hi")]))
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_text_blocks_project_without_provider_metadata(host):
    host.model.ainvoke.return_value = AIMessage(content=[{"type": "text", "text": "hello"}, {"type": "text", "text": " world"}], response_metadata={"secret": "hidden"})
    loaded, services, _ = await host.start([GRANT])
    result = await services[0].deps.model_invoker.invoke(request())
    assert result.content == "hello world"
    assert result.usage is None
    assert "hidden" not in repr(result)
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_tool_calls_rejected(host):
    host.model.ainvoke.return_value = AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "call"}])
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelInvocationFailed, match="Tool-call"):
        await services[0].deps.model_invoker.invoke(request())
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_failed_duplicate_install_does_not_grant_prior_service(monkeypatch):
    good = Service()
    failed = Service()

    def install(registry, config):
        registry.service(failed if config else good)
        if config:
            raise RuntimeError("install failed after registration")

    monkeypatch.setattr("deerflow.extensions.loader.resolve_variable", lambda _: install)
    loaded, diagnostics = load_extensions(
        [
            ExtensionSpec(use="same:install"),
            ExtensionSpec(use="same:install", config={"fail": True}, host_access={"model_invocation": GRANT}),
        ]
    )
    assert len(diagnostics) == 1
    assert len(loaded.services) == 1
    await start_services(loaded, SimpleNamespace(), None)
    assert good.deps.model_invoker is None
    assert not hasattr(failed, "deps")
    await stop_services(loaded)


@pytest.mark.parametrize("grant", [{"roles": {}}, {"roles": {"default": " "}}, {"roles": {"": "model"}}, {**GRANT, "max_concurrency": 0}, {**GRANT, "timeout_seconds": float("inf")}])
def test_invalid_grants_rejected(grant):
    with pytest.raises(ValueError):
        ExtensionSpec(use="example:install", host_access={"model_invocation": grant})


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["timeout", "cancel", "stop"])
async def test_sync_provider_retains_slot_until_thread_finishes(host, exit_kind):
    import threading

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult

    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    calls = []

    class SyncModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "blocked-sync-test"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            calls.append(1)
            loop.call_soon_threadsafe(started.set)
            assert release.wait(10)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    host.factory.return_value = SyncModel()
    loaded, services, _ = await host.start([{**GRANT, "max_concurrency": 1}], services_per_install=2)
    invoker = services[0].deps.model_invoker
    first = asyncio.create_task(invoker.invoke(request(timeout_seconds=0.1 if exit_kind == "timeout" else 5)))
    try:
        await asyncio.wait_for(started.wait(), 3)
        if exit_kind == "cancel":
            first.cancel()
        elif exit_kind == "stop":
            invoker.close()
        with pytest.raises(ModelInvocationFailed if exit_kind == "timeout" else asyncio.CancelledError):
            await first
        with pytest.raises(ModelInvocationFailed, match="timed out"):
            await services[1].deps.model_invoker.invoke(request(timeout_seconds=0.05))
        assert len(calls) == 1, "timed-out synchronous requests still consume their concurrency slot"
    finally:
        release.set()
        await asyncio.gather(first, return_exceptions=True)
    assert (await services[1].deps.model_invoker.invoke(request())).content == "ok"
    await stop_services(loaded)


@pytest.mark.asyncio
async def test_admission_limit_shared_and_rejects_before_payload_processing(host):
    started = asyncio.Event()
    release = asyncio.Event()

    async def invoke(*args, **kwargs):
        started.set()
        await release.wait()
        return AIMessage(content="ok")

    host.model.ainvoke.side_effect = invoke
    loaded, services, _ = await host.start([{**GRANT, "max_concurrency": 1}], services_per_install=2)
    first = asyncio.create_task(services[0].deps.model_invoker.invoke(request()))
    await started.wait()
    queued = asyncio.create_task(services[1].deps.model_invoker.invoke(request()))
    await asyncio.sleep(0)
    try:
        with pytest.raises(ModelInvocationFailed, match="capacity"):
            await services[0].deps.model_invoker.invoke(request(timeout_seconds=0.05))
        assert host.factory.call_count == 1
    finally:
        release.set()
        await asyncio.gather(first, queued)
        await stop_services(loaded)


@pytest.mark.asyncio
async def test_provider_timeout_is_not_reported_as_host_deadline(host):
    host.model.ainvoke.side_effect = TimeoutError("secret provider URL")
    loaded, services, _ = await host.start([GRANT])
    with pytest.raises(ModelInvocationFailed, match="provider timed out") as error:
        await services[0].deps.model_invoker.invoke(request())
    assert error.value.__context__ is None
    assert "secret" not in str(error.value)
    await stop_services(loaded)


@pytest.mark.asyncio
@pytest.mark.parametrize("self_cancel", [False, True])
@pytest.mark.parametrize("prior_cancellation", [False, True])
async def test_provider_cancellation_is_normalized_and_releases_capacity(host, self_cancel, prior_cancellation):
    async def cancelled_provider(*args, **kwargs):
        if self_cancel:
            asyncio.current_task().cancel("secret provider detail")
            await asyncio.sleep(0)
        raise asyncio.CancelledError("secret provider detail")

    host.model.ainvoke.side_effect = cancelled_provider
    loaded, services, _ = await host.start([{**GRANT, "max_concurrency": 1}])
    invoker = services[0].deps.model_invoker

    async def caller():
        if prior_cancellation:
            asyncio.current_task().cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass  # A previously handled request must not mask provider failure.
        with pytest.raises(ModelInvocationFailed, match="provider cancelled") as error:
            await invoker.invoke(request())
        assert error.value.__cause__ is None
        assert error.value.__context__ is None
        assert "secret" not in str(error.value)
        assert invoker._budget.admitted == 0
        host.model.ainvoke.side_effect = None
        assert (await invoker.invoke(request())).content == '{"label":"positive"}'

    try:
        await asyncio.create_task(caller())
    finally:
        await stop_services(loaded)


@pytest.mark.asyncio
async def test_caller_cancellation_wins_when_provider_also_cancels(host):
    async def cancelled_provider(*args, **kwargs):
        caller.cancel()
        raise asyncio.CancelledError("provider cancelled too")

    host.model.ainvoke.side_effect = cancelled_provider
    loaded, services, _ = await host.start([GRANT])
    invoker = services[0].deps.model_invoker
    caller = asyncio.create_task(invoker.invoke(request()))
    try:
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert caller.cancelled()
        assert invoker._budget.admitted == 0
    finally:
        await stop_services(loaded)


@pytest.mark.asyncio
async def test_pending_caller_cancellation_at_invocation_entry_propagates(host):
    loaded, services, _ = await host.start([GRANT])
    invoker = services[0].deps.model_invoker

    async def caller():
        asyncio.current_task().cancel()
        await invoker.invoke(request())

    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.create_task(caller())
    finally:
        await asyncio.gather(*invoker._budget.workers, return_exceptions=True)
        await stop_services(loaded)
    assert invoker._budget.admitted == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_kind", ["timeout", "cancel", "stop"])
async def test_validation_deadline_does_not_block_event_loop(host, monkeypatch, exit_kind):
    import time

    from deerflow.extensions import model_invocation

    processes = []
    popen = model_invocation.subprocess.Popen

    def track_process(*args, **kwargs):
        process = popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(model_invocation.subprocess, "Popen", track_process)
    schema = {"type": "object", "properties": {"value": {"type": "string", "pattern": "^(a+)+$"}}}
    host.model.ainvoke.return_value = AIMessage(content='{"value":"' + "a" * 30 + '!"}')
    loaded, services, _ = await host.start([GRANT])
    ticks = []
    running = True

    async def heartbeat():
        while running:
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    ticker = asyncio.create_task(heartbeat())
    invoker = services[0].deps.model_invoker
    task = asyncio.create_task(invoker.invoke(request(response_schema=schema, timeout_seconds=3)))
    try:
        if exit_kind != "timeout":
            async with asyncio.timeout(3):
                while len(processes) < 2:
                    await asyncio.sleep(0.01)
            if exit_kind == "cancel":
                task.cancel()
                # Repeated cancellation must not abandon the child cleanup.
                asyncio.get_running_loop().call_later(0.01, task.cancel)
            else:
                invoker.close()
        with pytest.raises(ModelInvocationFailed if exit_kind == "timeout" else asyncio.CancelledError):
            await task
        assert host.model.ainvoke.call_count == 1, "deadline must fire during response validation"
        ticks.append(time.monotonic())
        assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.3
        assert len(processes) == 2
        assert all(process.poll() is not None for process in processes)
        assert invoker._budget.admitted == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        running = False
        await ticker
        await stop_services(loaded)


@pytest.mark.asyncio
async def test_cancelled_constructor_retains_slot_and_never_dispatches(host):
    import threading

    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def factory(*args, **kwargs):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        return host.model

    host.factory.side_effect = factory
    loaded, services, _ = await host.start([{**GRANT, "max_concurrency": 1}])
    invoker = services[0].deps.model_invoker
    first = asyncio.create_task(invoker.invoke(request()))
    try:
        await asyncio.wait_for(started.wait(), 3)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        with pytest.raises(ModelInvocationFailed, match="timed out"):
            await invoker.invoke(request(timeout_seconds=0.05))
        assert host.factory.call_count == 1
    finally:
        release.set()
        await asyncio.gather(*invoker._budget.workers, return_exceptions=True)
        await stop_services(loaded)
    host.model.ainvoke.assert_not_called()
