"""Unit tests for user token passthrough through the integration layer.

Covers:
- user_context.py: set/get/reset access_token ContextVar
- RpcClient.call_raw(): extra_headers merge and Content-Type/Accept protection
- IntegrationSystemConfig: auth_mode field defaults and validation
- InsAdapter._build_extra_headers(): user_token mode vs static mode
- SmsAdapter._build_headers(): Bearer vs X-API-Key based on auth_mode
- Tool methods forward token to AuthContext
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.adapters.ins.adapter import InsAdapter
from deerflow.integrations.adapters.sms.adapter import SmsAdapter
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.runtime.user_context import (
    get_access_token,
    reset_access_token,
    set_access_token,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ins_config(**overrides) -> IntegrationSystemConfig:
    defaults = {
        "system_key": "ins_prod",
        "system_type": "ins",
        "display_name": "InS Production",
        "base_url": "http://ins.example.com",
        "auth_type": "bearer",
    }
    defaults.update(overrides)
    return IntegrationSystemConfig(**defaults)


def _make_sms_config(**overrides) -> IntegrationSystemConfig:
    defaults = {
        "system_key": "sms_prod",
        "system_type": "sms",
        "display_name": "SMS Production",
        "base_url": "http://sms.example.com",
        "auth_type": "api_key",
        "secret_ref": "static-api-key-123",
    }
    defaults.update(overrides)
    return IntegrationSystemConfig(**defaults)


# ---------------------------------------------------------------------------
# 1. user_context.py: access_token ContextVar
# ---------------------------------------------------------------------------


class TestAccessTokenContextVar:
    def test_default_is_none(self):
        assert get_access_token() is None

    def test_set_and_get(self):
        token = set_access_token("my-access-token")
        try:
            assert get_access_token() == "my-access-token"
        finally:
            reset_access_token(token)

    def test_reset_restores_previous(self):
        token1 = set_access_token("first")
        try:
            token2 = set_access_token("second")
            try:
                assert get_access_token() == "second"
            finally:
                reset_access_token(token2)
            assert get_access_token() == "first"
        finally:
            reset_access_token(token1)

    def test_set_none_clears(self):
        token1 = set_access_token("value")
        try:
            token2 = set_access_token(None)
            try:
                assert get_access_token() is None
            finally:
                reset_access_token(token2)
            assert get_access_token() == "value"
        finally:
            reset_access_token(token1)


# ---------------------------------------------------------------------------
# 2. IntegrationSystemConfig: auth_mode field
# ---------------------------------------------------------------------------


class TestAuthModeConfig:
    def test_default_auth_mode_is_static(self):
        config = _make_ins_config()
        assert config.auth_mode == "static"

    def test_user_token_auth_mode(self):
        config = _make_ins_config(auth_mode="user_token")
        assert config.auth_mode == "user_token"

    def test_invalid_auth_mode_rejected(self):
        with pytest.raises(Exception):
            _make_ins_config(auth_mode="invalid")


# ---------------------------------------------------------------------------
# 3. InsAdapter._build_extra_headers()
# ---------------------------------------------------------------------------


class TestInsAdapterExtraHeaders:
    def test_static_mode_returns_none(self):
        config = _make_ins_config(auth_mode="static")
        adapter = InsAdapter(config)
        auth = AuthContext(tenant_id="t1", user_id="u1", token="user-token-123")
        assert adapter._build_extra_headers(auth) is None

    def test_user_token_mode_with_token(self):
        config = _make_ins_config(auth_mode="user_token")
        adapter = InsAdapter(config)
        auth = AuthContext(tenant_id="t1", user_id="u1", token="user-token-123")
        headers = adapter._build_extra_headers(auth)
        assert headers == {"Authorization": "Bearer user-token-123"}

    def test_user_token_mode_without_token(self):
        config = _make_ins_config(auth_mode="user_token")
        adapter = InsAdapter(config)
        auth = AuthContext(tenant_id="t1", user_id="u1", token=None)
        assert adapter._build_extra_headers(auth) is None

    def test_user_token_mode_with_empty_token(self):
        config = _make_ins_config(auth_mode="user_token")
        adapter = InsAdapter(config)
        auth = AuthContext(tenant_id="t1", user_id="u1", token="")
        assert adapter._build_extra_headers(auth) is None


# ---------------------------------------------------------------------------
# 4. SmsAdapter._build_headers()
# ---------------------------------------------------------------------------


class TestSmsAdapterBuildHeaders:
    def test_static_mode_uses_api_key(self):
        config = _make_sms_config(auth_mode="static")
        adapter = SmsAdapter(config)
        adapter._api_key = "resolved-key"
        headers = adapter._build_headers()
        assert headers == {"Accept": "application/json", "X-API-Key": "resolved-key"}

    def test_user_token_mode_with_token_uses_bearer(self):
        config = _make_sms_config(auth_mode="user_token")
        adapter = SmsAdapter(config)
        adapter._api_key = "resolved-key"
        auth = AuthContext(tenant_id="t1", user_id="u1", token="user-token-abc")
        headers = adapter._build_headers(auth)
        assert headers == {"Accept": "application/json", "Authorization": "Bearer user-token-abc"}

    def test_user_token_mode_without_token_falls_back_to_api_key(self):
        config = _make_sms_config(auth_mode="user_token")
        adapter = SmsAdapter(config)
        adapter._api_key = "resolved-key"
        auth = AuthContext(tenant_id="t1", user_id="u1", token=None)
        headers = adapter._build_headers(auth)
        assert headers == {"Accept": "application/json", "X-API-Key": "resolved-key"}

    def test_user_token_mode_no_auth_context_falls_back(self):
        config = _make_sms_config(auth_mode="user_token")
        adapter = SmsAdapter(config)
        adapter._api_key = "resolved-key"
        headers = adapter._build_headers()
        assert headers == {"Accept": "application/json", "X-API-Key": "resolved-key"}

    def test_static_mode_ignores_token(self):
        config = _make_sms_config(auth_mode="static")
        adapter = SmsAdapter(config)
        adapter._api_key = "resolved-key"
        auth = AuthContext(tenant_id="t1", user_id="u1", token="should-be-ignored")
        headers = adapter._build_headers(auth)
        assert "Authorization" not in headers
        assert headers["X-API-Key"] == "resolved-key"


# ---------------------------------------------------------------------------
# 5. RpcClient.call_raw() extra_headers merge
# ---------------------------------------------------------------------------


class TestRpcExtraHeaders:
    def test_extra_headers_merged(self):
        from deerflow.config.rpc_config import RpcServiceConfig
        from deerflow.rpc.rpc_client import RpcClient

        client = RpcClient()
        service = RpcServiceConfig(
            name="test-svc",
            base_url="http://test.example.com",
            auth_headers={"X-Service-Key": "svc-key"},
        )

        with patch.object(client, "_get_service", return_value=service):
            headers = client._resolve_auth_headers(service)
            extra = {"Authorization": "Bearer user-token"}
            protected = {"content-type", "accept"}
            for k, v in extra.items():
                if k.lower() not in protected:
                    headers[k] = v

        assert headers == {
            "X-Service-Key": "svc-key",
            "Authorization": "Bearer user-token",
        }

    def test_extra_headers_cannot_override_content_type(self):
        from deerflow.config.rpc_config import RpcServiceConfig
        from deerflow.rpc.rpc_client import RpcClient

        client = RpcClient()
        service = RpcServiceConfig(
            name="test-svc",
            base_url="http://test.example.com",
        )

        headers = client._resolve_auth_headers(service)
        extra = {"Content-Type": "text/plain", "Authorization": "Bearer token"}
        protected = {"content-type", "accept"}
        for k, v in extra.items():
            if k.lower() not in protected:
                headers[k] = v

        assert "Content-Type" not in headers
        assert headers == {"Authorization": "Bearer token"}


# ---------------------------------------------------------------------------
# 6. Tool methods forward token to AuthContext
# ---------------------------------------------------------------------------


class TestToolsForwardToken:
    @pytest.mark.asyncio
    async def test_asset_catalog_forwards_token(self):
        from deerflow.integrations.services.asset_service import AssetService
        from deerflow.integrations.tools.asset_tools import AssetTools

        mock_service = MagicMock(spec=AssetService)
        mock_result = MagicMock()
        mock_result.data = []
        mock_service.get_catalog = AsyncMock(return_value=mock_result)

        tools = AssetTools(mock_service)
        await tools.get_asset_catalog(
            tenant_id="t1",
            user_id="u1",
            token="my-user-token",
        )

        call_args = mock_service.get_catalog.call_args
        auth_context = call_args[0][1]
        assert auth_context.token == "my-user-token"
        assert auth_context.tenant_id == "t1"
        assert auth_context.user_id == "u1"

    @pytest.mark.asyncio
    async def test_monitoring_trend_forwards_token(self):
        from datetime import datetime

        from deerflow.integrations.services.monitoring_service import MonitoringService
        from deerflow.integrations.tools.monitoring_tools import MonitoringTools

        mock_service = MagicMock(spec=MonitoringService)
        mock_series = MagicMock()
        mock_series.points = []
        mock_result = MagicMock()
        mock_result.data = mock_series
        mock_service.get_trend = AsyncMock(return_value=mock_result)

        tools = MonitoringTools(mock_service)
        now = datetime.now()
        await tools.get_trend_data(
            tenant_id="t1",
            user_id="u1",
            asset_id="A1",
            measurement_point_id="MP1",
            start_time=now,
            end_time=now,
            token="trend-token",
        )

        call_args = mock_service.get_trend.call_args
        auth_context = call_args[0][1]
        assert auth_context.token == "trend-token"

    @pytest.mark.asyncio
    async def test_health_assessment_forwards_token(self):
        from deerflow.integrations.services.assessment_service import AssessmentService
        from deerflow.integrations.tools.assessment_tools import AssessmentTools

        mock_service = MagicMock(spec=AssessmentService)
        mock_assessment = MagicMock()
        mock_assessment.overall_score = 85
        mock_assessment.overall_status = "healthy"
        mock_assessment.assessed_at = None
        mock_assessment.dimensions = {}
        mock_assessment.risk_items = []
        mock_result = MagicMock()
        mock_result.data = mock_assessment
        mock_service.get_health_assessment = AsyncMock(return_value=mock_result)

        tools = AssessmentTools(mock_service)
        await tools.get_health_assessment(
            tenant_id="t1",
            user_id="u1",
            asset_id="A1",
            token="assess-token",
        )

        call_args = mock_service.get_health_assessment.call_args
        auth_context = call_args[0][1]
        assert auth_context.token == "assess-token"


# ---------------------------------------------------------------------------
# 7. InsAdapter forwards extra_headers to bridge
# ---------------------------------------------------------------------------


class TestInsAdapterForwardsHeaders:
    @pytest.mark.asyncio
    async def test_catalog_passes_extra_headers_to_bridge(self):
        config = _make_ins_config(auth_mode="user_token")
        adapter = InsAdapter(config)
        bridge = MagicMock()
        bridge.get_machine_catalog = AsyncMock(return_value={"records": []})
        adapter._bridge = bridge

        auth = AuthContext(
            tenant_id="t1",
            user_id="u1",
            token="user-token-xyz",
            extra={"user_id": "100", "org_id": "200"},
        )
        await adapter.call("asset.catalog", MagicMock(), auth)

        call_kwargs = bridge.get_machine_catalog.call_args[1]
        assert call_kwargs["extra_headers"] == {"Authorization": "Bearer user-token-xyz"}

    @pytest.mark.asyncio
    async def test_catalog_no_headers_in_static_mode(self):
        config = _make_ins_config(auth_mode="static")
        adapter = InsAdapter(config)
        bridge = MagicMock()
        bridge.get_machine_catalog = AsyncMock(return_value={"records": []})
        adapter._bridge = bridge

        auth = AuthContext(
            tenant_id="t1",
            user_id="u1",
            token="user-token-xyz",
            extra={"user_id": "100", "org_id": "200"},
        )
        await adapter.call("asset.catalog", MagicMock(), auth)

        call_kwargs = bridge.get_machine_catalog.call_args[1]
        assert call_kwargs["extra_headers"] is None
