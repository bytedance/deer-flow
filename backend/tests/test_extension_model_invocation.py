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

    async def invoke(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

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
async def test_host_timeout_caps_request_and_cancels_provider(host):
    cancelled = asyncio.Event()

    async def invoke(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    host.model.ainvoke.side_effect = invoke
    loaded, services, _ = await host.start([{**GRANT, "timeout_seconds": 0.05}])
    with pytest.raises(ModelInvocationFailed, match="timed out"):
        await services[0].deps.model_invoker.invoke(request(timeout_seconds=500))
    assert cancelled.is_set()
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
