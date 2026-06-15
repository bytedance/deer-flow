"""Unit tests for SmsAdapter (Task 1.6.10)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from deerflow.integrations.adapters.base import AuthContext
from deerflow.integrations.adapters.sms.adapter import SmsAdapter
from deerflow.integrations.config import IntegrationSystemConfig
from deerflow.integrations.errors import (
    IntegrationAuthError,
    IntegrationError,
    IntegrationTimeoutError,
)


def _make_config(**overrides):
    defaults = {
        "system_key": "sms_prod",
        "system_type": "sms",
        "display_name": "Sms Production",
        "base_url": "http://sms.example.com",
        "auth_type": "api_key",
        "secret_ref": None,
    }
    defaults.update(overrides)
    return IntegrationSystemConfig(**defaults)


def _auth():
    return AuthContext(tenant_id="t1", user_id="u1")


class TestSmsAdapterLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_and_shutdown(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        assert adapter.system_key == "sms_prod"
        assert adapter.system_type == "sms"

        await adapter.initialize()
        assert adapter._http is not None

        await adapter.shutdown()
        assert adapter._http is None

    @pytest.mark.asyncio
    async def test_call_before_initialize_raises(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        with pytest.raises(IntegrationError, match="not initialized"):
            await adapter.call("health.assessment", {}, _auth())

    @pytest.mark.asyncio
    async def test_unsupported_capability_raises(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()
        try:
            with pytest.raises(IntegrationError, match="Unsupported capability"):
                await adapter.call("nonexistent.cap", {}, _auth())
        finally:
            await adapter.shutdown()


class TestSmsAdapterCapabilities:
    @pytest.mark.asyncio
    async def test_health_assessment(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "id": "A1",
                "equipmentId": "EQ1",
                "overallScore": 85.5,
                "overallStatus": "good",
                "summary": "Equipment in good condition",
                "dimensions": [
                    {"name": "vibration", "score": 90.0},
                    {"name": "temperature", "score": 80.0},
                ],
                "riskItems": [],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter._http, "get", return_value=mock_response):
            from deerflow.integrations.models.queries import HealthAssessmentQuery
            query = HealthAssessmentQuery(tenant_id="t1", asset_id="EQ1")
            result = await adapter.call("health.assessment", query, _auth())

            assert result is not None
            assert result.asset_id == "EQ1"
            assert result.overall_score == 85.5

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_anomaly_statistics(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "id": "S1",
                "equipmentId": "EQ1",
                "totalAnomalies": 15,
                "anomalyRate": 0.05,
                "bySeverity": [
                    {"severity": "high", "count": 3},
                    {"severity": "medium", "count": 7},
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter._http, "get", return_value=mock_response):
            from deerflow.integrations.models.queries import AnomalyStatsQuery
            query = AnomalyStatsQuery(tenant_id="t1", asset_id="EQ1")
            result = await adapter.call("health.anomaly_statistics", query, _auth())

            assert result is not None
            assert result.total_anomalies == 15

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_risk_ranking(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": {
                "id": "R1",
                "tenantId": "t1",
                "rankings": [
                    {
                        "equipmentId": "EQ1",
                        "equipmentName": "Pump A",
                        "riskLevel": "high",
                        "riskScore": 0.85,
                    },
                ],
            },
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter._http, "get", return_value=mock_response):
            from deerflow.integrations.models.queries import RiskRankingQuery
            query = RiskRankingQuery(tenant_id="t1")
            result = await adapter.call("health.risk_ranking", query, _auth())

            assert result is not None
            assert len(result.rankings) == 1
            assert result.rankings[0].risk_score == 0.85

        await adapter.shutdown()


class TestSmsAdapterHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_not_initialized(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        status = await adapter.health_check()
        assert status.healthy is False
        assert "not initialized" in status.message

    @pytest.mark.asyncio
    async def test_health_check_healthy(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch.object(adapter._http, "get", return_value=mock_response):
            status = await adapter.health_check()
            assert status.healthy is True

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        with patch.object(
            adapter._http, "get", side_effect=Exception("connection refused")
        ):
            status = await adapter.health_check()
            assert status.healthy is False
            assert "Health check failed" in status.message

        await adapter.shutdown()


class TestSmsAdapterErrorHandling:
    @pytest.mark.asyncio
    async def test_timeout_error(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        with patch.object(
            adapter._http, "get", side_effect=httpx.TimeoutException("timeout")
        ):
            from deerflow.integrations.models.queries import HealthAssessmentQuery
            query = HealthAssessmentQuery(tenant_id="t1", asset_id="EQ1")
            with pytest.raises(IntegrationTimeoutError):
                await adapter.call("health.assessment", query, _auth())

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_auth_error_401(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.status_code = 401
        error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(adapter._http, "get", side_effect=error):
            from deerflow.integrations.models.queries import HealthAssessmentQuery
            query = HealthAssessmentQuery(tenant_id="t1", asset_id="EQ1")
            with pytest.raises(IntegrationAuthError):
                await adapter.call("health.assessment", query, _auth())

        await adapter.shutdown()

    @pytest.mark.asyncio
    async def test_http_error_500(self):
        config = _make_config()
        adapter = SmsAdapter(config)
        await adapter.initialize()

        mock_response = MagicMock()
        mock_response.status_code = 500
        error = httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=MagicMock(),
            response=mock_response,
        )

        with patch.object(adapter._http, "get", side_effect=error):
            from deerflow.integrations.models.queries import HealthAssessmentQuery
            query = HealthAssessmentQuery(tenant_id="t1", asset_id="EQ1")
            with pytest.raises(IntegrationError, match="HTTP error"):
                await adapter.call("health.assessment", query, _auth())

        await adapter.shutdown()


class TestSmsTransforms:
    def test_transform_health_assessment(self):
        from deerflow.integrations.adapters.sms.transform import (
            transform_health_assessment,
        )

        raw = {
            "id": "A1",
            "equipmentId": "EQ1",
            "overallScore": 85.5,
            "overallStatus": "good",
            "summary": "OK",
            "dimensions": [{"name": "vibration", "score": 90.0}],
            "riskItems": [
                {
                    "id": "R1",
                    "equipmentId": "EQ1",
                    "riskType": "vibration",
                    "severity": "high",
                    "description": "High vibration detected",
                    "recommendation": "Check bearing",
                    "confidence": 0.95,
                },
            ],
        }
        result = transform_health_assessment(raw, "sms_prod")
        assert result.assessment_id == "A1"
        assert result.asset_id == "EQ1"
        assert result.overall_score == 85.5
        assert len(result.risk_items) == 1
        assert result.risk_items[0].confidence == 0.95
        assert result.provenance.source_system_type == "sms"

    def test_transform_anomaly_stats(self):
        from deerflow.integrations.adapters.sms.transform import transform_anomaly_stats

        raw = {
            "id": "S1",
            "equipmentId": "EQ1",
            "totalAnomalies": 15,
            "anomalyRate": 0.05,
            "bySeverity": [
                {"severity": "high", "count": 3},
                {"severity": "medium", "count": 7},
            ],
        }
        result = transform_anomaly_stats(raw, "sms_prod")
        assert result.total_anomalies == 15
        assert result.by_severity["high"] == 3

    def test_transform_risk_ranking(self):
        from deerflow.integrations.adapters.sms.transform import transform_risk_ranking

        raw = {
            "id": "R1",
            "rankings": [
                {
                    "equipmentId": "EQ1",
                    "equipmentName": "Pump A",
                    "riskLevel": "high",
                    "riskScore": 0.85,
                    "topRisks": ["vibration", "temperature"],
                },
            ],
        }
        result = transform_risk_ranking(raw, "sms_prod", "t1")
        assert len(result.rankings) == 1
        assert result.rankings[0].risk_score == 0.85
        assert result.rankings[0].top_risks == ("vibration", "temperature")
