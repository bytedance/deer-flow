"""Tests for Phase 1B tool authorization enforcement."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import StructuredTool

from deerflow.agents.lead_agent import agent as lead_agent_module
from deerflow.agents.middlewares.tool_error_handling_middleware import (
    build_lead_runtime_middlewares,
    build_subagent_runtime_middlewares,
)
from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.enforcement import filter_tools_by_authorization
from deerflow.authz.provider import AuthzDecision, AuthzReason, Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.guardrails_config import GuardrailProviderConfig, GuardrailsConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.tools.builtins.tool_search import assemble_deferred_tools
from deerflow.tools.mcp_metadata import tag_mcp_tool


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(lambda: name, name=name, description=name)


class _FilterProvider:
    name = "filter"

    def __init__(self, allowed: list[str]) -> None:
        self.allowed = allowed
        self.calls: list[tuple[Principal, str, list[str]]] = []

    def authorize(self, request):
        return AuthzDecision(allow=True)

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        self.calls.append((principal, resource_type, candidates))
        return [candidate for candidate in candidates if candidate in self.allowed]


class _ExplodingFilterProvider(_FilterProvider):
    def __init__(self) -> None:
        super().__init__([])

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        raise RuntimeError("provider failed")


def _app_config(
    *,
    authorization: AuthorizationConfig,
    guardrails: GuardrailsConfig | None = None,
    models: list[ModelConfig] | None = None,
) -> AppConfig:
    return AppConfig(
        models=models or [],
        sandbox=SandboxConfig(use="test"),
        authorization=authorization,
        guardrails=guardrails or GuardrailsConfig(),
    )


class TestAuthorizationToolFilter:
    def test_keeps_only_provider_allowed_tools_and_preserves_input_order(self):
        provider = _FilterProvider(["web_search", "read_file"])
        tools = [_tool("bash"), _tool("web_search"), _tool("read_file")]

        filtered = filter_tools_by_authorization(
            tools,
            provider=provider,
            principal=Principal(role="user"),
            fail_closed=True,
        )

        assert [tool.name for tool in filtered] == ["web_search", "read_file"]
        assert provider.calls == [(Principal(role="user"), "tool", ["bash", "web_search", "read_file"])]

    def test_provider_error_fails_closed_to_an_empty_tool_set(self):
        tools = [_tool("bash"), _tool("web_search")]

        filtered = filter_tools_by_authorization(
            tools,
            provider=_ExplodingFilterProvider(),
            principal=Principal(role="user"),
            fail_closed=True,
        )

        assert filtered == []

    def test_provider_error_fails_open_only_when_configured(self):
        tools = [_tool("bash"), _tool("web_search")]

        filtered = filter_tools_by_authorization(
            tools,
            provider=_ExplodingFilterProvider(),
            principal=Principal(role="user"),
            fail_closed=False,
        )

        assert filtered == tools

    @pytest.mark.parametrize("invalid_result", ["bash", ("bash",), ["bash", 1]])
    def test_invalid_provider_result_fails_closed(self, invalid_result):
        class _InvalidResultProvider(_FilterProvider):
            def filter_resources(self, principal, resource_type, candidates):
                return invalid_result

        filtered = filter_tools_by_authorization(
            [_tool("bash")],
            provider=_InvalidResultProvider([]),
            principal=Principal(role="user"),
            fail_closed=True,
        )

        assert filtered == []

    def test_provider_cannot_add_tools_outside_the_candidate_set(self):
        class _InjectingProvider(_FilterProvider):
            def filter_resources(self, principal, resource_type, candidates):
                return [*candidates, "injected_tool"]

        filtered = filter_tools_by_authorization(
            [_tool("bash")],
            provider=_InjectingProvider([]),
            principal=Principal(role="user"),
            fail_closed=True,
        )

        assert [tool.name for tool in filtered] == ["bash"]


class TestAuthorizationGuardrailWiring:
    def test_deferred_tool_search_bypasses_layer_two_for_filtered_catalog(self):
        provider = RbacAuthorizationProvider(roles={"guest": {"tools": {"allow": ["mcp_allowed"]}}})
        filtered_tools = filter_tools_by_authorization(
            [tag_mcp_tool(_tool("mcp_allowed"))],
            provider=provider,
            principal=Principal(role="guest"),
            fail_closed=True,
        )
        _final_tools, deferred_setup = assemble_deferred_tools(filtered_tools, enabled=True)
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                default_role="guest",
                provider=AuthorizationProviderConfig(use="unused:Provider"),
            )
        )

        middlewares = build_lead_runtime_middlewares(
            app_config=config,
            authorization_provider=provider,
            deferred_setup=deferred_setup,
        )
        authorization_middleware = next(middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware) and isinstance(middleware.provider, GuardrailAuthorizationAdapter))
        request = MagicMock()
        request.tool_call = {
            "name": "tool_search",
            "args": {"query": "mcp_allowed"},
            "id": "call-search",
        }
        request.runtime = SimpleNamespace(context={"user_role": "guest"})
        expected = MagicMock()
        handler = MagicMock(return_value=expected)

        result = authorization_middleware.wrap_tool_call(request, handler)

        assert result is expected
        handler.assert_called_once_with(request)

    def test_tool_search_without_deferred_catalog_is_not_exempt(self):
        provider = RbacAuthorizationProvider(roles={"guest": {"tools": {"allow": ["web_search"]}}})
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                default_role="guest",
                provider=AuthorizationProviderConfig(use="unused:Provider"),
            )
        )
        middlewares = build_lead_runtime_middlewares(
            app_config=config,
            authorization_provider=provider,
        )
        authorization_middleware = next(middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware) and isinstance(middleware.provider, GuardrailAuthorizationAdapter))
        request = MagicMock()
        request.tool_call = {"name": "tool_search", "args": {}, "id": "call-search"}
        request.runtime = SimpleNamespace(context={"user_role": "guest"})
        handler = MagicMock()

        result = authorization_middleware.wrap_tool_call(request, handler)

        assert result.status == "error"
        handler.assert_not_called()

    def test_subagent_deferred_tool_search_bypasses_layer_two_async(self):
        provider = RbacAuthorizationProvider(roles={"guest": {"tools": {"allow": ["mcp_allowed"]}}})
        filtered_tools = filter_tools_by_authorization(
            [tag_mcp_tool(_tool("mcp_allowed"))],
            provider=provider,
            principal=Principal(role="guest"),
            fail_closed=True,
        )
        _final_tools, deferred_setup = assemble_deferred_tools(filtered_tools, enabled=True)
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                default_role="guest",
                provider=AuthorizationProviderConfig(use="unused:Provider"),
            )
        )
        middlewares = build_subagent_runtime_middlewares(
            app_config=config,
            authorization_provider=provider,
            deferred_setup=deferred_setup,
        )
        authorization_middleware = next(middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware) and isinstance(middleware.provider, GuardrailAuthorizationAdapter))
        request = MagicMock()
        request.tool_call = {
            "name": "tool_search",
            "args": {"query": "mcp_allowed"},
            "id": "call-search",
        }
        request.runtime = SimpleNamespace(context={"user_role": "guest"})
        expected = MagicMock()
        handler = AsyncMock(return_value=expected)

        result = asyncio.run(authorization_middleware.awrap_tool_call(request, handler))

        assert result is expected
        handler.assert_awaited_once_with(request)

    def test_authorization_wires_adapter_with_the_build_provider_instance(self):
        provider = _FilterProvider(["bash"])
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                provider=AuthorizationProviderConfig(use="deerflow.authz.rbac:RbacAuthorizationProvider", config={"roles": {"user": {}}}),
            )
        )

        middlewares = build_lead_runtime_middlewares(app_config=config, authorization_provider=provider)
        authorization_middleware = next(middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware) and isinstance(middleware.provider, GuardrailAuthorizationAdapter))

        assert authorization_middleware.provider._provider is provider
        assert authorization_middleware.fail_closed is True

    def test_authorization_and_explicit_guardrail_both_run(self):
        provider = _FilterProvider(["bash"])
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                provider=AuthorizationProviderConfig(use="deerflow.authz.rbac:RbacAuthorizationProvider", config={"roles": {"user": {}}}),
            ),
            guardrails=GuardrailsConfig(
                enabled=True,
                provider=GuardrailProviderConfig(
                    use="deerflow.guardrails.builtin:AllowlistProvider",
                    config={"allowed_tools": ["bash"]},
                ),
            ),
        )

        middlewares = build_lead_runtime_middlewares(app_config=config, authorization_provider=provider)
        guardrails = [middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware)]

        assert len(guardrails) == 2
        assert isinstance(guardrails[0].provider, GuardrailAuthorizationAdapter)
        assert guardrails[0].provider._provider is provider
        assert type(guardrails[1].provider).__name__ == "AllowlistProvider"

    def test_wired_authorization_middleware_denies_execution_with_runtime_principal(self):
        class _DenyingProvider(_FilterProvider):
            def __init__(self):
                super().__init__(["bash"])
                self.requests = []

            def authorize(self, request):
                self.requests.append(request)
                return AuthzDecision(
                    allow=False,
                    reasons=[AuthzReason(code="authz.denied", message="blocked")],
                )

        provider = _DenyingProvider()
        config = _app_config(
            authorization=AuthorizationConfig(
                enabled=True,
                provider=AuthorizationProviderConfig(use="unused:Provider"),
            )
        )
        middlewares = build_lead_runtime_middlewares(
            app_config=config,
            authorization_provider=provider,
        )
        authorization_middleware = next(middleware for middleware in middlewares if isinstance(middleware, GuardrailMiddleware) and isinstance(middleware.provider, GuardrailAuthorizationAdapter))
        request = MagicMock()
        request.tool_call = {"name": "bash", "args": {"command": "whoami"}, "id": "call-1"}
        request.runtime = SimpleNamespace(
            context={
                "user_id": "u1",
                "user_role": "guest",
                "thread_id": "t1",
                "run_id": "r1",
            }
        )
        handler = MagicMock()

        result = authorization_middleware.wrap_tool_call(request, handler)

        handler.assert_not_called()
        assert result.status == "error"
        assert "authz.denied" in result.content
        assert provider.requests[0].principal == Principal(user_id="u1", role="guest")
        assert provider.requests[0].target == "bash"
        assert provider.requests[0].context["run_id"] == "r1"


@pytest.mark.parametrize("is_bootstrap", [False, True])
def test_lead_agent_filters_all_model_visible_tools_and_reuses_provider(monkeypatch, is_bootstrap):
    """Layer 1 covers late framework tools and Layer 2 receives its provider."""
    config = _app_config(
        authorization=AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"tools": {"allow": ["safe_tool"]}}}},
            ),
        ),
        models=[
            ModelConfig(
                name="test-model",
                display_name="Test model",
                use="langchain_openai:ChatOpenAI",
                model="test-model",
            )
        ],
    )
    config.skills.deferred_discovery = True

    monkeypatch.setattr(lead_agent_module, "_resolve_model_name", lambda *args, **kwargs: "test-model")
    monkeypatch.setattr(lead_agent_module, "create_chat_model", lambda **kwargs: object())
    monkeypatch.setattr(lead_agent_module, "create_agent", lambda **kwargs: kwargs)
    monkeypatch.setattr(lead_agent_module, "apply_prompt_template", lambda **kwargs: "prompt")
    monkeypatch.setattr(lead_agent_module, "build_tracing_callbacks", lambda: [])
    monkeypatch.setattr(lead_agent_module, "_load_enabled_available_skills", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        lead_agent_module,
        "build_skill_search_setup",
        lambda *args, **kwargs: SimpleNamespace(
            describe_skill_tool=_tool("describe_skill"),
            skill_names=frozenset({"example"}),
        ),
        raising=False,
    )
    monkeypatch.setattr("deerflow.skills.describe.build_skill_search_setup", lead_agent_module.build_skill_search_setup)
    monkeypatch.setattr("deerflow.tools.get_available_tools", lambda **kwargs: [_tool("safe_tool"), _tool("denied_tool")])
    monkeypatch.setattr(lead_agent_module, "should_use_memory_tools", lambda memory_config: True)
    monkeypatch.setattr(
        lead_agent_module,
        "_append_memory_tools_without_name_conflicts",
        lambda tools: tools.append(_tool("memory_search")),
    )

    captured: dict[str, object] = {}

    def _capture_middlewares(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(lead_agent_module, "build_middlewares", _capture_middlewares)

    runtime_context = {"user_role": "user"}
    if is_bootstrap:
        runtime_context["is_bootstrap"] = True
    result = lead_agent_module._make_lead_agent({"context": runtime_context}, app_config=config)

    assert [tool.name for tool in result["tools"]] == ["safe_tool"]
    assert captured["authorization_provider"] is not None
