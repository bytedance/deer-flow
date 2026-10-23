"""Unit tests for the Jsonify community tool."""

import ipaddress
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

SERVE_URL = "https://factory.jsonify.com/api/serve/abc123"
PAGE_ONE = {
    "dataset": "abc123",
    "dataset_name": "LLM API pricing",
    "table": "models",
    "version": 3,
    "updated_at": 1791979608,
    "row_count": 2,
    "has_more": True,
    "next_offset": 2,
    "rows": [
        {"_row_id": "r1", "_parent_row_id": "p1", "_source_key": "anthropic", "provider": "Anthropic", "model": "a"},
        {"_row_id": "r2", "_parent_row_id": "p2", "_source_key": "anthropic", "provider": "Anthropic", "model": "b"},
    ],
}
PAGE_TWO = {**PAGE_ONE, "row_count": 1, "has_more": False, "next_offset": None, "rows": [{"_row_id": "r3", "provider": "Anthropic", "model": "c"}]}


@pytest.fixture
def public_dns():
    with patch(
        "deerflow.community.url_safety.resolve_host_addresses",
        return_value=[ipaddress.ip_address("93.184.216.34")],
    ):
        yield


def _config(extra: dict | None):
    tool_config = MagicMock()
    tool_config.model_extra = extra
    app_config = MagicMock()
    app_config.get_tool_config.return_value = tool_config
    return app_config


def _response(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request("GET", SERVE_URL))


def _client_with(responses: list[httpx.Response]) -> MagicMock:
    client = MagicMock()
    client.get = AsyncMock(side_effect=responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_reads_pages_strips_system_columns_and_pins_version():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response(PAGE_ONE), _response(PAGE_TWO)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = json.loads(await dataset_rows_tool.ainvoke({"dataset": "pricing", "filters": {"provider": "Anthropic"}, "columns": ["provider", "model"], "limit": 10}))

    assert result["dataset_name"] == "LLM API pricing"
    assert result["row_count"] == 3
    assert result["rows"][0] == {"_row_id": "r1", "provider": "Anthropic", "model": "a"}
    first = client.get.call_args_list[0].kwargs["params"]
    second = client.get.call_args_list[1].kwargs["params"]
    assert first == {"limit": 10, "offset": 0, "columns": "provider,model", "filter[provider]": "Anthropic"}
    assert second["offset"] == 2
    assert second["version"] == 3
    assert second["limit"] == 8


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_limit_is_capped_by_configured_max_rows():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response(PAGE_ONE)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}, "max_rows": 1})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = json.loads(await dataset_rows_tool.ainvoke({"dataset": "pricing", "limit": 500}))

    assert client.get.call_args.kwargs["params"]["limit"] == 1
    assert result["row_count"] == 1


@pytest.mark.anyio
async def test_unknown_dataset_lists_available_names():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    with patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL, "releases": SERVE_URL + "0"}})):
        result = await dataset_rows_tool.ainvoke({"dataset": "nope"})

    assert result == "Error: Unknown dataset 'nope'. Available datasets: pricing, releases"


@pytest.mark.anyio
async def test_unconfigured_tool_returns_error_without_request():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config(None)),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient") as client_cls,
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})

    assert result.startswith("Error: jsonify_dataset_rows is not configured")
    client_cls.assert_not_called()


@pytest.mark.anyio
async def test_rejects_http_serve_url_and_userinfo():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    for bad in ("http://factory.jsonify.com/api/serve/abc", "https://user:pw@factory.jsonify.com/api/serve/abc"):
        with patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": bad}})):
            result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})
        assert result.startswith("Error: jsonify_dataset_rows is not configured")


@pytest.mark.anyio
async def test_private_address_blocked_before_request():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"meta": "https://169.254.169.254/latest/meta-data"}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient") as client_cls,
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "meta"})

    assert result.startswith("Error:")
    client_cls.assert_not_called()


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_http_error_is_redacted():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response({"error": "nope"}, status=404)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})

    assert result == "Error: Jsonify returned HTTP 404"
    assert SERVE_URL not in result


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_truncated_flag_when_more_rows_match():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response(PAGE_ONE)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = json.loads(await dataset_rows_tool.ainvoke({"dataset": "pricing", "limit": 2}))

    assert result["row_count"] == 2
    assert result["truncated"] is True


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_complete_read_is_not_truncated():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response(PAGE_TWO)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = json.loads(await dataset_rows_tool.ainvoke({"dataset": "pricing"}))

    assert result["truncated"] is False


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
@pytest.mark.parametrize(
    "page",
    [
        {**PAGE_ONE, "next_offset": 0},
        {**PAGE_ONE, "next_offset": "2"},
        {**PAGE_ONE, "rows": []},
    ],
)
async def test_stops_when_cursor_does_not_advance_or_page_is_empty(page):
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([_response(page), _response(PAGE_TWO)])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = json.loads(await dataset_rows_tool.ainvoke({"dataset": "pricing", "limit": 100}))

    assert client.get.call_count == 1
    assert result["row_count"] == len(page["rows"])


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
@pytest.mark.parametrize("payload", [["not", "a", "page"], {"rows": "nope"}, {"rows": ["r1"]}, {"has_more": False}])
async def test_malformed_page_returns_redacted_error(payload):
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = MagicMock()
    client.get = AsyncMock(return_value=httpx.Response(200, json=payload, request=httpx.Request("GET", SERVE_URL)))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})

    assert result == "Error: Jsonify returned an unexpected response shape"


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_non_json_page_returns_error():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = _client_with([httpx.Response(200, text="<html>", request=httpx.Request("GET", SERVE_URL))])
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})

    assert result == "Error: Jsonify returned a response that is not JSON"


def test_invalid_config_warning_omits_serve_url(caplog):
    from deerflow.community.jsonify.tools import _load_settings

    secret = "http://factory.jsonify.com/api/serve/supersecret"
    with patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": secret}})):
        result = _load_settings()

    assert isinstance(result, str)
    assert "supersecret" not in caplog.text
    assert "datasets: value_error" in caplog.text


@pytest.mark.anyio
@pytest.mark.usefixtures("public_dns")
async def test_transport_error_omits_url():
    from deerflow.community.jsonify.tools import dataset_rows_tool

    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.ConnectError(f"failed to connect to {SERVE_URL}"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with (
        patch("deerflow.community.jsonify.tools.get_app_config", return_value=_config({"datasets": {"pricing": SERVE_URL}})),
        patch("deerflow.community.jsonify.tools.httpx.AsyncClient", return_value=client),
    ):
        result = await dataset_rows_tool.ainvoke({"dataset": "pricing"})

    assert result == "Error: Could not reach Jsonify: ConnectError"
