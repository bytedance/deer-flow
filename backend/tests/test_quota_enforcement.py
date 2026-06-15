"""Regression tests for quota enforcement in run creation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.gateway.services import start_run
from deerflow.config.cost_config import BudgetConfigModel, CostConfig
from deerflow.config.tenant_storage import TenantConfig


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request."""
    request = MagicMock()
    request.app.state.stream_bridge = MagicMock()
    request.app.state.run_manager = MagicMock()
    request.app.state.run_context = MagicMock()
    request.app.state.run_context.thread_store = AsyncMock()
    request.app.state.tenant_store = AsyncMock()
    return request


@pytest.fixture
def mock_body():
    """Create a mock RunCreateRequest."""
    body = MagicMock()
    body.assistant_id = "lead_agent"
    body.input = {"messages": []}
    body.config = None
    body.metadata = {}
    body.on_disconnect = "cancel"
    body.multitask_strategy = "reject"
    body.stream_mode = None
    body.stream_subgraphs = False
    body.interrupt_before = None
    body.interrupt_after = None
    body.context = None
    return body


@pytest.fixture
def tenant_config():
    """Create a test tenant config with quotas."""
    return TenantConfig(
        tenant_id="test-tenant",
        name="Test Tenant",
        daily_quota_usd=10.0,
        monthly_quota_usd=100.0,
        is_active=True,
    )


@pytest.fixture
def cost_config_enabled():
    """Create a cost config with enforcement enabled."""
    return CostConfig(
        enabled=True,
        budget=BudgetConfigModel(
            default_daily_limit_usd=50.0,
            default_monthly_limit_usd=1000.0,
            action_on_exceed="block",
        ),
    )


@pytest.fixture
def cost_config_disabled():
    """Create a cost config with enforcement disabled."""
    return CostConfig(enabled=False)


class TestQuotaEnforcement:
    """Test quota enforcement in run creation."""

    @pytest.mark.asyncio
    async def test_run_blocked_when_daily_quota_exceeded(
        self, mock_request, mock_body, tenant_config, cost_config_enabled
    ):
        """Test that run creation is blocked when daily quota is exceeded."""
        # Setup: tenant has used 15 USD today, quota is 10 USD
        mock_request.app.state.tenant_store.get = AsyncMock(return_value=tenant_config)

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_enabled), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_usage_storage") as mock_get_storage:

            mock_storage = MagicMock()
            mock_storage.get_today_total.return_value = 15.0  # Exceeded
            mock_storage.get_current_month_total.return_value = 50.0  # Within limit
            mock_get_storage.return_value = mock_storage

            with pytest.raises(HTTPException) as exc_info:
                await start_run(mock_body, "test-thread", mock_request)

            assert exc_info.value.status_code == 429
            detail = exc_info.value.detail
            assert detail["code"] == "quota_daily_exceeded"
            assert detail["used"] == 15.0
            assert detail["limit"] == 10.0
            assert detail["period"] == "daily"

    @pytest.mark.asyncio
    async def test_run_blocked_when_monthly_quota_exceeded(
        self, mock_request, mock_body, tenant_config, cost_config_enabled
    ):
        """Test that run creation is blocked when monthly quota is exceeded."""
        # Setup: tenant has used 150 USD this month, quota is 100 USD
        mock_request.app.state.tenant_store.get = AsyncMock(return_value=tenant_config)

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_enabled), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_usage_storage") as mock_get_storage:

            mock_storage = MagicMock()
            mock_storage.get_today_total.return_value = 5.0  # Within daily limit
            mock_storage.get_current_month_total.return_value = 150.0  # Exceeded
            mock_get_storage.return_value = mock_storage

            with pytest.raises(HTTPException) as exc_info:
                await start_run(mock_body, "test-thread", mock_request)

            assert exc_info.value.status_code == 429
            detail = exc_info.value.detail
            assert detail["code"] == "quota_monthly_exceeded"
            assert detail["used"] == 150.0
            assert detail["limit"] == 100.0
            assert detail["period"] == "monthly"

    @pytest.mark.asyncio
    async def test_run_allowed_when_within_quota(
        self, mock_request, mock_body, tenant_config, cost_config_enabled
    ):
        """Test that run creation is allowed when within quota."""
        # Setup: tenant has used 5 USD today and 50 USD this month
        mock_request.app.state.tenant_store.get = AsyncMock(return_value=tenant_config)
        mock_request.app.state.run_manager.create_or_reject = AsyncMock(
            return_value=MagicMock(run_id="test-run", status=MagicMock(value="pending"))
        )

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_enabled), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_effective_user_id", return_value="test-user"), \
             patch("app.gateway.services.get_usage_storage") as mock_get_storage, \
             patch("app.gateway.services.resolve_agent_factory"), \
             patch("app.gateway.services.asyncio.create_task"):

            mock_storage = MagicMock()
            mock_storage.get_today_total.return_value = 5.0  # Within daily limit
            mock_storage.get_current_month_total.return_value = 50.0  # Within monthly limit
            mock_get_storage.return_value = mock_storage

            # Should not raise an exception
            result = await start_run(mock_body, "test-thread", mock_request)
            assert result is not None

    @pytest.mark.asyncio
    async def test_run_allowed_when_cost_tracking_disabled(
        self, mock_request, mock_body, tenant_config, cost_config_disabled
    ):
        """Test that run creation is allowed when cost tracking is disabled."""
        mock_request.app.state.tenant_store.get = AsyncMock(return_value=tenant_config)
        mock_request.app.state.run_manager.create_or_reject = AsyncMock(
            return_value=MagicMock(run_id="test-run", status=MagicMock(value="pending"))
        )

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_disabled), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_effective_user_id", return_value="test-user"), \
             patch("app.gateway.services.resolve_agent_factory"), \
             patch("app.gateway.services.asyncio.create_task"):

            # Should not raise an exception even if quota would be exceeded
            result = await start_run(mock_body, "test-thread", mock_request)
            assert result is not None

    @pytest.mark.asyncio
    async def test_run_allowed_when_action_is_warn(
        self, mock_request, mock_body, tenant_config
    ):
        """Test that run creation is allowed when action_on_exceed is 'warn'."""
        cost_config_warn = CostConfig(
            enabled=True,
            budget=BudgetConfigModel(
                default_daily_limit_usd=50.0,
                default_monthly_limit_usd=1000.0,
                action_on_exceed="warn",  # Only warn, don't block
            ),
        )

        mock_request.app.state.tenant_store.get = AsyncMock(return_value=tenant_config)
        mock_request.app.state.run_manager.create_or_reject = AsyncMock(
            return_value=MagicMock(run_id="test-run", status=MagicMock(value="pending"))
        )

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_warn), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_effective_user_id", return_value="test-user"), \
             patch("app.gateway.services.get_usage_storage") as mock_get_storage, \
             patch("app.gateway.services.resolve_agent_factory"), \
             patch("app.gateway.services.asyncio.create_task"):

            mock_storage = MagicMock()
            mock_storage.get_today_total.return_value = 15.0  # Exceeded
            mock_storage.get_current_month_total.return_value = 50.0
            mock_get_storage.return_value = mock_storage

            # Should not raise an exception because action is 'warn'
            result = await start_run(mock_body, "test-thread", mock_request)
            assert result is not None

    @pytest.mark.asyncio
    async def test_run_allowed_when_quota_check_fails(
        self, mock_request, mock_body, tenant_config, cost_config_enabled
    ):
        """Test that run creation is allowed when quota check fails (fail-open)."""
        # Simulate tenant_store.get() raising an exception
        mock_request.app.state.tenant_store.get = AsyncMock(side_effect=Exception("Database error"))
        mock_request.app.state.run_manager.create_or_reject = AsyncMock(
            return_value=MagicMock(run_id="test-run", status=MagicMock(value="pending"))
        )

        with patch("app.gateway.services.get_cost_config", return_value=cost_config_enabled), \
             patch("app.gateway.services.get_current_tenant_id", return_value="test-tenant"), \
             patch("app.gateway.services.get_effective_user_id", return_value="test-user"), \
             patch("app.gateway.services.resolve_agent_factory"), \
             patch("app.gateway.services.asyncio.create_task"):

            # Should not raise an exception (fail-open behavior)
            result = await start_run(mock_body, "test-thread", mock_request)
            assert result is not None
