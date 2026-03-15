"""Unit tests for the PTC proxy endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """Create a test client for the Gateway app."""
    from src.gateway.app import create_app

    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _set_ptc_secret(monkeypatch):
    """Set a deterministic PTC secret for all tests."""
    monkeypatch.setenv("PTC_SECRET", "test-ptc-secret-for-unit-tests")


def _make_valid_token(thread_id: str = "test-thread") -> str:
    """Create a valid session token for testing."""
    from src.ptc.session_token import create_session_token

    return create_session_token(thread_id)


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestPTCAuthentication:
    def test_valid_token(self, client):
        """Valid token should not get 401."""
        token = _make_valid_token()

        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.ainvoke = AsyncMock(return_value="result data")

        mock_client_instance = AsyncMock()
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.gateway.routers.ptc.validate_session_token", return_value="test-thread"),
            patch("src.config.extensions_config.ExtensionsConfig.from_file"),
            patch("src.mcp.client.build_servers_config", return_value={"test_server": {"transport": "stdio"}}),
            patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        ):
            resp = client.post(
                "/api/ptc/call",
                json={
                    "token": token,
                    "server_name": "test_server",
                    "tool_name": "test_tool",
                    "arguments": {},
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["result"] == "result data"

    def test_invalid_token_returns_401(self, client):
        """Invalid token should return 401."""
        resp = client.post(
            "/api/ptc/call",
            json={
                "token": "invalid-token",
                "server_name": "server",
                "tool_name": "tool",
                "arguments": {},
            },
        )
        assert resp.status_code == 401
        assert "Invalid or expired" in resp.json()["detail"]

    def test_expired_token_returns_401(self, client):
        """Expired token should return 401."""
        import base64
        import hashlib
        import hmac
        import json
        import time

        # Create a token that expired 2 hours ago
        secret = "test-ptc-secret-for-unit-tests"
        payload = {"thread_id": "t", "iat": int(time.time()) - 7200}
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
        payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
        sig_b64 = base64.urlsafe_b64encode(sig).decode("ascii")
        token = f"{payload_b64}.{sig_b64}"

        resp = client.post(
            "/api/ptc/call",
            json={"token": token, "server_name": "s", "tool_name": "t", "arguments": {}},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Server / tool resolution
# ---------------------------------------------------------------------------


class TestPTCServerResolution:
    def test_unknown_server_returns_404(self, client):
        """Unknown server should return 404."""
        with (
            patch("src.gateway.routers.ptc.validate_session_token", return_value="t"),
            patch("src.config.extensions_config.ExtensionsConfig.from_file"),
            patch("src.mcp.client.build_servers_config", return_value={"postgres": {}}),
        ):
            resp = client.post(
                "/api/ptc/call",
                json={
                    "token": _make_valid_token(),
                    "server_name": "nonexistent",
                    "tool_name": "query",
                    "arguments": {},
                },
            )

        assert resp.status_code == 404
        assert "Unknown MCP server" in resp.json()["detail"]

    def test_unknown_tool_returns_404(self, client):
        """Unknown tool on a known server should return 404."""
        mock_tool = MagicMock()
        mock_tool.name = "real_tool"

        mock_client_instance = AsyncMock()
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.gateway.routers.ptc.validate_session_token", return_value="t"),
            patch("src.config.extensions_config.ExtensionsConfig.from_file"),
            patch("src.mcp.client.build_servers_config", return_value={"server": {"transport": "stdio"}}),
            patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        ):
            resp = client.post(
                "/api/ptc/call",
                json={
                    "token": _make_valid_token(),
                    "server_name": "server",
                    "tool_name": "nonexistent_tool",
                    "arguments": {},
                },
            )

        assert resp.status_code == 404
        assert "Unknown tool" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Tool execution errors
# ---------------------------------------------------------------------------


class TestPTCToolExecution:
    def test_tool_execution_error(self, client):
        """Tool execution errors should return success=False with error message."""
        mock_tool = MagicMock()
        mock_tool.name = "failing_tool"
        mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("Database connection failed"))

        mock_client_instance = AsyncMock()
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.gateway.routers.ptc.validate_session_token", return_value="t"),
            patch("src.config.extensions_config.ExtensionsConfig.from_file"),
            patch("src.mcp.client.build_servers_config", return_value={"server": {"transport": "stdio"}}),
            patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        ):
            resp = client.post(
                "/api/ptc/call",
                json={
                    "token": _make_valid_token(),
                    "server_name": "server",
                    "tool_name": "failing_tool",
                    "arguments": {},
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Database connection failed" in data["error"]

    def test_successful_tool_with_arguments(self, client):
        """Tool should receive arguments and return result."""
        mock_tool = MagicMock()
        mock_tool.name = "query"
        mock_tool.ainvoke = AsyncMock(return_value='[{"id": 1, "name": "test"}]')

        mock_client_instance = AsyncMock()
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("src.gateway.routers.ptc.validate_session_token", return_value="t"),
            patch("src.config.extensions_config.ExtensionsConfig.from_file"),
            patch("src.mcp.client.build_servers_config", return_value={"pg": {"transport": "stdio"}}),
            patch("langchain_mcp_adapters.client.MultiServerMCPClient", return_value=mock_client_instance),
        ):
            resp = client.post(
                "/api/ptc/call",
                json={
                    "token": _make_valid_token(),
                    "server_name": "pg",
                    "tool_name": "query",
                    "arguments": {"sql": "SELECT * FROM users"},
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "test" in data["result"]

        # Verify arguments were passed through
        mock_tool.ainvoke.assert_called_once_with({"sql": "SELECT * FROM users"})
