"""Tests for config-declared extension middleware loading (#3923)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
import yaml
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


class _BrokenMiddleware(AgentMiddleware):
    """Middleware whose __init__ always raises — used to test instantiation-failure handling.

    This is module-level so :func:`resolve_variable` can resolve it before
    ``cls()`` is reached, exercising the ``except Exception`` branch in
    :func:`load_extension_middlewares`.
    """

    def __init__(self, **kwargs):
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _neutralize_agent_middleware_init_subclass():
    """Prevent LangChain's abstract-method enforcement from blocking instantiation.

    ``_ValidMiddleware``, ``_AnotherMiddleware``, and ``_BrokenMiddleware`` are
    instantiated via ``cls()`` without ``async_setup``/``on_tool_start``/
    ``on_chat_model_start`` kwargs.  This fixture monkey-patches
    ``AgentMiddleware.__init_subclass__`` for the duration of this module's
    tests and restores the original afterwards so other test modules are not
    affected.
    """
    original = getattr(AgentMiddleware, "__init_subclass__", None)

    def _noop(cls, **kwargs):
        pass

    AgentMiddleware.__init_subclass__ = classmethod(_noop)  # type: ignore[assignment]
    yield
    if original is not None:
        AgentMiddleware.__init_subclass__ = original
    else:
        del AgentMiddleware.__init_subclass__


# ---------------------------------------------------------------------------
# ExtensionsConfig deserialization
# ---------------------------------------------------------------------------


class TestExtensionsConfigDeserialization:
    """ExtensionsConfig should deserialize correctly from a plain dict (YAML parse)."""

    def test_defaults(self):
        cfg = ExtensionsConfig()
        assert cfg.enabled is True
        assert cfg.middlewares == []

    def test_from_dict_with_middlewares(self):
        cfg = ExtensionsConfig.model_validate({"middlewares": ["pkg.mod:MW1", "pkg.mod:MW2"]})
        assert cfg.middlewares == ["pkg.mod:MW1", "pkg.mod:MW2"]

    def test_from_empty_dict(self):
        cfg = ExtensionsConfig.model_validate({})
        assert cfg.middlewares == []

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

    def test_disabled_returns_empty(self):
        """When extensions.enabled is False, middlewares are not loaded."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            enabled=False,
            middlewares=["test_extensions_config:_ValidMiddleware"],
        )
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
        """An absent declared top-level package logs INFO and is skipped (optional dependency)."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["nonexistent_package.module:SomeClass"],
        )
        app_cfg = MagicMock(extensions=cfg)
        result = load_extension_middlewares(app_cfg)
        assert result == []

    def test_malformed_path_raises(self):
        """A malformed path (no colon) is a misconfiguration and must abort, not skip."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["not_a_valid_path_without_colon"],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(ImportError, match="doesn't look like a variable path"):
            load_extension_middlewares(app_cfg)

    def test_missing_attribute_raises(self):
        """A resolvable module without the declared attribute must abort, not skip."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_DoesNotExistMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(ImportError, match="does not define"):
            load_extension_middlewares(app_cfg)

    def test_transitive_import_failure_raises(self, tmp_path, monkeypatch):
        """An installed module whose import fails on a missing transitive dependency must abort.

        The declared module exists on ``sys.path`` but raises
        ``ModuleNotFoundError`` for a *different* module while importing —
        that is a broken dependency, not an absent optional package, so the
        agent must not start with the middleware silently absent.
        """
        from deerflow.agents.factory import load_extension_middlewares

        mod = tmp_path / "ext_mw_transitive_fail_mod.py"
        mod.write_text("import definitely_missing_transitive_dep_xyz\n", encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))

        cfg = ExtensionsConfig(
            middlewares=["ext_mw_transitive_fail_mod:SomeMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(ImportError):
            load_extension_middlewares(app_cfg)

    def test_non_middleware_class_raises(self):
        """A resolved class that is not an AgentMiddleware subclass must abort, not skip."""
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_NotAMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(ValueError, match="not a subclass of AgentMiddleware"):
            load_extension_middlewares(app_cfg)

    def test_instantiation_failure_raises(self):
        """If cls() raises, agent construction must abort with the path in the error.

        Uses module-level ``_BrokenMiddleware`` so ``resolve_class`` can
        find it — the test then exercises the constructor-failure branch when
        ``cls()`` raises at instantiation time.
        """
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=["test_extensions_config:_BrokenMiddleware"],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(RuntimeError, match="_BrokenMiddleware") as excinfo:
            load_extension_middlewares(app_cfg)
        assert isinstance(excinfo.value.__cause__, RuntimeError)
        assert "boom" in str(excinfo.value.__cause__)

    def test_mixed_valid_and_missing_optional(self):
        """Valid middlewares load; an absent optional package is skipped."""
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

    def test_duplicate_path_raises(self):
        """The same path declared twice must abort with an actionable error.

        LangChain's ``create_agent`` rejects duplicate middleware names with a
        bare ``AssertionError`` deep inside agent assembly; the loader surfaces
        the misconfiguration up front instead.
        """
        from deerflow.agents.factory import load_extension_middlewares

        cfg = ExtensionsConfig(
            middlewares=[
                "test_extensions_config:_ValidMiddleware",
                "  test_extensions_config:_ValidMiddleware  ",
            ],
        )
        app_cfg = MagicMock(extensions=cfg)
        with pytest.raises(ValueError, match="Duplicate extension middleware path"):
            load_extension_middlewares(app_cfg)

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
# AppConfig integration
# ---------------------------------------------------------------------------


class TestExtensionsJsonIntegration:
    """Extensions (incl. middlewares) come from ``extensions_config.json`` in production.

    ``AppConfig.from_file`` populates the ``extensions`` section from
    ``ExtensionsConfig.from_file()`` and ignores any ``extensions`` key in
    ``config.yaml`` — these tests pin that documented behaviour.
    """

    def test_middlewares_parse_from_extensions_json_file(self, tmp_path):
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(
            json.dumps(
                {
                    "mcpServers": {"srv": {"enabled": False, "type": "stdio", "command": "echo"}},
                    "skills": {},
                    "middlewares": ["my_package.middleware:MyCustomMiddleware"],
                }
            ),
            encoding="utf-8",
        )

        cfg = ExtensionsConfig.from_file(str(extensions_path))

        assert cfg.enabled is True
        assert cfg.middlewares == ["my_package.middleware:MyCustomMiddleware"]
        assert cfg.mcp_servers["srv"].command == "echo"

    def test_app_config_loads_extensions_from_json_with_yaml_override(self, tmp_path, monkeypatch):
        """Extensions load from extensions_config.json; explicit ``extensions`` fields in config.yaml override per-field."""
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(
            json.dumps({"mcpServers": {}, "skills": {}, "middlewares": ["json_module:JsonMiddleware"]}),
            encoding="utf-8",
        )
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                    "extensions": {"middlewares": ["yaml_module:YamlMiddleware"]},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

        app_cfg = AppConfig.from_file(str(config_path))

        # config.yaml explicitly declares `middlewares`, so it wins over the
        # JSON value (replace-per-field, part of the AppConfig hot-reload
        # contract). Fields not declared in config.yaml keep the JSON value.
        assert app_cfg.extensions.middlewares == ["yaml_module:YamlMiddleware"]

    def test_app_config_loads_extensions_from_json_when_yaml_silent(self, tmp_path, monkeypatch):
        """Without an ``extensions`` section in config.yaml, extensions_config.json is the source of truth."""
        extensions_path = tmp_path / "extensions_config.json"
        extensions_path.write_text(
            json.dumps({"mcpServers": {}, "skills": {}, "middlewares": ["json_module:JsonMiddleware"]}),
            encoding="utf-8",
        )
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

        app_cfg = AppConfig.from_file(str(config_path))

        assert app_cfg.extensions.middlewares == ["json_module:JsonMiddleware"]

    def test_app_config_extensions_field_defaults(self):
        """AppConfig.extensions defaults to an empty ExtensionsConfig."""
        cfg_data = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}

        app_cfg = AppConfig.model_validate(cfg_data)

        assert app_cfg.extensions.enabled is True
        assert app_cfg.extensions.middlewares == []
