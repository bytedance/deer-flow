"""Unit tests for checkpointer config and singleton factory."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from deerflow.agents.checkpointer import get_checkpointer, reset_checkpointer
from deerflow.config.checkpointer_config import (
    CheckpointerConfig,
    get_checkpointer_config,
    load_checkpointer_config_from_dict,
    set_checkpointer_config,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset singleton state before each test."""
    set_checkpointer_config(None)
    reset_checkpointer()
    yield
    set_checkpointer_config(None)
    reset_checkpointer()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestCheckpointerConfig:
    def test_load_memory_config(self):
        load_checkpointer_config_from_dict({"type": "memory"})
        config = get_checkpointer_config()
        assert config is not None
        assert config.type == "memory"
        assert config.connection_string is None

    def test_load_sqlite_config(self):
        load_checkpointer_config_from_dict({"type": "sqlite", "connection_string": "/tmp/test.db"})
        config = get_checkpointer_config()
        assert config is not None
        assert config.type == "sqlite"
        assert config.connection_string == "/tmp/test.db"

    def test_load_postgres_config(self):
        load_checkpointer_config_from_dict({"type": "postgres", "connection_string": "postgresql://localhost/db"})
        config = get_checkpointer_config()
        assert config is not None
        assert config.type == "postgres"
        assert config.connection_string == "postgresql://localhost/db"

    def test_default_connection_string_is_none(self):
        config = CheckpointerConfig(type="memory")
        assert config.connection_string is None

    def test_set_config_to_none(self):
        load_checkpointer_config_from_dict({"type": "memory"})
        set_checkpointer_config(None)
        assert get_checkpointer_config() is None

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            load_checkpointer_config_from_dict({"type": "unknown"})


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestGetCheckpointer:
    def test_returns_in_memory_saver_when_not_configured(self):
        """get_checkpointer should return InMemorySaver when not configured."""
        from langgraph.checkpoint.memory import InMemorySaver

        cp = get_checkpointer()
        assert cp is not None
        assert isinstance(cp, InMemorySaver)

    def test_memory_returns_in_memory_saver(self):
        load_checkpointer_config_from_dict({"type": "memory"})
        from langgraph.checkpoint.memory import InMemorySaver

        cp = get_checkpointer()
        assert isinstance(cp, InMemorySaver)

    def test_memory_singleton(self):
        load_checkpointer_config_from_dict({"type": "memory"})
        cp1 = get_checkpointer()
        cp2 = get_checkpointer()
        assert cp1 is cp2

    def test_reset_clears_singleton(self):
        load_checkpointer_config_from_dict({"type": "memory"})
        cp1 = get_checkpointer()
        reset_checkpointer()
        cp2 = get_checkpointer()
        assert cp1 is not cp2

    def test_sqlite_raises_when_package_missing(self):
        load_checkpointer_config_from_dict({"type": "sqlite", "connection_string": "/tmp/test.db"})
        with patch.dict(sys.modules, {"langgraph.checkpoint.sqlite": None}):
            reset_checkpointer()
            with pytest.raises(ImportError, match="langgraph-checkpoint-sqlite"):
                get_checkpointer()

    def test_postgres_raises_when_package_missing(self):
        load_checkpointer_config_from_dict({"type": "postgres", "connection_string": "postgresql://localhost/db"})
        with patch.dict(sys.modules, {"langgraph.checkpoint.postgres": None}):
            reset_checkpointer()
            with pytest.raises(ImportError, match="langgraph-checkpoint-postgres"):
                get_checkpointer()

    def test_postgres_raises_when_connection_string_missing(self):
        load_checkpointer_config_from_dict({"type": "postgres"})
        mock_saver = MagicMock()
        mock_module = MagicMock()
        mock_module.PostgresSaver = mock_saver
        with patch.dict(sys.modules, {"langgraph.checkpoint.postgres": mock_module}):
            reset_checkpointer()
            with pytest.raises(ValueError, match="connection_string is required"):
                get_checkpointer()

    def test_sqlite_creates_saver(self):
        """SQLite checkpointer is created when package is available."""
        load_checkpointer_config_from_dict({"type": "sqlite", "connection_string": "/tmp/test.db"})

        mock_saver_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_saver_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_saver_cls = MagicMock()
        mock_saver_cls.from_conn_string = MagicMock(return_value=mock_cm)

        mock_module = MagicMock()
        mock_module.SqliteSaver = mock_saver_cls

        with patch.dict(sys.modules, {"langgraph.checkpoint.sqlite": mock_module}):
            reset_checkpointer()
            cp = get_checkpointer()

        assert cp is mock_saver_instance
        mock_saver_cls.from_conn_string.assert_called_once()
        mock_saver_instance.setup.assert_called_once()

    def test_postgres_creates_saver(self):
        """Postgres checkpointer is created when packages are available."""
        load_checkpointer_config_from_dict({"type": "postgres", "connection_string": "postgresql://localhost/db"})

        mock_saver_instance = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_saver_instance)
        mock_cm.__exit__ = MagicMock(return_value=False)

        mock_saver_cls = MagicMock()
        mock_saver_cls.from_conn_string = MagicMock(return_value=mock_cm)

        mock_pg_module = MagicMock()
        mock_pg_module.PostgresSaver = mock_saver_cls

        with patch.dict(sys.modules, {"langgraph.checkpoint.postgres": mock_pg_module}):
            reset_checkpointer()
            cp = get_checkpointer()

        assert cp is mock_saver_instance
        mock_saver_cls.from_conn_string.assert_called_once_with("postgresql://localhost/db")
        mock_saver_instance.setup.assert_called_once()


# ---------------------------------------------------------------------------
# app_config.py integration
# ---------------------------------------------------------------------------


class TestAppConfigLoadsCheckpointer:
    def test_load_checkpointer_section(self):
        """load_checkpointer_config_from_dict populates the global config."""
        set_checkpointer_config(None)
        load_checkpointer_config_from_dict({"type": "memory"})
        cfg = get_checkpointer_config()
        assert cfg is not None
        assert cfg.type == "memory"


# ---------------------------------------------------------------------------
# DeerFlowClient falls back to config checkpointer
# ---------------------------------------------------------------------------


class TestClientCheckpointerFallback:
    def test_client_uses_config_checkpointer_when_none_provided(self):
        """DeerFlowClient._ensure_agent falls back to get_checkpointer() when checkpointer=None."""
        from langgraph.checkpoint.memory import InMemorySaver

        from deerflow.client import DeerFlowClient

        load_checkpointer_config_from_dict({"type": "memory"})

        captured_kwargs = {}

        def fake_create_agent(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        model_mock = MagicMock()
        config_mock = MagicMock()
        config_mock.models = [model_mock]
        config_mock.get_model_config.return_value = MagicMock(supports_vision=False)
        config_mock.checkpointer = None

        with (
            patch("deerflow.client.get_app_config", return_value=config_mock),
            patch("deerflow.client.create_agent", side_effect=fake_create_agent),
            patch("deerflow.client.create_chat_model", return_value=MagicMock()),
            patch("deerflow.client._build_middlewares", return_value=[]),
            patch("deerflow.client.apply_prompt_template", return_value=""),
            patch("deerflow.client.DeerFlowClient._get_tools", return_value=[]),
        ):
            client = DeerFlowClient(checkpointer=None)
            config = client._get_runnable_config("test-thread")
            client._ensure_agent(config)

        assert "checkpointer" in captured_kwargs
        assert isinstance(captured_kwargs["checkpointer"], InMemorySaver)

    def test_client_explicit_checkpointer_takes_precedence(self):
        """An explicitly provided checkpointer is used even when config checkpointer is set."""
        from deerflow.client import DeerFlowClient

        load_checkpointer_config_from_dict({"type": "memory"})

        explicit_cp = MagicMock()
        captured_kwargs = {}

        def fake_create_agent(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        model_mock = MagicMock()
        config_mock = MagicMock()
        config_mock.models = [model_mock]
        config_mock.get_model_config.return_value = MagicMock(supports_vision=False)
        config_mock.checkpointer = None

        with (
            patch("deerflow.client.get_app_config", return_value=config_mock),
            patch("deerflow.client.create_agent", side_effect=fake_create_agent),
            patch("deerflow.client.create_chat_model", return_value=MagicMock()),
            patch("deerflow.client._build_middlewares", return_value=[]),
            patch("deerflow.client.apply_prompt_template", return_value=""),
            patch("deerflow.client.DeerFlowClient._get_tools", return_value=[]),
        ):
            client = DeerFlowClient(checkpointer=explicit_cp)
            config = client._get_runnable_config("test-thread")
            client._ensure_agent(config)

        assert captured_kwargs["checkpointer"] is explicit_cp
