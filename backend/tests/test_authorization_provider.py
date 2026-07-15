"""Tests for the authorization provider protocol, adapter, and configuration.

Phase 0 covers scaffolding only (no behavior change at ``enabled: false``).
These tests verify:
- Protocol conformance and ``@runtime_checkable`` isinstance checks.
- Principal / AuthzRequest / AuthzDecision dataclass construction.
- GuardrailAuthorizationAdapter request mapping and decision conversion.
- AuthorizationConfig defaults, singleton load/reset, and AppConfig wiring.
"""

from __future__ import annotations

import asyncio

import pytest

from deerflow.authz.adapter import GuardrailAuthorizationAdapter
from deerflow.authz.provider import (
    AuthorizationProvider,
    AuthzDecision,
    AuthzReason,
    AuthzRequest,
    Principal,
)
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import (
    AuthorizationConfig,
    get_authorization_config,
    load_authorization_config_from_dict,
    reset_authorization_config,
)
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.guardrails.provider import GuardrailDecision, GuardrailProvider, GuardrailRequest

# --- Test providers ---


class _AllowAllProvider:
    """Provider that allows everything."""

    name = "allow-all"

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        return AuthzDecision(allow=True, reasons=[AuthzReason(code="test.allowed", message="allow-all")])

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        return list(candidates)


class _DenyAllProvider:
    """Provider that denies everything."""

    name = "deny-all"

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        return AuthzDecision(allow=False, reasons=[AuthzReason(code="test.denied", message="deny-all")], policy_id="test.deny.v1")

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        return []


class _FilterByDenylistProvider:
    """Provider whose filter_resources removes a denylist, regardless of authorize()."""

    name = "denylist-filter"

    def __init__(self, *, denied: list[str] | None = None):
        self._denied = set(denied) if denied else set()

    def authorize(self, request: AuthzRequest) -> AuthzDecision:
        if request.target in self._denied:
            return AuthzDecision(allow=False, reasons=[AuthzReason(code="test.denied", message=f"'{request.target}' is denied")])
        return AuthzDecision(allow=True, reasons=[AuthzReason(code="test.allowed")])

    async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
        return self.authorize(request)

    def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
        return [c for c in candidates if c not in self._denied]


# --- Protocol conformance ---


class TestProtocolConformance:
    """Verify the @runtime_checkable Protocol recognizes concrete providers."""

    def test_allow_all_is_authorization_provider(self):
        assert isinstance(_AllowAllProvider(), AuthorizationProvider)

    def test_deny_all_is_authorization_provider(self):
        assert isinstance(_DenyAllProvider(), AuthorizationProvider)

    def test_plain_object_without_methods_is_not_provider(self):
        class _NotAProvider:
            pass

        assert not isinstance(_NotAProvider(), AuthorizationProvider)

    def test_provider_without_filter_resources_is_not_provider(self):
        """filter_resources is a required Protocol method.

        A provider that only implements name/authorize/aauthorize but omits
        filter_resources must NOT pass isinstance — otherwise it would be
        silently accepted as an AuthorizationProvider and Layer 1 would
        get None (fail-open) when calling filter_resources.
        """

        class _NoFilterMethod:
            name = "no-filter"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

        assert not isinstance(_NoFilterMethod(), AuthorizationProvider)


# --- Dataclass construction ---


class TestDataclasses:
    """Verify Principal / AuthzRequest / AuthzDecision construction."""

    def test_principal_defaults(self):
        p = Principal()
        assert p.user_id is None
        assert p.role is None
        assert p.oauth_provider is None
        assert p.oauth_id is None
        assert p.channel_user_id is None
        assert p.is_internal is False
        assert p.attributes == {}

    def test_principal_with_fields(self):
        p = Principal(user_id="u1", role="admin", oauth_provider="github", oauth_id="gh-123", is_internal=True)
        assert p.user_id == "u1"
        assert p.role == "admin"
        assert p.oauth_provider == "github"
        assert p.oauth_id == "gh-123"
        assert p.is_internal is True

    def test_authz_request(self):
        p = Principal(user_id="u1", role="user")
        req = AuthzRequest(principal=p, resource="tool", action="call", target="bash")
        assert req.principal.user_id == "u1"
        assert req.resource == "tool"
        assert req.action == "call"
        assert req.target == "bash"
        assert req.context == {}

    def test_authz_request_with_context(self):
        p = Principal(user_id="u1")
        req = AuthzRequest(principal=p, resource="tool", action="call", target="write_file", context={"thread_id": "t1"})
        assert req.context["thread_id"] == "t1"

    def test_authz_decision_defaults(self):
        d = AuthzDecision(allow=True)
        assert d.allow is True
        assert d.reasons == []
        assert d.policy_id is None
        assert d.metadata == {}

    def test_authz_decision_with_reasons(self):
        d = AuthzDecision(allow=False, reasons=[AuthzReason(code="denied", message="no access")], policy_id="p1")
        assert d.allow is False
        assert len(d.reasons) == 1
        assert d.reasons[0].code == "denied"
        assert d.reasons[0].message == "no access"
        assert d.policy_id == "p1"


# --- filter_resources ---


class TestFilterResources:
    """Verify the Layer 1 batch filter."""

    def test_allow_all_returns_all(self):
        provider = _AllowAllProvider()
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search", "read_file"])
        assert result == ["bash", "web_search", "read_file"]

    def test_deny_all_returns_empty(self):
        provider = _DenyAllProvider()
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search"])
        assert result == []

    def test_denylist_filter_removes_denied(self):
        provider = _FilterByDenylistProvider(denied=["bash", "write_file"])
        result = provider.filter_resources(Principal(role="user"), "tool", ["bash", "web_search", "write_file", "read_file"])
        assert result == ["web_search", "read_file"]


# --- GuardrailAuthorizationAdapter ---


def _make_guardrail_request(
    *,
    tool_name: str = "bash",
    tool_input: dict | None = None,
    user_id: str | None = "u1",
    user_role: str | None = "user",
    thread_id: str | None = "t1",
    is_subagent: bool = False,
    agent_id: str | None = None,
    timestamp: str = "",
) -> GuardrailRequest:
    return GuardrailRequest(
        tool_name=tool_name,
        tool_input=tool_input or {},
        user_id=user_id,
        user_role=user_role,
        thread_id=thread_id,
        is_subagent=is_subagent,
        agent_id=agent_id,
        timestamp=timestamp,
    )


class TestGuardrailAuthorizationAdapter:
    """Verify the adapter maps between Guardrail and Authz request/decision types."""

    def test_adapter_name(self):
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        assert adapter.name == "authorization"

    def test_adapter_is_guardrail_provider(self):
        """The adapter must satisfy the GuardrailProvider Protocol so existing
        GuardrailMiddleware can enforce authz decisions without a new middleware."""
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        assert isinstance(adapter, GuardrailProvider)

    def test_evaluate_allow(self):
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        gr_req = _make_guardrail_request(tool_name="web_search")
        decision = adapter.evaluate(gr_req)
        assert decision.allow is True
        assert len(decision.reasons) == 1
        assert decision.reasons[0].code == "test.allowed"

    def test_evaluate_deny(self):
        adapter = GuardrailAuthorizationAdapter(_DenyAllProvider())
        gr_req = _make_guardrail_request(tool_name="bash")
        decision = adapter.evaluate(gr_req)
        assert decision.allow is False
        assert decision.policy_id == "test.deny.v1"

    def test_evaluate_maps_principal_identity(self):
        """Verify user_role and user_id flow into the AuthzRequest principal."""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                captured.append(request)
                return AuthzDecision(allow=True, reasons=[AuthzReason(code="ok")])

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        gr_req = _make_guardrail_request(user_id="user-42", user_role="admin", tool_name="write_file")
        adapter.evaluate(gr_req)

        assert len(captured) == 1
        authz_req = captured[0]
        assert authz_req.principal.user_id == "user-42"
        assert authz_req.principal.role == "admin"
        assert authz_req.resource == "tool"
        assert authz_req.action == "call"
        assert authz_req.target == "write_file"

    def test_evaluate_does_not_populate_is_internal_in_phase0(self):
        """is_internal is not populated by the adapter in Phase 0.

        The correct signal (auth_source == AUTH_SOURCE_INTERNAL) lives on
        request.state, not on GuardrailRequest. The adapter does not set
        is_internal, so Principal retains its dataclass default (False).
        Phase 1 will thread the signal into run context.
        """
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        adapter.evaluate(_make_guardrail_request(user_role="user"))

        # is_internal retains its dataclass default — adapter does not set it
        assert captured[0].principal.is_internal is False

    def test_evaluate_maps_context_fields(self):
        """Verify thread_id, tool_input, and is_subagent flow into AuthzRequest.context."""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider())
        gr_req = _make_guardrail_request(
            tool_name="write_file",
            tool_input={"path": "/tmp/test.txt"},
            thread_id="thread-99",
            is_subagent=True,
            agent_id="passport-42",
            timestamp="2026-07-13T00:00:00Z",
        )
        adapter.evaluate(gr_req)

        ctx = captured[0].context
        assert ctx["thread_id"] == "thread-99"
        assert ctx["tool_input"] == {"path": "/tmp/test.txt"}
        assert ctx["is_subagent"] is True
        assert ctx["agent_id"] == "passport-42"
        assert ctx["timestamp"] == "2026-07-13T00:00:00Z"

    def test_custom_resource_type_and_action(self):
        """The adapter can be configured for non-tool resource types."""
        captured: list[AuthzRequest] = []

        class _CapturingProvider:
            name = "capturing"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                captured.append(request)
                return AuthzDecision(allow=True)

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_CapturingProvider(), resource_type="model", action="use")
        adapter.evaluate(_make_guardrail_request(tool_name="claude-sonnet-4-6"))

        assert captured[0].resource == "model"
        assert captured[0].action == "use"

    def test_aevaluate_allow(self):
        adapter = GuardrailAuthorizationAdapter(_AllowAllProvider())
        gr_req = _make_guardrail_request(tool_name="web_search")
        decision = asyncio.run(adapter.aevaluate(gr_req))
        assert decision.allow is True

    def test_aevaluate_deny(self):
        adapter = GuardrailAuthorizationAdapter(_DenyAllProvider())
        gr_req = _make_guardrail_request(tool_name="bash")
        decision = asyncio.run(adapter.aevaluate(gr_req))
        assert decision.allow is False

    def test_decision_conversion_preserves_metadata(self):
        class _MetadataProvider:
            name = "metadata"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                return AuthzDecision(
                    allow=True,
                    reasons=[AuthzReason(code="ok", message="allowed by policy X")],
                    policy_id="rbac.v1",
                    metadata={"rule_id": "rule-42"},
                )

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                return self.authorize(request)

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_MetadataProvider())
        decision = adapter.evaluate(_make_guardrail_request())

        assert isinstance(decision, GuardrailDecision)
        assert decision.policy_id == "rbac.v1"
        assert decision.metadata == {"rule_id": "rule-42"}
        assert decision.reasons[0].message == "allowed by policy X"

    def test_evaluate_propagates_provider_exception(self):
        """Provider exceptions propagate to the caller (sync).

        The adapter intentionally does not catch provider exceptions.
        GuardrailMiddleware's wrap_tool_call applies fail_closed semantics
        (deny on error when fail_closed=True). Catching here would duplicate
        that logic and risk divergent behavior between layers.
        """

        class _ExplodingProvider:
            name = "exploding"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                raise RuntimeError("provider crashed")

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                raise RuntimeError("provider crashed")

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_ExplodingProvider())
        with pytest.raises(RuntimeError, match="provider crashed"):
            adapter.evaluate(_make_guardrail_request())

    def test_aevaluate_propagates_provider_exception(self):
        """Provider exceptions propagate to the caller (async).

        Same rationale as the sync variant: GuardrailMiddleware's
        awrap_tool_call handles fail_closed.
        """

        class _ExplodingProvider:
            name = "exploding"

            def authorize(self, request: AuthzRequest) -> AuthzDecision:
                raise RuntimeError("provider crashed")

            async def aauthorize(self, request: AuthzRequest) -> AuthzDecision:
                raise RuntimeError("provider crashed")

            def filter_resources(self, principal: Principal, resource_type: str, candidates: list[str]) -> list[str]:
                return list(candidates)

        adapter = GuardrailAuthorizationAdapter(_ExplodingProvider())
        with pytest.raises(RuntimeError, match="provider crashed"):
            asyncio.run(adapter.aevaluate(_make_guardrail_request()))


# --- Configuration ---


class TestAuthorizationConfig:
    """Verify config defaults, singleton behavior, and AppConfig wiring."""

    def teardown_method(self):
        reset_authorization_config()

    def test_defaults(self):
        config = AuthorizationConfig()
        assert config.enabled is False
        assert config.fail_closed is True
        assert config.default_role == "user"
        assert config.provider is None

    def test_get_returns_defaults_when_not_loaded(self):
        reset_authorization_config()
        config = get_authorization_config()
        assert config.enabled is False

    def test_load_from_dict(self):
        config = load_authorization_config_from_dict(
            {
                "enabled": True,
                "default_role": "guest",
                "provider": {
                    "use": "my_package:MyProvider",
                    "config": {"roles": {"admin": {}}},
                },
            }
        )
        assert config.enabled is True
        assert config.default_role == "guest"
        assert config.provider is not None
        assert config.provider.use == "my_package:MyProvider"
        assert config.provider.config == {"roles": {"admin": {}}}

    def test_singleton_persistence(self):
        load_authorization_config_from_dict({"enabled": True})
        config2 = get_authorization_config()
        assert config2.enabled is True

    def test_reset_clears_singleton(self):
        load_authorization_config_from_dict({"enabled": True})
        reset_authorization_config()
        config = get_authorization_config()
        assert config.enabled is False

    def test_app_config_has_authorization_field(self):
        """Verify AuthorizationConfig is wired into AppConfig with correct defaults."""
        app_config = AppConfig(sandbox=SandboxConfig(use="test"))
        assert hasattr(app_config, "authorization")
        assert app_config.authorization.enabled is False
        assert app_config.authorization.fail_closed is True
        assert app_config.authorization.default_role == "user"

    def test_app_config_load_propagates_to_singleton(self):
        """Verify _apply_singleton_configs populates the authorization singleton.

        model_validate alone does NOT call _apply_singleton_configs (that runs
        only in from_file). We call it directly to verify the wiring line
        ``load_authorization_config_from_dict(config.authorization.model_dump())``
        actually populates the singleton — deleting that line should fail this test.
        """
        reset_authorization_config()
        validated = AppConfig.model_validate(
            {
                "sandbox": {"use": "test"},
                "authorization": {
                    "enabled": True,
                    "default_role": "operator",
                },
            }
        )
        # Drive the singleton wiring the same way from_file does.
        AppConfig._apply_singleton_configs(validated, acp_agents={})

        singleton = get_authorization_config()
        assert singleton.enabled is True
        assert singleton.default_role == "operator"
