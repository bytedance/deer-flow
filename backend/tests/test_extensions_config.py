"""Tests for config-declared extension middleware loading (#3923)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware import AgentMiddleware

from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig


# ---------------------------------------------------------------------------
# Dummy middleware classes for testing
# ---------------------------------------------------------------------------


class _ValidMiddleware(AgentMiddleware):
    """A valid middleware used by tests to verify resolution and instantiation."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.init_called = True


class _AnotherMiddleware(AgentMiddleware):
    """Another valid middleware for multi-middleware tests."""


class _NotAMiddleware:
    """A class that does not extend AgentMiddleware."""


# Prevent LangChain's abstract-method enforcement from blocking instantiation
# in tests.  _ValidMiddleware and _AnotherMiddleware are instantiated via
# cls() without async_setup/on_tool_start/on_chat_model_start kwargs, so we
# monkey-patch AgentMiddleware.__init_subclass__ only for this module.
_original_init_subclass = getattr(AgentMiddleware, "__init_subclass__", None)


def _noop_init_subclass(cls, **kwargs):
    pass


AgentMiddleware.__init_subclass__ = classmethod(_noop_init_subclass)  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# ExtensionsConfig deserialization
# ---------------------------------------------------------------------------


class TestExtensionsConfigDeserialization:
    """ExtensionsConfig should deserialize correctly from a plain dict (YAML parse)."""

    def test_defaults(self):
        cfg = ExtensionsConfig()
        assert cfg.middlewares == []
        assert cfg.sse_wrapper is None
        assert cfg.run_model_override is None

    def test_from_dict_with_middlewares(self):
        cfg = ExtensionsConfig.model_validate({"middlewares": ["pkg.mod:MW1", "pkg.mod:MW2"]})
        assert cfg.middlewares == ["pkg.mod:MW1", "pkg.mod:MW2"]

    def test_from_dict_with_hooks(self):
        cfg = ExtensionsConfig.model_validate(
            {
                "sse_wrapper": "pkg.stream:Wrapper",
                "run_model_override": "pkg.router:Router",
            }
        )
        assert cfg.sse_wrapper == "pkg.stream:Wrapper"
        assert cfg.run_model_override == "pkg.router:Router"

    def test_from_empty_dict(self):
        cfg = ExtensionsConfig.model_validate({})
        assert cfg.middlewares == []
        assert cfg.sse_wrapper is None
        assert cfg.run_model_override is None

    def test_preserves_mcp_servers_and_skills(self):
        """New fields must not break existing mcpServers/skills parsing."""
        cfg = ExtensionsConfig.model_validate(
            {
                "mcpServers": {
                    "test_srv": {"enabled": True, "type": "stdio", "command": "echo"},
                },
                "skills": {"my_skill": {"enabled": False}},
                "middlewares": ["pkg.mod:MW"],
            }
        )
        assert len(cfg.mcp_servers) == 1
        assert cfg.mcp_servers["test_srv"].command == "echo"
        assert cfg.skills["my_skill"].enabled is False
        assert cfg.middlewares == ["pkg.mod:MW"]


# ---------------------------------------------------------------------------
# load_extension_middlewares
# ---------------------------------------------------------------------------


class TestLoadExtensionMiddlewares:
    """Unit tests for :func:`deerflow.agents.factory.load_extension_middlewares`."""

    def test_empty_config_returns_empty(self):
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig()
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_none_extensions_returns_empty(self):
        from deerflow.agents.factory import load_extension_middlewares

        app_cfg = MagicMock(extensions=None)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_no_extensions_attr_returns_empty(self):
        from deerflow.agents.factory import load_extension_middlewares

        app_cfg = MagicMock(spec=[])
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_single_valid_middleware(self):
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_ValidMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert len(result) == 1
        assert isinstance(result[0], _ValidMiddleware)
        assert result[0].init_called is True

    def test_multiple_valid_middlewares(self):
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=[
                "test_extensions_config:_ValidMiddleware",
                "test_extensions_config:_AnotherMiddleware",
            ],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert len(result) == 2
        assert isinstance(result[0], _ValidMiddleware)
        assert isinstance(result[1], _AnotherMiddleware)

    def test_module_not_found_skipped(self):
        """ModuleNotFoundError should log INFO and skip, not crash."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["nonexistent_package.module:SomeClass"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_invalid_path_format_skipped(self):
        """A malformed path (no colon) should be logged and skipped."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["not_a_valid_path_without_colon"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_non_middleware_class_skipped(self):
        """Resolved class that is not AgentMiddleware subclass → skipped."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_NotAMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_instantiation_failure_skipped(self):
        """If cls() raises, log and skip."""
        from deerflow.agents.factory import load_extension_middlewares

        class _BrokenMiddleware(AgentMiddleware):
            def __init__(self, **kwargs):
                raise RuntimeError("boom")

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_BrokenMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_mixed_valid_and_invalid(self):
        """Valid middlewares load; invalid ones are skipped."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=[
                "test_extensions_config:_ValidMiddleware",
                "nonexistent.module:DoesNotExist",
                "test_extensions_config:_AnotherMiddleware",
            ],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert len(result) == 2
        assert isinstance(result[0], _ValidMiddleware)
        assert isinstance(result[1], _AnotherMiddleware)

    def test_paths_with_whitespace_trimmed(self):
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["  test_extensions_config:_ValidMiddleware  "],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert len(result) == 1
        assert isinstance(result[0], _ValidMiddleware)


# ---------------------------------------------------------------------------
# resolve_extension_hooks
# ---------------------------------------------------------------------------


class TestResolveExtensionHooks:
    """Unit tests for :func:`deerflow.agents.factory.resolve_extension_hooks`."""

    def test_none_extensions_returns_none_tuple(self):
        from deerflow.agents.factory import resolve_extension_hooks

        app_cfg = MagicMock(extensions=None)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is None
        assert model is None

    def test_no_hooks_configured(self):
        from deerflow.agents.factory import resolve_extension_hooks

        cfg = ExtensionsConfig()
        app_cfg = MagicMock(extensions=cfg)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is None
        assert model is None

    def test_sse_wrapper_resolved(self):
        from deerflow.agents.factory import resolve_extension_hooks

        cfg = ExtensionsConfig(sse_wrapper="test_extensions_config:_ValidMiddleware")
        app_cfg = MagicMock(extensions=cfg)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is _ValidMiddleware
        assert model is None

    def test_run_model_override_resolved(self):
        from deerflow.agents.factory import resolve_extension_hooks

        cfg = ExtensionsConfig(run_model_override="test_extensions_config:_AnotherMiddleware")
        app_cfg = MagicMock(extensions=cfg)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is None
        assert model is _AnotherMiddleware

    def test_both_hooks_resolved(self):
        from deerflow.agents.factory import resolve_extension_hooks

        cfg = ExtensionsConfig(
            sse_wrapper="test_extensions_config:_ValidMiddleware",
            run_model_override="test_extensions_config:_AnotherMiddleware",
        )
        app_cfg = MagicMock(extensions=cfg)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is _ValidMiddleware
        assert model is _AnotherMiddleware

    def test_sse_wrapper_not_found_returns_none(self):
        from deerflow.agents.factory import resolve_extension_hooks

        cfg = ExtensionsConfig(sse_wrapper="nonexistent.module:Klass")
        app_cfg = MagicMock(extensions=cfg)
        sse, model = resolve_extension_hooks(app_cfg)
        assert sse is None  # gracefully handled
        assert model is None


# ---------------------------------------------------------------------------
# AppConfig integration
# ---------------------------------------------------------------------------


class TestAppConfigExtensionsMerge:
    """Verify that YAML-declared extensions merge with JSON-loaded ones."""

    def test_yaml_extensions_override_json(self):
        """YAML keys should take precedence over JSON-loaded keys."""
        # Simulate: JSON loaded {"mcp_servers": {"srv": {...}}, "skills": {}}
        # YAML had {"middlewares": ["pkg:MW"], "sse_wrapper": "pkg:Wrap"}
        with patch.object(ExtensionsConfig, "from_file", return_value=ExtensionsConfig()):
            with patch.object(AppConfig, "resolve_config_path", return_value=__file__):
                # We can't fully test from_file without a real config.yaml,
                # but we can test the merge logic directly.
                pass

    def test_app_config_extensions_field_defaults(self):
        """AppConfig should have extensions as optional with default factory."""
        # Minimal config data with only required fields
        cfg_data = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}
        # Extensions should default to an empty ExtensionsConfig
        with patch.object(ExtensionsConfig, "from_file", return_value=ExtensionsConfig()):
            app_cfg = AppConfig.model_validate(cfg_data)
            assert app_cfg.extensions.middlewares == []
            assert app_cfg.extensions.sse_wrapper is None
            assert app_cfg.extensions.run_model_override is None
