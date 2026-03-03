"""Unit tests for the Fiscal Data MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the fiscaldata MCP server directory to sys.path so we can import directly
FISCALDATA_DIR = str(Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "fiscaldata")
if FISCALDATA_DIR not in sys.path:
    sys.path.insert(0, FISCALDATA_DIR)

from api_client import FiscalDataAPIError, FiscalDataClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


SAMPLE_DEBT_RESPONSE = {
    "data": [
        {
            "record_date": "2024-12-31",
            "tot_pub_debt_out_amt": "36218064858041.87",
            "debt_held_public_amt": "28908004857498.89",
            "intragov_hold_amt": "7310060000542.98",
        },
        {
            "record_date": "2024-12-30",
            "tot_pub_debt_out_amt": "36167364858041.87",
            "debt_held_public_amt": "28857304857498.89",
            "intragov_hold_amt": "7310060000542.98",
        },
    ],
    "meta": {
        "count": 2,
        "labels": {"record_date": "Record Date"},
        "dataTypes": {"record_date": "DATE"},
        "dataFormats": {"record_date": "YYYY-MM-DD"},
        "total-count": 500,
        "total-pages": 5,
    },
    "links": {
        "self": "&page%5Bnumber%5D=1&page%5Bsize%5D=100",
        "first": "&page%5Bnumber%5D=1&page%5Bsize%5D=100",
        "last": "&page%5Bnumber%5D=5&page%5Bsize%5D=100",
        "next": "&page%5Bnumber%5D=2&page%5Bsize%5D=100",
    },
}

SAMPLE_INTEREST_RATES_RESPONSE = {
    "data": [
        {
            "record_date": "2024-12-31",
            "security_desc": "Treasury Bonds",
            "avg_interest_rate_amt": "3.875",
        },
        {
            "record_date": "2024-12-31",
            "security_desc": "Treasury Notes",
            "avg_interest_rate_amt": "2.750",
        },
    ],
    "meta": {"count": 2, "total-count": 2, "total-pages": 1},
    "links": {"self": "&page%5Bnumber%5D=1"},
}

SAMPLE_EXCHANGE_RATES_RESPONSE = {
    "data": [
        {
            "record_date": "2024-12-31",
            "country": "Japan",
            "currency": "Yen",
            "exchange_rate": "157.35",
            "effective_date": "2024-12-31",
        },
    ],
    "meta": {"count": 1, "total-count": 1, "total-pages": 1},
    "links": {},
}

SAMPLE_DTS_RESPONSE = {
    "data": [
        {
            "record_date": "2024-12-31",
            "account_type": "Federal Reserve Account",
            "close_today_bal": "722594.57",
            "open_today_bal": "718594.57",
            "open_month_bal": "691434.81",
            "open_fiscal_year_bal": "824554.78",
        },
    ],
    "meta": {"count": 1, "total-count": 1, "total-pages": 1},
    "links": {},
}


# ---------------------------------------------------------------------------
# TestFiscalDataClient
# ---------------------------------------------------------------------------

class TestFiscalDataClient:
    """Tests for the FiscalDataClient API wrapper."""

    @pytest.fixture()
    def client(self):
        return FiscalDataClient()

    @pytest.mark.asyncio
    async def test_get_debt_to_penny_basic(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_debt_to_penny()

        assert len(result["data"]) == 2
        assert result["data"][0]["record_date"] == "2024-12-31"
        assert result["data"][0]["tot_pub_debt_out_amt"] == "36218064858041.87"
        assert "meta" in result

    @pytest.mark.asyncio
    async def test_get_debt_to_penny_with_date_range(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(start_date="2024-01-01", end_date="2024-12-31")

        call_kwargs = mock_get.call_args
        assert "record_date:gte:2024-01-01" in call_kwargs[1]["params"]["filter"]
        assert "record_date:lte:2024-12-31" in call_kwargs[1]["params"]["filter"]

    @pytest.mark.asyncio
    async def test_get_debt_to_penny_with_fields(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(fields="record_date,tot_pub_debt_out_amt")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["fields"] == "record_date,tot_pub_debt_out_amt"

    @pytest.mark.asyncio
    async def test_get_debt_to_penny_pagination(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(page_size=50, page=3)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["page[size]"] == 50
        assert call_kwargs[1]["params"]["page[number]"] == 3

    @pytest.mark.asyncio
    async def test_get_interest_rates_basic(self, client):
        mock_resp = _mock_response(SAMPLE_INTEREST_RATES_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_interest_rates()

        assert len(result["data"]) == 2
        assert result["data"][0]["security_desc"] == "Treasury Bonds"

    @pytest.mark.asyncio
    async def test_get_interest_rates_with_security_type_filter(self, client):
        mock_resp = _mock_response(SAMPLE_INTEREST_RATES_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_interest_rates(security_type="Treasury Bonds")

        call_kwargs = mock_get.call_args
        assert "security_desc:eq:Treasury Bonds" in call_kwargs[1]["params"]["filter"]

    @pytest.mark.asyncio
    async def test_get_exchange_rates_basic(self, client):
        mock_resp = _mock_response(SAMPLE_EXCHANGE_RATES_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_exchange_rates()

        assert len(result["data"]) == 1
        assert result["data"][0]["country"] == "Japan"
        assert result["data"][0]["currency"] == "Yen"

    @pytest.mark.asyncio
    async def test_get_exchange_rates_with_country_filter(self, client):
        mock_resp = _mock_response(SAMPLE_EXCHANGE_RATES_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_exchange_rates(country="Japan")

        call_kwargs = mock_get.call_args
        assert "country:eq:Japan" in call_kwargs[1]["params"]["filter"]

    @pytest.mark.asyncio
    async def test_get_exchange_rates_with_currency_filter(self, client):
        mock_resp = _mock_response(SAMPLE_EXCHANGE_RATES_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_exchange_rates(currency="Yen")

        call_kwargs = mock_get.call_args
        assert "currency:eq:Yen" in call_kwargs[1]["params"]["filter"]

    @pytest.mark.asyncio
    async def test_get_interest_expense_basic(self, client):
        response = {
            "data": [{"record_date": "2024-12-31", "expense_catg_desc": "Total", "month_expense_amt": "89000000000"}],
            "meta": {"count": 1, "total-count": 1, "total-pages": 1},
            "links": {},
        }
        mock_resp = _mock_response(response)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_interest_expense()

        assert len(result["data"]) == 1
        assert result["data"][0]["expense_catg_desc"] == "Total"

    @pytest.mark.asyncio
    async def test_get_treasury_statement_basic(self, client):
        mock_resp = _mock_response(SAMPLE_DTS_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_treasury_statement()

        assert len(result["data"]) == 1
        assert result["data"][0]["account_type"] == "Federal Reserve Account"

    @pytest.mark.asyncio
    async def test_get_treasury_statement_invalid_table(self, client):
        with pytest.raises(FiscalDataAPIError, match="Invalid DTS table"):
            await client.get_treasury_statement(table="nonexistent_table")

    @pytest.mark.asyncio
    async def test_get_treasury_statement_correct_endpoint(self, client):
        mock_resp = _mock_response(SAMPLE_DTS_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_treasury_statement(table="public_debt_transactions")

        call_args = mock_get.call_args
        assert call_args[0][0] == "/v1/accounting/dts/public_debt_transactions"

    @pytest.mark.asyncio
    async def test_query_dataset_basic(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.query_dataset(endpoint="v2/accounting/od/gold_reserve")

        assert "data" in result
        assert "meta" in result

    @pytest.mark.asyncio
    async def test_query_dataset_with_filter(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.query_dataset(
                endpoint="v2/accounting/od/gold_reserve",
                filter_expr="record_date:gte:2024-01-01",
            )

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["filter"] == "record_date:gte:2024-01-01"

    @pytest.mark.asyncio
    async def test_query_dataset_endpoint_validation_rejects_invalid(self, client):
        with pytest.raises(FiscalDataAPIError, match="Invalid endpoint path"):
            await client.query_dataset(endpoint="../../../etc/passwd")

    @pytest.mark.asyncio
    async def test_query_dataset_endpoint_validation_rejects_no_version(self, client):
        with pytest.raises(FiscalDataAPIError, match="Invalid endpoint path"):
            await client.query_dataset(endpoint="accounting/od/debt_to_penny")

    @pytest.mark.asyncio
    async def test_query_dataset_endpoint_validation_rejects_special_chars(self, client):
        with pytest.raises(FiscalDataAPIError, match="Invalid endpoint path"):
            await client.query_dataset(endpoint="v2/accounting/od/debt;drop")

    @pytest.mark.asyncio
    async def test_query_dataset_endpoint_validation_accepts_valid(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.query_dataset(endpoint="v2/accounting/od/debt_to_penny")

        call_args = mock_get.call_args
        assert call_args[0][0] == "/v2/accounting/od/debt_to_penny"

    @pytest.mark.asyncio
    async def test_cache_hit(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            result1 = await client.get_debt_to_penny()
            result2 = await client.get_debt_to_penny()

        # Second call should use cache
        assert mock_get.call_count == 1
        assert result1["data"] == result2["data"]

    @pytest.mark.asyncio
    async def test_stale_cache_fallback(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        # First call succeeds and populates cache
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result1 = await client.get_debt_to_penny()

        # Invalidate cache by setting old timestamp
        for entry in client._cache.values():
            entry.timestamp = 0

        # Second call fails, should use stale cache
        with patch.object(client._http, "get", new_callable=AsyncMock, side_effect=httpx.TimeoutException("timeout")):
            result2 = await client.get_debt_to_penny()

        assert result2["data"] == result1["data"]
        assert "warning" in result2["meta"]

    @pytest.mark.asyncio
    async def test_retry_on_timeout_no_cache(self, client):
        """Retry exhaustion raises when there's no stale cache."""
        with patch.object(
            client._http, "get", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("timeout"),
        ):
            with pytest.raises(httpx.TimeoutException):
                await client.get_debt_to_penny()

    @pytest.mark.asyncio
    async def test_unexpected_response_format(self, client):
        mock_resp = _mock_response("not a dict")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(FiscalDataAPIError, match="Unexpected API response format"):
                await client._get("/v2/test", {})

    @pytest.mark.asyncio
    async def test_page_size_clamped_upper(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(page_size=99999)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["page[size]"] == 10000

    @pytest.mark.asyncio
    async def test_page_size_clamped_lower(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(page_size=-5)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["page[size]"] == 1

    @pytest.mark.asyncio
    async def test_meta_includes_links(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_debt_to_penny()

        assert "links" in result["meta"]
        assert "next" in result["meta"]["links"]

    @pytest.mark.asyncio
    async def test_sort_parameter_passed(self, client):
        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_debt_to_penny(sort="record_date")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["sort"] == "record_date"


# ---------------------------------------------------------------------------
# TestFiscalDataTools
# ---------------------------------------------------------------------------

class TestFiscalDataTools:
    """Tests for the MCP tool wrapper functions."""

    @pytest.fixture(autouse=True)
    def _reset_client(self):
        """Reset the module-level client's cache between tests."""
        import server
        server.client._cache.clear()

    @pytest.mark.asyncio
    async def test_get_national_debt_returns_json(self):
        from server import fiscaldata_get_national_debt

        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_get_national_debt()

        parsed = json.loads(result)
        assert "data" in parsed
        assert "meta" in parsed

    @pytest.mark.asyncio
    async def test_get_interest_rates_returns_json(self):
        from server import fiscaldata_get_interest_rates

        mock_resp = _mock_response(SAMPLE_INTEREST_RATES_RESPONSE)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_get_interest_rates()

        parsed = json.loads(result)
        assert "data" in parsed
        assert "meta" in parsed

    @pytest.mark.asyncio
    async def test_get_exchange_rates_returns_json(self):
        from server import fiscaldata_get_exchange_rates

        mock_resp = _mock_response(SAMPLE_EXCHANGE_RATES_RESPONSE)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_get_exchange_rates()

        parsed = json.loads(result)
        assert "data" in parsed
        assert result != ""

    @pytest.mark.asyncio
    async def test_get_interest_expense_returns_json(self):
        from server import fiscaldata_get_interest_expense

        expense_response = {
            "data": [{"record_date": "2024-12-31", "expense_catg_desc": "Total"}],
            "meta": {"count": 1, "total-count": 1, "total-pages": 1},
            "links": {},
        }
        mock_resp = _mock_response(expense_response)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_get_interest_expense()

        parsed = json.loads(result)
        assert "data" in parsed

    @pytest.mark.asyncio
    async def test_get_treasury_statement_returns_json(self):
        from server import fiscaldata_get_treasury_statement

        mock_resp = _mock_response(SAMPLE_DTS_RESPONSE)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_get_treasury_statement()

        parsed = json.loads(result)
        assert "data" in parsed

    @pytest.mark.asyncio
    async def test_query_dataset_returns_json(self):
        from server import fiscaldata_query_dataset

        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await fiscaldata_query_dataset(endpoint="v2/accounting/od/gold_reserve")

        parsed = json.loads(result)
        assert "data" in parsed

    @pytest.mark.asyncio
    async def test_tool_error_wrapping_api_error(self):
        from server import fiscaldata_get_treasury_statement

        # Invalid table should produce an error dict, not raise
        result = await fiscaldata_get_treasury_statement(table="invalid_table")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid DTS table" in parsed["error"]

    @pytest.mark.asyncio
    async def test_tool_error_wrapping_timeout(self):
        from server import fiscaldata_get_national_debt

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Connection timed out"),
        ):
            result = await fiscaldata_get_national_debt()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"]

    @pytest.mark.asyncio
    async def test_tool_error_wrapping_network_error(self):
        from server import fiscaldata_get_national_debt

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
            side_effect=httpx.ConnectError("Connection refused"),
        ):
            result = await fiscaldata_get_national_debt()

        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_query_dataset_validates_endpoint(self):
        from server import fiscaldata_query_dataset

        result = await fiscaldata_query_dataset(endpoint="../../etc/passwd")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid endpoint path" in parsed["error"]

    @pytest.mark.asyncio
    async def test_page_size_clamping_in_tool(self):
        from server import fiscaldata_get_national_debt

        mock_resp = _mock_response(SAMPLE_DEBT_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            await fiscaldata_get_national_debt(page_size=99999)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["page[size]"] == 10000

    @pytest.mark.asyncio
    async def test_each_tool_uses_correct_endpoint(self):
        from server import (
            fiscaldata_get_exchange_rates,
            fiscaldata_get_interest_expense,
            fiscaldata_get_interest_rates,
            fiscaldata_get_national_debt,
            fiscaldata_get_treasury_statement,
        )

        expected_endpoints = {
            fiscaldata_get_national_debt: "/v2/accounting/od/debt_to_penny",
            fiscaldata_get_interest_rates: "/v2/accounting/od/avg_interest_rates",
            fiscaldata_get_exchange_rates: "/v1/accounting/od/rates_of_exchange",
            fiscaldata_get_interest_expense: "/v2/accounting/od/interest_expense",
            fiscaldata_get_treasury_statement: "/v1/accounting/dts/operating_cash_balance",
        }

        for tool_fn, expected_ep in expected_endpoints.items():
            generic_resp = {
                "data": [{"record_date": "2024-01-01"}],
                "meta": {"count": 1, "total-count": 1, "total-pages": 1},
                "links": {},
            }
            mock_resp = _mock_response(generic_resp)
            with patch.object(
                httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
            ) as mock_get:
                # Reset cache before each tool call
                import server
                server.client._cache.clear()
                await tool_fn()

            call_args = mock_get.call_args
            assert call_args[0][0] == expected_ep, f"{tool_fn.__name__} should use {expected_ep}"


# ---------------------------------------------------------------------------
# TestFiscalDataMcpConfig
# ---------------------------------------------------------------------------

class TestFiscalDataMcpConfig:
    """Tests for the fiscaldata entry in extensions_config.json."""

    def test_extensions_config_has_fiscaldata(self):
        config_path = Path(__file__).resolve().parent.parent.parent / "extensions_config.json"
        with open(config_path) as f:
            config = json.load(f)

        fd = config["mcpServers"]["fiscaldata"]
        assert fd["enabled"] is True
        assert fd["type"] == "stdio"
        assert fd["command"] == "uv"
        assert "../mcp_servers/fiscaldata" in fd["args"]

    def test_build_server_params_for_fiscaldata(self):
        from src.config.extensions_config import McpServerConfig
        from src.mcp.client import build_server_params

        config = McpServerConfig(
            enabled=True,
            type="stdio",
            command="uv",
            args=["--directory", "../mcp_servers/fiscaldata", "run", "python", "server.py"],
            env={},
            description="U.S. Treasury Fiscal Data API",
        )
        params = build_server_params("fiscaldata", config)

        assert params["transport"] == "stdio"
        assert params["command"] == "uv"
        assert "--directory" in params["args"]
        assert "../mcp_servers/fiscaldata" in params["args"]
