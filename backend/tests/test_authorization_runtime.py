"""Tests for resolve_authorization_provider — the provider factory."""

from __future__ import annotations

import pytest

from deerflow.authz.provider import AuthorizationProvider
from deerflow.authz.runtime import resolve_authorization_provider
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig


class TestDisabled:
    """enabled=False must return None without importing anything."""

    def test_disabled_returns_none(self):
        config = AuthorizationConfig(enabled=False)
        assert resolve_authorization_provider(config) is None

    def test_disabled_with_provider_config_returns_none(self):
        """Even with a provider configured, disabled means None."""
        config = AuthorizationConfig(
            enabled=False,
            provider=AuthorizationProviderConfig(use="nonexistent.module:FakeProvider"),
        )
        assert resolve_authorization_provider(config) is None


class TestMissingProvider:
    """enabled=True but no provider configured must fail clearly."""

    def test_enabled_without_provider_raises(self):
        config = AuthorizationConfig(enabled=True)
        with pytest.raises(ValueError, match="no provider is configured"):
            resolve_authorization_provider(config)


class TestValidProvider:
    """Built-in and custom providers resolve through the same path."""

    def test_builtin_rbac_resolves(self):
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"admin": {"tools": {"allow": "*"}}}},
            ),
        )
        provider = resolve_authorization_provider(config)
        assert provider is not None
        assert isinstance(provider, AuthorizationProvider)
        assert provider.name == "rbac"

    def test_custom_provider_resolves(self):
        """A provider defined in an importable module resolves through the same path."""
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"tools": {"allow": ["web_search"]}}}},
            ),
        )
        provider = resolve_authorization_provider(config)
        assert provider is not None


class TestInvalidClassPath:
    """Invalid class paths must raise with the path in the error."""

    def test_nonexistent_module_raises_with_path(self):
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(use="nonexistent.module:FakeProvider"),
        )
        with pytest.raises(ValueError, match="nonexistent.module"):
            resolve_authorization_provider(config)

    def test_nonexistent_attribute_raises_with_path(self):
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(use="deerflow.authz.rbac:NonexistentProvider"),
        )
        with pytest.raises(ValueError, match="NonexistentProvider"):
            resolve_authorization_provider(config)


class TestProtocolConformance:
    """Instance not satisfying AuthorizationProvider must fail."""

    def test_non_protocol_class_raises(self):
        """A class that constructs successfully but doesn't implement all
        Protocol methods must fail the isinstance check."""
        # `builtins:dict` constructs as empty dict(), which is not an
        # AuthorizationProvider — it lacks name/authorize/aauthorize/filter_resources.
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="builtins:dict",
                config={},
            ),
        )
        with pytest.raises(ValueError, match="AuthorizationProvider Protocol"):
            resolve_authorization_provider(config)

    def test_non_class_target_raises(self):
        """A class path pointing to a non-class (e.g. a function) must fail
        because resolve_variable is called with expected_type=type."""
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="builtins:print",
                config={},
            ),
        )
        with pytest.raises(ValueError, match="Failed to resolve"):
            resolve_authorization_provider(config)


class TestRbacErrorPropagation:
    """Factory must surface RBAC construction errors with class path and __cause__."""

    def test_unknown_provider_config_key_surfaces_through_factory(self):
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {}}, "bogus": True},
            ),
        )
        with pytest.raises(ValueError, match="RbacAuthorizationProvider.*bogus") as exc_info:
            resolve_authorization_provider(config)
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_invalid_rbac_config_surfaces_class_path(self):
        """RBAC construction failure (e.g. bad roles) must produce a ValueError
        containing the class path."""
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": "not a dict"},
            ),
        )
        with pytest.raises(ValueError, match="RbacAuthorizationProvider"):
            resolve_authorization_provider(config)

    def test_invalid_rbac_config_preserves_cause(self):
        """The original construction error must be chained as __cause__."""
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"tools": {"allow": 42}}}},
            ),
        )
        try:
            resolve_authorization_provider(config)
        except ValueError as err:
            assert err.__cause__ is not None
            assert isinstance(err.__cause__, ValueError)
        else:
            pytest.fail("Expected ValueError for invalid RBAC config")


class TestNoFactoryInjection:
    """Factory must not inject fail_closed or default_role into provider kwargs."""

    def test_factory_does_not_inject_framework_params(self):
        """The provider constructor should only receive config.config kwargs,
        not fail_closed/default_role from AuthorizationConfig."""
        config = AuthorizationConfig(
            enabled=True,
            fail_closed=False,
            default_role="guest",
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"guest": {"tools": {"allow": "*"}}}},
            ),
        )
        # Should construct successfully without injecting fail_closed/default_role
        provider = resolve_authorization_provider(config)
        assert provider is not None


class TestNoCaching:
    """Factory must not cache instances."""

    def test_each_call_returns_new_instance(self):
        config = AuthorizationConfig(
            enabled=True,
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"admin": {"tools": {"allow": "*"}}}},
            ),
        )
        p1 = resolve_authorization_provider(config)
        p2 = resolve_authorization_provider(config)
        assert p1 is not p2


class TestDisabledNoImport:
    """disabled must not trigger any import of the provider module."""

    def test_disabled_does_not_import_invalid_path(self):
        """Even with a garbage class path, disabled must return None
        without raising ImportError."""
        config = AuthorizationConfig(
            enabled=False,
            provider=AuthorizationProviderConfig(use="garbage.that.does.not.exist:Nope"),
        )
        # Must not raise
        assert resolve_authorization_provider(config) is None
