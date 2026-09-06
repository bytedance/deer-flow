"""Tests for Phase 1B tool authorization enforcement.

Covers Layer 1 (tool filtering before deferred assembly) and Layer 2
(GuardrailMiddleware via adapter) across the authorization enforcement
helpers, plus disabled-parity and fail-closed semantics.
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, StructuredTool

from deerflow.authz.enforcement import filter_tools_by_authorization
from deerflow.authz.provider import Principal
from deerflow.authz.rbac import RbacAuthorizationProvider
from deerflow.authz.tool_filter import apply_tool_authorization
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.sandbox_config import SandboxConfig

# --- Helpers ---


def _make_tool(name: str) -> BaseTool:
    """Create a minimal named tool for testing."""
    return StructuredTool.from_function(lambda: None, name=name, description="test tool")


def _make_app_config(authz_config: AuthorizationConfig) -> AppConfig:
    return AppConfig(
        sandbox=SandboxConfig(use="test"),
        authorization=authz_config,
    )


def _rbac_provider() -> RbacAuthorizationProvider:
    return RbacAuthorizationProvider(
        roles={
            "admin": {"tools": {"allow": "*"}},
            "user": {"tools": {"allow": "*", "deny": ["update_agent", "bash"]}},
            "guest": {"tools": {"allow": ["web_search", "read_file"]}},
        }
    )


# --- filter_tools_by_authorization ---


class TestFilterToolsByAuthorization:
    def test_provider_none_returns_original(self):
        """When authorization is disabled (provider=None), tools pass through unchanged."""
        tools = [_make_tool("bash"), _make_tool("web_search")]
        result = filter_tools_by_authorization(
            tools,
            provider=None,
            principal=Principal(role="user"),
            fail_closed=True,
        )
        assert result == tools

    def test_filters_denied_tools(self):
        """Denied tools are removed."""
        provider = _rbac_provider()
        tools = [_make_tool("bash"), _make_tool("web_search"), _make_tool("read_file")]
        result = filter_tools_by_authorization(
            tools,
            provider=provider,
            principal=Principal(role="user"),
            fail_closed=True,
        )
        names = [t.name for t in result]
        assert "bash" not in names
        assert "web_search" in names
        assert "read_file" in names

    def test_preserves_order(self):
        """Filtering preserves the original tool order."""
        provider = _rbac_provider()
        tools = [_make_tool("web_search"), _make_tool("bash"), _make_tool("read_file")]
        result = filter_tools_by_authorization(
            tools,
            provider=provider,
            principal=Principal(role="user"),
            fail_closed=True,
        )
        assert [t.name for t in result] == ["web_search", "read_file"]

    def test_guest_narrow_allowlist(self):
        """Guest role only sees allowed tools."""
        provider = _rbac_provider()
        tools = [_make_tool("bash"), _make_tool("web_search"), _make_tool("read_file"), _make_tool("write_file")]
        result = filter_tools_by_authorization(
            tools,
            provider=provider,
            principal=Principal(role="guest"),
            fail_closed=True,
        )
        assert [t.name for t in result] == ["web_search", "read_file"]

    def test_fail_closed_on_provider_error(self):
        """When provider raises and fail_closed=True, deny all tools."""

        class _ExplodingProvider:
            name = "exploding"

            def authorize(self, request):
                raise RuntimeError("boom")

            async def aauthorize(self, request):
                raise RuntimeError("boom")

            def filter_resources(self, principal, resource_type, candidates):
                raise RuntimeError("boom")

        tools = [_make_tool("bash"), _make_tool("web_search")]
        result = filter_tools_by_authorization(
            tools,
            provider=_ExplodingProvider(),
            principal=Principal(role="user"),
            fail_closed=True,
        )
        assert result == []

    def test_fail_open_on_provider_error(self):
        """When provider raises and fail_closed=False, keep original tools."""

        class _ExplodingProvider:
            name = "exploding"

            def authorize(self, request):
                raise RuntimeError("boom")

            async def aauthorize(self, request):
                raise RuntimeError("boom")

            def filter_resources(self, principal, resource_type, candidates):
                raise RuntimeError("boom")

        tools = [_make_tool("bash"), _make_tool("web_search")]
        result = filter_tools_by_authorization(
            tools,
            provider=_ExplodingProvider(),
            principal=Principal(role="user"),
            fail_closed=False,
        )
        assert result == tools

    def test_unknown_role_raises_and_fail_closed_denies_all(self):
        """Unknown role causes filter_resources to raise ValueError;
        fail_closed=True → deny all tools."""
        provider = _rbac_provider()
        tools = [_make_tool("bash"), _make_tool("web_search")]
        result = filter_tools_by_authorization(
            tools,
            provider=provider,
            principal=Principal(role="nonexistent"),
            fail_closed=True,
        )
        assert result == []


# --- apply_tool_authorization (wrapper) ---


class TestApplyToolAuthorization:
    def test_disabled_returns_original_and_none(self):
        """When authorization is disabled, tools unchanged and provider=None."""
        app_config = _make_app_config(AuthorizationConfig(enabled=False))
        tools = [_make_tool("bash")]
        result, provider = apply_tool_authorization(
            tools,
            context={},
            app_config=app_config,
        )
        assert result == tools
        assert provider is None

    def test_enabled_filters_and_returns_provider(self):
        """When enabled, tools are filtered and provider is returned for Layer 2 reuse."""
        app_config = _make_app_config(
            AuthorizationConfig(
                enabled=True,
                provider=AuthorizationProviderConfig(
                    use="deerflow.authz.rbac:RbacAuthorizationProvider",
                    config={"roles": {"user": {"tools": {"allow": "*", "deny": ["bash"]}}}},
                ),
            )
        )
        tools = [_make_tool("bash"), _make_tool("web_search")]
        result, provider = apply_tool_authorization(
            tools,
            context={"user_role": "user"},
            app_config=app_config,
        )
        assert provider is not None
        assert [t.name for t in result] == ["web_search"]

    def test_disabled_does_not_resolve_provider(self):
        """Disabled mode must not attempt to resolve/import the provider."""
        app_config = _make_app_config(
            AuthorizationConfig(
                enabled=False,
                provider=AuthorizationProviderConfig(use="nonexistent.module:FakeProvider"),
            )
        )
        tools = [_make_tool("bash")]
        result, provider = apply_tool_authorization(
            tools,
            context={},
            app_config=app_config,
        )
        assert result == tools
        assert provider is None

    def test_reuses_provided_provider(self):
        """When caller provides a provider, it's reused (not re-resolved)."""
        rbac = _rbac_provider()
        app_config = _make_app_config(AuthorizationConfig(enabled=True))
        tools = [_make_tool("bash"), _make_tool("web_search")]
        result, provider = apply_tool_authorization(
            tools,
            context={"user_role": "user"},
            app_config=app_config,
            authorization_provider=rbac,
        )
        assert provider is rbac
        assert "bash" not in [t.name for t in result]


# --- Disabled parity ---


class TestDisabledParity:
    """When authorization.enabled=false, the tool set must be completely unchanged."""

    def test_lead_agent_context_disabled_noop(self):
        """Simulate what the lead agent does: apply_tool_authorization with disabled config."""
        app_config = _make_app_config(AuthorizationConfig(enabled=False))
        tools = [_make_tool("bash"), _make_tool("web_search"), _make_tool("read_file")]
        result, provider = apply_tool_authorization(
            tools,
            context={"user_role": "admin", "user_id": "u1", "is_internal": True},
            app_config=app_config,
        )
        assert result == tools
        assert provider is None
