"""Unit tests for the World Bank MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the worldbank MCP server directory to sys.path so we can import directly
WORLDBANK_DIR = str(Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "worldbank")
if WORLDBANK_DIR not in sys.path:
    sys.path.insert(0, WORLDBANK_DIR)

from api_client import WorldBankAPIError, WorldBankClient


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


SAMPLE_COUNTRY_RESPONSE = [
    {"page": 1, "pages": 1, "per_page": 50, "total": 2},
    [
        {
            "id": "CHN",
            "name": "China",
            "region": {"value": "East Asia & Pacific"},
            "incomeLevel": {"value": "Upper middle income"},
            "capitalCity": "Beijing",
            "iso2Code": "CN",
        },
        {
            "id": "USA",
            "name": "United States",
            "region": {"value": "North America"},
            "incomeLevel": {"value": "High income"},
            "capitalCity": "Washington D.C.",
            "iso2Code": "US",
        },
    ],
]

SAMPLE_INDICATOR_LIST = [
    {"page": 1, "pages": 1, "per_page": 1000, "total": 3},
    [
        {
            "id": "NY.GDP.MKTP.CD",
            "name": "GDP (current US$)",
            "sourceNote": "GDP at purchaser's prices",
            "source": {"value": "World Development Indicators"},
            "topics": [{"id": "3", "value": "Economy & Growth"}],
        },
        {
            "id": "SP.POP.TOTL",
            "name": "Population, total",
            "sourceNote": "Total population count",
            "source": {"value": "World Development Indicators"},
            "topics": [{"id": "19", "value": "Climate Change"}],
        },
        {
            "id": "SE.ADT.LITR.ZS",
            "name": "Literacy rate, adult total",
            "sourceNote": "Adult literacy rate percentage",
            "source": {"value": "World Development Indicators"},
            "topics": [{"id": "4", "value": "Education"}],
        },
    ],
]

SAMPLE_INDICATOR_DATA = [
    {"page": 1, "pages": 1, "per_page": 100, "total": 3},
    [
        {
            "country": {"value": "United States"},
            "countryiso3code": "USA",
            "date": "2023",
            "value": 25462700000000,
            "indicator": {"value": "GDP (current US$)"},
        },
        {
            "country": {"value": "United States"},
            "countryiso3code": "USA",
            "date": "2022",
            "value": 25744100000000,
            "indicator": {"value": "GDP (current US$)"},
        },
        {
            "country": {"value": "United States"},
            "countryiso3code": "USA",
            "date": "2021",
            "value": None,
            "indicator": {"value": "GDP (current US$)"},
        },
    ],
]


# ---------------------------------------------------------------------------
# TestWorldBankClient
# ---------------------------------------------------------------------------

class TestWorldBankClient:
    """Tests for the WorldBankClient API wrapper."""

    @pytest.fixture()
    def client(self):
        return WorldBankClient()

    @pytest.mark.asyncio
    async def test_list_countries_basic(self, client):
        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.list_countries()

        assert len(result["countries"]) == 2
        assert result["countries"][0]["id"] == "CHN"
        assert result["countries"][0]["name"] == "China"
        assert result["countries"][0]["capital"] == "Beijing"
        assert result["countries"][1]["id"] == "USA"
        assert result["pagination"]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_countries_with_region_filter(self, client):
        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.list_countries(region="EAS")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["region"] == "EAS"

    @pytest.mark.asyncio
    async def test_list_countries_with_income_level_filter(self, client):
        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.list_countries(income_level="HIC")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["incomeLevel"] == "HIC"

    @pytest.mark.asyncio
    async def test_list_countries_per_page_clamped(self, client):
        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.list_countries(per_page=999)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["per_page"] == 300

    @pytest.mark.asyncio
    async def test_search_indicators_keyword_match(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.search_indicators(query="GDP")

        assert len(result["indicators"]) == 1
        assert result["indicators"][0]["id"] == "NY.GDP.MKTP.CD"
        assert result["pagination"]["total"] == 1

    @pytest.mark.asyncio
    async def test_search_indicators_case_insensitive(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.search_indicators(query="gdp")

        assert len(result["indicators"]) == 1
        assert result["indicators"][0]["id"] == "NY.GDP.MKTP.CD"

    @pytest.mark.asyncio
    async def test_search_indicators_with_topic_filter(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            # Topic 4 = Education, should match literacy only among all results
            result = await client.search_indicators(query="rate", topic=4)

        assert len(result["indicators"]) == 1
        assert result["indicators"][0]["id"] == "SE.ADT.LITR.ZS"

    @pytest.mark.asyncio
    async def test_search_indicators_caching(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_indicators(query="GDP")
            await client.search_indicators(query="population")

        # Should only call the API once (cached)
        assert mock_get.call_count == 1

    @pytest.mark.asyncio
    async def test_search_indicators_pagination(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            # All 3 match with empty-ish query, get page 2 with per_page=2
            result = await client.search_indicators(query="", per_page=2, page=2)

        # Only the third indicator should be on page 2
        assert len(result["indicators"]) == 1
        assert result["pagination"]["page"] == 2
        assert result["pagination"]["pages"] == 2

    @pytest.mark.asyncio
    async def test_get_indicator_data_basic(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_DATA)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_indicator_data("USA", "NY.GDP.MKTP.CD")

        # Should filter out null values
        assert len(result["data"]) == 2
        assert result["data"][0]["country"] == "United States"
        assert result["data"][0]["value"] == 25462700000000

    @pytest.mark.asyncio
    async def test_get_indicator_data_with_date_range(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_DATA)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_indicator_data("USA", "NY.GDP.MKTP.CD", start_year=2020, end_year=2023)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["date"] == "2020:2023"

    @pytest.mark.asyncio
    async def test_get_indicator_data_with_start_year_only(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_DATA)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.get_indicator_data("USA", "NY.GDP.MKTP.CD", start_year=2022)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["date"] == "2022:2022"

    @pytest.mark.asyncio
    async def test_get_indicator_data_null_filtering(self, client):
        mock_resp = _mock_response(SAMPLE_INDICATOR_DATA)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_indicator_data("USA", "NY.GDP.MKTP.CD")

        # The third entry has value=None, should be filtered
        for record in result["data"]:
            assert record["value"] is not None

    @pytest.mark.asyncio
    async def test_api_error_response(self, client):
        # World Bank returns errors as [[{message: [...]}], ""] or similar two-element arrays
        error_response = [
            [{"message": [{"id": "120", "key": "Invalid value", "value": "The provided parameter value is not valid"}]}],
            "",
        ]
        mock_resp = _mock_response(error_response)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(WorldBankAPIError, match="not valid"):
                await client._get("/country", {})

    @pytest.mark.asyncio
    async def test_get_null_data_array(self, client):
        """API sometimes returns null as the data array."""
        response = [{"page": 1, "pages": 0, "per_page": 50, "total": 0}, None]
        mock_resp = _mock_response(response)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            meta, data = await client._get("/country")

        assert data == []


# ---------------------------------------------------------------------------
# TestWorldBankTools
# ---------------------------------------------------------------------------

class TestWorldBankTools:
    """Tests for the MCP tool wrapper functions."""

    @pytest.fixture(autouse=True)
    def _reset_client(self):
        """Reset the module-level client's cache between tests."""
        import server
        server.client._indicator_cache = None
        server.client._indicator_cache_time = 0.0

    @pytest.mark.asyncio
    async def test_list_countries_returns_json(self):
        from server import worldbank_list_countries

        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await worldbank_list_countries()

        parsed = json.loads(result)
        assert "countries" in parsed
        assert "pagination" in parsed

    @pytest.mark.asyncio
    async def test_search_indicators_returns_json(self):
        from server import worldbank_search_indicators

        mock_resp = _mock_response(SAMPLE_INDICATOR_LIST)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await worldbank_search_indicators(query="GDP")

        parsed = json.loads(result)
        assert "indicators" in parsed
        assert "pagination" in parsed

    @pytest.mark.asyncio
    async def test_get_indicator_data_returns_json(self):
        from server import worldbank_get_indicator_data

        mock_resp = _mock_response(SAMPLE_INDICATOR_DATA)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await worldbank_get_indicator_data(
                country_codes="USA", indicator_code="NY.GDP.MKTP.CD"
            )

        parsed = json.loads(result)
        assert "data" in parsed
        assert "pagination" in parsed

    @pytest.mark.asyncio
    async def test_tool_error_wrapping_api_error(self):
        from server import worldbank_list_countries

        error_response = [
            [{"message": [{"id": "120", "key": "Invalid value", "value": "Bad request"}]}],
        ]
        mock_resp = _mock_response(error_response)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await worldbank_list_countries()

        parsed = json.loads(result)
        assert "error" in parsed

    @pytest.mark.asyncio
    async def test_tool_error_wrapping_timeout(self):
        from server import worldbank_list_countries

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Connection timed out"),
        ):
            result = await worldbank_list_countries()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"]

    @pytest.mark.asyncio
    async def test_per_page_clamping_in_tool(self):
        from server import worldbank_list_countries

        mock_resp = _mock_response(SAMPLE_COUNTRY_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            await worldbank_list_countries(per_page=999)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["per_page"] == 300


# ---------------------------------------------------------------------------
# TestWorldBankMcpConfig
# ---------------------------------------------------------------------------

class TestWorldBankMcpConfig:
    """Tests for the worldbank entry in extensions_config.json."""

    def test_extensions_config_has_worldbank(self):
        config_path = Path(__file__).resolve().parent.parent.parent / "extensions_config.json"
        with open(config_path) as f:
            config = json.load(f)

        wb = config["mcpServers"]["worldbank"]
        assert wb["enabled"] is True
        assert wb["type"] == "stdio"
        assert wb["command"] == "uv"
        assert "../mcp_servers/worldbank" in wb["args"]

    def test_build_server_params_for_worldbank(self):
        from src.config.extensions_config import McpServerConfig
        from src.mcp.client import build_server_params

        config = McpServerConfig(
            enabled=True,
            type="stdio",
            command="uv",
            args=["--directory", "../mcp_servers/worldbank", "run", "python", "server.py"],
            env={},
            description="World Bank Open Data API",
        )
        params = build_server_params("worldbank", config)

        assert params["transport"] == "stdio"
        assert params["command"] == "uv"
        assert "--directory" in params["args"]
        assert "../mcp_servers/worldbank" in params["args"]
