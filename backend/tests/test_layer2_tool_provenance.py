"""Layer-2 tool provenance forwarding and the identity-bound infrastructure exemption.

Covers (spec: PR 2, §6.5):
- ``GuardrailMiddleware._build_request`` resolves host provenance from the
  bound tool object and forwards it into ``AuthzRequest.context``;
- the authorization adapter's infrastructure exemption binds to the concrete
  host-created tool *object* — never to a name or a provenance label;
- a request entering the guardrail with ``tool=None`` goes to the provider.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from langchain_core.tools import StructuredTool

from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.provider import AuthzDecision, AuthzReason, Principal
from deerflow.guardrails.middleware import GuardrailMiddleware
from deerflow.tools.tool_provenance import DECLARED_TOOL_SOURCE_METADATA_KEY, tag_plugin_tool


def _tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(lambda: name, name=name, description=name)


def _build_guardrail_request(tool, *, tool_name: str):
    middleware = GuardrailMiddleware(MagicMock(), fail_closed=True)
    request = MagicMock()
    request.tool_call = {"name": tool_name, "args": {}, "id": "call-1"}
    request.tool = tool
    request.runtime = SimpleNamespace(context={"user_role": "user"})
    return middleware._build_request(request, {"user_role": "user"})


class _CapturingProvider:
    name = "capturing"

    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.requests = []

    def authorize(self, request):
        self.requests.append(request)
        return AuthzDecision(
            allow=self.allow,
            reasons=[] if self.allow else [AuthzReason(code="test.deny", message="denied")],
        )

    async def aauthorize(self, request):
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        return list(candidates)


class TestProvenanceForwarding:
    def test_plugin_tool_provenance_reaches_the_authz_context(self):
        from deerflow.extensions.plugin_tools import plugin_tool_name

        tool = _tool(plugin_tool_name("acme.search", "web_query"))
        tag_plugin_tool(tool, namespace="acme.search", declaration="web_query", installation="acme:1.0.0", operation="query")

        gr = _build_guardrail_request(tool, tool_name=tool.name)

        assert gr.tool_identity is tool
        assert gr.tool_provenance["source"] == "plugin:acme.search"
        assert gr.tool_provenance["namespace"] == "acme.search"
        assert gr.tool_provenance["declaration"] == "web_query"
        assert gr.tool_provenance["installation"] == "acme:1.0.0"
        assert gr.tool_provenance["operation"] == "query"

        provider = _CapturingProvider()
        GuardrailAuthorizationAdapter(provider).evaluate(gr)

        forwarded = provider.requests[0].context["tool_provenance"]
        assert forwarded["source"] == "plugin:acme.search"
        assert forwarded["namespace"] == "acme.search"
        # The opaque identity never leaves the guardrail layer.
        assert "tool_identity" not in provider.requests[0].context

    def test_mis_attributed_plugin_tag_is_dropped(self):
        tool = _tool("totally_different_name")
        tag_plugin_tool(tool, namespace="acme.search", declaration="web_query", installation="acme:1.0.0")

        gr = _build_guardrail_request(tool, tool_name=tool.name)

        assert gr.tool_provenance.get("source") != "plugin:acme.search"
        assert "namespace" not in gr.tool_provenance

    def test_missing_tool_yields_empty_provenance_and_no_identity(self):
        gr = _build_guardrail_request(None, tool_name="anything")

        assert gr.tool_provenance == {}
        assert gr.tool_identity is None


class TestIdentityBoundExemption:
    def test_exemption_applies_to_the_host_created_object(self):
        host_tool = _tool("tool_search")
        provider = _CapturingProvider()
        adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tools=[host_tool])

        decision = adapter.evaluate(_build_guardrail_request(host_tool, tool_name="tool_search"))

        assert decision.allow is True
        assert decision.policy_id == "authz:infrastructure"
        assert provider.requests == []  # no provider call for the exempt tool

    def test_same_named_foreign_tool_is_not_exempt(self):
        host_tool = _tool("tool_search")
        foreign_tool = _tool("tool_search")  # same name, different object
        provider = _CapturingProvider(allow=False)
        adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tools=[host_tool])

        decision = adapter.evaluate(_build_guardrail_request(foreign_tool, tool_name="tool_search"))

        assert decision.allow is False
        assert len(provider.requests) == 1

    def test_builtin_label_does_not_buy_the_exemption(self):
        host_tool = _tool("tool_search")
        impostor = _tool("tool_search")
        impostor.metadata = {DECLARED_TOOL_SOURCE_METADATA_KEY: "builtin"}
        provider = _CapturingProvider(allow=False)
        adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tools=[host_tool])

        decision = adapter.evaluate(_build_guardrail_request(impostor, tool_name="tool_search"))

        assert decision.allow is False
        assert len(provider.requests) == 1
        # The label still flows as display context — it just decides nothing.
        assert provider.requests[0].context["tool_provenance"]["source"] == "builtin"

    def test_tool_none_request_goes_to_the_provider(self):
        host_tool = _tool("tool_search")
        provider = _CapturingProvider(allow=False)
        adapter = GuardrailAuthorizationAdapter(provider, infrastructure_tools=[host_tool])

        decision = adapter.evaluate(_build_guardrail_request(None, tool_name="tool_search"))

        assert decision.allow is False
        assert len(provider.requests) == 1
