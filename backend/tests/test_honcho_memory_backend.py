"""Tests for the Honcho memory backend (config + manager)."""

from __future__ import annotations

import pytest

from deerflow.agents.memory.backends.honcho.config import HonchoConfig, sanitize_id


class TestHonchoConfig:
    def test_defaults(self):
        cfg = HonchoConfig.from_backend_config(None)
        assert cfg.base_url == "http://localhost:8000"
        assert cfg.api_key is None
        assert cfg.workspace_prefix == "deerflow-u-"
        assert cfg.workspace_overrides == {}
        assert cfg.user_peer_overrides == {}
        assert cfg.assistant_peer == "deerflow"
        assert cfg.message_char_limit == 8000
        assert cfg.max_injection_chars == 6000
        assert cfg.read_fail_closed is False

    def test_parses_knobs_and_ignores_unknown_keys(self):
        cfg = HonchoConfig.from_backend_config(
            {
                "base_url": "https://api.honcho.dev/",
                "api_key": "sk-test",
                "workspace_prefix": "df-",
                "workspace_overrides": {"user-1": "shared"},
                "user_peer_overrides": {"user-1": "alice"},
                "assistant_peer": "deer",
                "failure_policy": {"read": "fail_closed"},
                "storage_path": "/tmp/x",
                "unknown_key": True,
            }
        )
        assert cfg.base_url == "https://api.honcho.dev"  # trailing slash stripped
        assert cfg.workspace_overrides == {"user-1": "shared"}
        assert cfg.user_peer_overrides == {"user-1": "alice"}
        assert cfg.read_fail_closed is True
        assert cfg.storage_path == "/tmp/x"

    def test_http_with_api_key_requires_opt_in(self):
        with pytest.raises(ValueError, match="allow_insecure_http"):
            HonchoConfig.from_backend_config({"base_url": "http://internal:8000", "api_key": "sk-x"})
        cfg = HonchoConfig.from_backend_config({"base_url": "http://internal:8000", "api_key": "sk-x", "allow_insecure_http": True})
        assert cfg.api_key == "sk-x"

    def test_http_without_api_key_is_fine(self):
        cfg = HonchoConfig.from_backend_config({"base_url": "http://host.docker.internal:8000"})
        assert cfg.api_key is None


class TestSanitizeId:
    def test_passthrough_and_cleanup(self):
        assert sanitize_id("user_1-ok") == "user_1-ok"
        assert sanitize_id("weird id@example.com") == "weird-id-example-com"
        assert len(sanitize_id("x" * 200)) == 64
        assert sanitize_id("") == ""
