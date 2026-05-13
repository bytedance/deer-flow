"""End-to-end integration test for http_connector with mock external API."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.http_connector_config import HttpConnectorConfig
from deerflow.config.sandbox_config import SandboxConfig


def _make_config_with_connectors() -> AppConfig:
    """Create an AppConfig with a full set of data-platform connectors."""
    connectors = [
        HttpConnectorConfig(
            name="list_datasets",
            url="http://data-platform.internal/api/v1/datasets",
            method="GET",
            auth_type="bearer",
            auth_token_env="DATA_PLATFORM_TOKEN",
            timeout_seconds=30,
            max_response_bytes=524288,
            max_retries=1,
        ),
        HttpConnectorConfig(
            name="fetch_dataset",
            url="http://data-platform.internal/api/v1/datasets/query",
            method="POST",
            auth_type="bearer",
            auth_token_env="DATA_PLATFORM_TOKEN",
            timeout_seconds=60,
            max_response_bytes=1048576,
            max_retries=1,
        ),
        HttpConnectorConfig(
            name="dataset_schema",
            url="http://data-platform.internal/api/v1/datasets/schema",
            method="GET",
            auth_type="bearer",
            auth_token_env="DATA_PLATFORM_TOKEN",
            timeout_seconds=15,
            max_response_bytes=262144,
            max_retries=1,
        ),
    ]
    return AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={"default": connectors})


MOCK_DATASETS_RESPONSE = json.dumps({
    "datasets": [
        {"id": "ds_sales_2024", "name": "销售数据-2024", "description": "2024年全渠道销售明细", "row_count": 150000},
        {"id": "ds_inventory", "name": "库存数据", "description": "实时库存快照", "row_count": 8500},
        {"id": "ds_customers", "name": "客户画像", "description": "客户基础信息与标签", "row_count": 32000},
    ],
    "total": 3,
    "has_more": False,
}).encode()

MOCK_SCHEMA_RESPONSE = json.dumps({
    "dataset_id": "ds_sales_2024",
    "name": "销售数据-2024",
    "columns": [
        {"name": "order_id", "type": "string", "description": "订单编号", "nullable": False},
        {"name": "amount", "type": "float", "description": "订单金额", "nullable": False},
        {"name": "created_at", "type": "datetime", "description": "下单时间", "nullable": False},
        {"name": "channel", "type": "string", "description": "销售渠道", "nullable": True},
    ],
}).encode()

MOCK_FETCH_RESPONSE = json.dumps({
    "dataset_id": "ds_sales_2024",
    "columns": ["order_id", "amount", "created_at", "channel"],
    "rows": [
        {"order_id": "ORD001", "amount": 299.0, "created_at": "2024-01-15T10:30:00Z", "channel": "online"},
        {"order_id": "ORD002", "amount": 150.5, "created_at": "2024-01-15T11:00:00Z", "channel": "offline"},
        {"order_id": "ORD003", "amount": 1200.0, "created_at": "2024-01-16T09:15:00Z", "channel": "online"},
    ],
    "total_rows": 150000,
    "returned_rows": 3,
    "has_more": True,
}).encode()


class TestHttpConnectorE2E:
    """End-to-end flow: list datasets → get schema → fetch data."""

    @pytest.mark.asyncio
    async def test_full_flow_list_then_fetch(self, monkeypatch):
        """Simulate the complete Agent workflow: discover → select → fetch."""
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        monkeypatch.setenv("DATA_PLATFORM_TOKEN", "test-bearer-token")
        config = _make_config_with_connectors()

        # Step 1: List datasets
        list_response = httpx.Response(200, content=MOCK_DATASETS_RESPONSE, request=httpx.Request("GET", "http://data-platform.internal/api/v1/datasets"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=list_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "list_datasets", "params": {"limit": 50}})
            datasets = json.loads(result)
            assert len(datasets["datasets"]) == 3
            assert datasets["datasets"][0]["id"] == "ds_sales_2024"

        # Step 2: Get schema for selected dataset
        schema_response = httpx.Response(200, content=MOCK_SCHEMA_RESPONSE, request=httpx.Request("GET", "http://data-platform.internal/api/v1/datasets/schema"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=schema_response),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "dataset_schema", "params": {"dataset_id": "ds_sales_2024"}})
            schema = json.loads(result)
            assert schema["dataset_id"] == "ds_sales_2024"
            assert len(schema["columns"]) == 4

        # Step 3: Fetch data
        fetch_response = httpx.Response(200, content=MOCK_FETCH_RESPONSE, request=httpx.Request("POST", "http://data-platform.internal/api/v1/datasets/query"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=fetch_response),
        ):
            result = await http_connector_tool.ainvoke({
                "connector_name": "fetch_dataset",
                "body": {"dataset_id": "ds_sales_2024", "limit": 1000},
            })
            data = json.loads(result)
            assert data["returned_rows"] == 3
            assert data["rows"][0]["order_id"] == "ORD001"

    @pytest.mark.asyncio
    async def test_auth_header_sent(self, monkeypatch):
        """Verify bearer token is included in request headers."""
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        monkeypatch.setenv("DATA_PLATFORM_TOKEN", "my-secret-token")
        config = _make_config_with_connectors()

        captured_headers = {}

        async def mock_get(self, url, *, headers=None, params=None):
            captured_headers.update(headers or {})
            return httpx.Response(200, content=b'{"datasets": []}', request=httpx.Request("GET", url))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.get", mock_get),
        ):
            await http_connector_tool.ainvoke({"connector_name": "list_datasets"})
            assert captured_headers.get("Authorization") == "Bearer my-secret-token"

    @pytest.mark.asyncio
    async def test_graceful_degradation_no_config(self, monkeypatch):
        """When no connectors are configured, tool returns helpful error."""
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        config = AppConfig(sandbox=SandboxConfig(use="test"), http_connectors={})

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "list_datasets"})
            assert "Error" in result
            assert "No HTTP connectors configured" in result

    @pytest.mark.asyncio
    async def test_retry_then_success(self, monkeypatch):
        """Verify retry logic recovers from transient 503."""
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        monkeypatch.setenv("DATA_PLATFORM_TOKEN", "tok")
        config = _make_config_with_connectors()

        fail_resp = httpx.Response(503, content=b"Service Unavailable", request=httpx.Request("GET", "http://data-platform.internal/api/v1/datasets"))
        ok_resp = httpx.Response(200, content=MOCK_DATASETS_RESPONSE, request=httpx.Request("GET", "http://data-platform.internal/api/v1/datasets"))

        mock_get = AsyncMock(side_effect=[fail_resp, ok_resp])

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.get", mock_get),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "list_datasets"})
            data = json.loads(result)
            assert data["total"] == 3
            assert mock_get.call_count == 2

    @pytest.mark.asyncio
    async def test_large_response_truncation(self, monkeypatch):
        """Verify responses exceeding max_response_bytes are truncated."""
        from deerflow.tools.builtins.http_connector_tool import http_connector_tool

        monkeypatch.setenv("DATA_PLATFORM_TOKEN", "tok")
        config = _make_config_with_connectors()

        # dataset_schema connector has max_response_bytes=262144
        large_content = b"x" * 300000
        resp = httpx.Response(200, content=large_content, request=httpx.Request("GET", "http://data-platform.internal/api/v1/datasets/schema"))

        with (
            patch("deerflow.tools.builtins.http_connector_tool.get_current_tenant_id", return_value="default"),
            patch("deerflow.tools.builtins.http_connector_tool.get_app_config", return_value=config),
            patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=resp),
        ):
            result = await http_connector_tool.ainvoke({"connector_name": "dataset_schema", "params": {"dataset_id": "ds1"}})
            assert "[Response truncated due to size limit]" in result
            # Content should be truncated to max_response_bytes (262144) + truncation message
            content_part = result.replace("\n\n[Response truncated due to size limit]", "")
            assert len(content_part.encode()) <= 262144
