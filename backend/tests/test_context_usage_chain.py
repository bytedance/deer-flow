"""The lead chain records context composition before system-message coalescing."""

from __future__ import annotations

from types import SimpleNamespace

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, SystemMessage

from deerflow.agents.lead_agent.agent import build_middlewares
from deerflow.agents.middlewares.context_usage_middleware import CONTEXT_USAGE_KEY, ContextUsageMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig


def _stack(*, token_usage_enabled: bool = True, context_window: int | None = None):
    config = AppConfig(sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"))
    config.title.enabled = config.memory.enabled = config.summarization.enabled = False
    config.token_usage.enabled = token_usage_enabled
    config.models = [ModelConfig(name="offline", use="langchain_openai.ChatOpenAI", model="offline", context_window=context_window)]
    config._build_name_indexes()
    return build_middlewares(
        config={"configurable": {}},
        model_name="offline",
        app_config=config,
        memory_enabled=False,
        owns_agent_skill_projection=False,
    )


def test_context_usage_middleware_is_installed_before_coalescing() -> None:
    names = [type(middleware).__name__ for middleware in _stack()]

    assert "ContextUsageMiddleware" in names
    assert names.index("ContextUsageMiddleware") < names.index("SystemMessageCoalescingMiddleware")
    # It must observe the request after the dynamic/durable-context producers.
    assert names.index("DynamicContextMiddleware") < names.index("ContextUsageMiddleware")
    assert names.index("DurableContextMiddleware") < names.index("ContextUsageMiddleware")


def test_context_usage_middleware_follows_the_token_usage_switch() -> None:
    names = [type(middleware).__name__ for middleware in _stack(token_usage_enabled=False)]

    assert "ContextUsageMiddleware" not in names


def test_context_usage_middleware_receives_the_model_capacity() -> None:
    stack = _stack(context_window=64000)
    middleware = next(item for item in stack if isinstance(item, ContextUsageMiddleware))
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})
    request = ModelRequest(
        model=SimpleNamespace(),
        messages=[],
        system_message=SystemMessage(content="prompt"),
        tools=[],
        state={"messages": []},
        runtime=runtime,
    )

    returned = middleware.wrap_model_call(request, lambda _request: ModelResponse(result=[AIMessage(content="done", id="ai-1")]))

    snapshot = returned.result[0].additional_kwargs[CONTEXT_USAGE_KEY]
    assert snapshot["context_window"] == 64000
    assert snapshot["model_name"] == "offline"
    assert middleware.release_policy_parameters()["snapshot_version"] == 1


def test_context_usage_middleware_registers_no_after_model_node() -> None:
    """LangChain gives every middleware that overrides ``after_model`` its own
    graph node, and each node execution emits an extra ``values`` SSE event per
    model call. That drifted the replay golden, so the stamp must ride the model
    node's own response instead.
    """
    assert ContextUsageMiddleware.after_model is AgentMiddleware.after_model
    assert ContextUsageMiddleware.aafter_model is AgentMiddleware.aafter_model
