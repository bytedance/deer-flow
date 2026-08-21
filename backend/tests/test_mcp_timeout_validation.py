"""Validate that MCP timeout fields reject non-positive, non-finite values."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.gateway.routers.mcp import McpServerConfigResponse
from deerflow.config.extensions_config import McpServerConfig


@pytest.mark.parametrize("cls", [McpServerConfig, McpServerConfigResponse])
class TestTimeoutValidation:
    """Shared timeout validation for runtime and gateway models."""

    def test_none_is_valid(self, cls):
        """None means 'no timeout' and must be accepted."""
        cfg = cls.model_validate({"session_init_timeout": None, "tool_call_timeout": None})
        assert cfg.session_init_timeout is None
        assert cfg.tool_call_timeout is None

    def test_positive_float_is_valid(self, cls):
        cfg = cls.model_validate({"session_init_timeout": 5.0, "tool_call_timeout": 10.0})
        assert cfg.session_init_timeout == 5.0
        assert cfg.tool_call_timeout == 10.0

    def test_zero_rejected(self, cls):
        with pytest.raises(ValidationError, match="Timeout must be positive"):
            cls.model_validate({"session_init_timeout": 0})

    def test_negative_rejected(self, cls):
        with pytest.raises(ValidationError, match="Timeout must be positive"):
            cls.model_validate({"session_init_timeout": -1.0})

    def test_nan_rejected(self, cls):
        with pytest.raises(ValidationError, match="NaN"):
            cls.model_validate({"tool_call_timeout": float("nan")})

    def test_inf_rejected(self, cls):
        with pytest.raises(ValidationError, match="finite"):
            cls.model_validate({"tool_call_timeout": float("inf")})

    def test_string_rejected(self, cls):
        with pytest.raises(ValidationError, match="must be a number"):
            cls.model_validate({"session_init_timeout": "thirty"})
