"""Tests for SearXNG community tools."""

import json
import logging
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from deerflow.community.searxng import tools
from deerflow.community.searxng.searxng_client import SearxngClient, SearxngResponseError


class AsyncMock(MagicMock):
    """Mock that supports async call."""

    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


@contextmanager
def _searxng_pages(pages: dict[int, list[dict]]):
    """Patch httpx so request page N answers with ``pages[N]``.

    A page that was not given answers with an empty result set, which is what a
    real instance does once the query is exhausted.
    """
    with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
        mock_ctx = MagicMock()
        mock_cls.return_value.__aenter__.return_value = mock_ctx

        def _get(url, params=None, headers=None):
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": pages.get(params["pageno"], [])}
            mock_resp.raise_for_status.return_value = None
            return mock_resp

        mock_ctx.get = AsyncMock(side_effect=_get)
        yield mock_ctx


@pytest.mark.asyncio
class TestSearxngClient:
    """Tests for the SearxngClient class."""

    async def test_search_success(self):
        """Search returns normalized results."""
        results_data = {
            "results": [
                {"title": "Page 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Page 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = results_data
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

            assert len(result) == 2
            assert result[0]["title"] == "Page 1"
            assert result[1]["url"] == "https://example.com/2"

    async def test_search_empty_results(self):
        """Search returns empty list when no results."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("empty query")
            assert result == []

    async def test_search_http_error(self):
        """Search raises on HTTP error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError("403 Forbidden", request=MagicMock(), response=MagicMock())
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("blocked query")

    async def test_search_request_error(self):
        """Search raises on request error."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            import httpx

            mock_ctx.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(httpx.RequestError):
                await client.search("unreachable query")

    async def test_search_with_categories(self):
        """Search passes categories parameter."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("test", categories=["news", "science"])

            call_kwargs = mock_ctx.get.call_args.kwargs
            assert call_kwargs["params"]["categories"] == "news,science"

    async def test_search_with_time_range(self):
        """Search passes a native relative time range."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("latest release", time_range="month")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert params["time_range"] == "month"

    async def test_search_without_time_range_omits_parameter(self):
        """The default request shape remains unchanged."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.json.return_value = {"results": []}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("stable documentation")

            params = mock_ctx.get.call_args.kwargs["params"]
            assert "time_range" not in params

    async def test_search_collects_results_across_pages(self):
        """A max_results larger than one page is collected by walking pageno.

        SearXNG's search API has no `limit` parameter -- /search answers with one
        page (the instance's results_per_page, 10 by default) and ignores a limit
        it is handed -- so a configured max_results above a page used to be
        silently capped at whatever the first page held.
        """
        pages = {
            1: [{"title": f"page1-{i}", "url": f"https://example.com/1/{i}", "content": "c"} for i in range(3)],
            2: [{"title": f"page2-{i}", "url": f"https://example.com/2/{i}", "content": "c"} for i in range(3)],
        }

        with _searxng_pages(pages) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

        assert len(result) == 5
        assert [call.kwargs["params"]["pageno"] for call in mock_ctx.get.call_args_list] == [1, 2]

    async def test_search_makes_one_request_when_a_page_is_enough(self):
        """The default max_results still costs exactly one request."""
        rows = [{"title": f"r{i}", "url": f"https://example.com/{i}", "content": "c"} for i in range(10)]

        with _searxng_pages({1: rows}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

        assert len(result) == 5
        assert mock_ctx.get.call_count == 1

    async def test_search_stops_when_a_page_adds_nothing_new(self):
        """A repeating page ends the walk instead of duplicating results."""
        repeated = [{"title": f"r{i}", "url": f"https://example.com/{i}", "content": "c"} for i in range(2)]

        with _searxng_pages({1: repeated, 2: repeated, 3: repeated}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=50)

        assert len(result) == 2
        assert mock_ctx.get.call_count == 2

    async def test_search_drops_collected_rows_when_a_later_page_is_malformed(self):
        """A malformed page aborts the walk and discards the rows already collected.

        SearXNG is the only contained provider whose ``search()`` paginates, so it
        is the only one where a multi-request search can fail midway. Pinning the
        trade-off: a reverse proxy or captive portal that starts failing between
        pages is assumed to be failing persistently, and returning the short first
        page would look like a complete search. Raising the format error is the
        sibling providers' behaviour too (they fail on their single request), so
        this keeps the family contract at the cost of the already-collected rows.
        """
        first_page = [{"title": f"r{i}", "url": f"https://example.com/1/{i}", "content": "c"} for i in range(3)]

        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            def _get(url, params=None, headers=None):
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                # Page 1 parses; page 2 is the proxy/captive-portal HTML page.
                mock_resp.json.return_value = {"results": first_page} if params["pageno"] == 1 else "upstream maintenance"
                mock_resp.raise_for_status.return_value = None
                return mock_resp

            mock_ctx.get = AsyncMock(side_effect=_get)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(SearxngResponseError):
                await client.search("test query", max_results=20)

        assert [call.kwargs["params"]["pageno"] for call in mock_ctx.get.call_args_list] == [1, 2]

    async def test_search_never_sends_the_unsupported_limit_parameter(self):
        """`limit` is not part of the SearXNG search API, so it is not sent."""
        with _searxng_pages({1: [{"title": "t", "url": "https://example.com/1", "content": "c"}]}) as mock_ctx:
            client = SearxngClient(base_url="http://searxng:8080")
            await client.search("test query", max_results=20)

        assert "limit" not in mock_ctx.get.call_args_list[0].kwargs["params"]

    @pytest.mark.parametrize(
        "payload",
        [
            {"results": "maintenance window"},
            {"results": {"a": 1}},
            {"results": 7},
            {"results": [1, 2, 3]},
            {"results": [None, None]},
            {"results": ["a"]},
            ["not-an-object"],
            "text",
        ],
        ids=[
            "results-is-a-string",
            "results-is-a-populated-dict",
            "results-is-an-int",
            "list-with-no-objects",
            "list-of-nulls",
            "list-of-strings",
            "payload-is-a-list",
            "payload-is-a-string",
        ],
    )
    async def test_search_malformed_payload_reports_a_format_error(self, payload, caplog):
        """A malformed 200 payload is a format error, not an empty search.

        An instance behind a reverse proxy or captive portal answers an HTML or
        plain-text error page with HTTP 200. Returning an empty list for it would
        tell the agent the query legitimately matched nothing -- and indexing the
        raw payload first leaked an AttributeError/TypeError instead.

        The raise must come from the dedicated ``except SearxngResponseError``
        clause, not the generic ``except Exception`` below: the generic branch
        logs "An unexpected error occurred" at ERROR for every contained page
        before re-raising, so without this assertion the clause can be deleted
        with the whole file still green.
        """
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = payload
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with caplog.at_level(logging.ERROR, logger="deerflow.community.searxng.searxng_client"):
                with pytest.raises(SearxngResponseError):
                    await client.search("test query")

        assert "An unexpected error occurred" not in caplog.text

    async def test_search_keeps_valid_rows_from_a_mixed_page(self):
        """Non-object entries in an otherwise valid page are skipped in order.

        The page still has usable rows, so it is not malformed: dropping them
        would lose a valid answer.
        """
        rows = [
            {"title": "ok", "url": "https://example.com/1", "content": "c"},
            7,
            None,
        ]

        with _searxng_pages({1: rows}):
            client = SearxngClient(base_url="http://searxng:8080")
            result = await client.search("test query", max_results=5)

        assert [row["title"] for row in result] == ["ok"]

    async def test_search_logs_the_index_of_a_skipped_row(self, caplog):
        """Every skipped entry is logged with its position.

        The merged sibling #6932 reports the same drift for InfoQuest
        (``Skipping malformed InfoQuest result entry at results[1]``); SearXNG is
        the provider where drift is most expected and where a single search can
        span ``_MAX_PAGES`` requests, so the skip must leave a trace.
        """
        rows = [
            {"title": "kept-0", "url": "https://example.com/0", "content": "c"},
            7,
            {"title": "kept-2", "url": "https://example.com/2", "content": "c"},
        ]

        with _searxng_pages({1: rows}):
            client = SearxngClient(base_url="http://searxng:8080")
            with caplog.at_level(logging.WARNING, logger="deerflow.community.searxng.searxng_client"):
                result = await client.search("test query", max_results=5)

        assert [row["title"] for row in result] == ["kept-0", "kept-2"]
        warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
        assert any("results[1]" in message for message in warnings), warnings
        assert not any("example.com" in message for message in warnings), warnings

    async def test_search_non_json_body_reports_a_format_error(self):
        """A 200 body that is not JSON at all is a format error, not a crash."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            client = SearxngClient(base_url="http://searxng:8080")
            with pytest.raises(SearxngResponseError):
                await client.search("test query")


@pytest.mark.asyncio
class TestSearxngTools:
    """Tests for the SearXNG tool functions."""

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_success(self, mock_get_client):
        """web_search_tool returns JSON results."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(
            return_value=[
                {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
            ]
        )
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert len(data) == 1
        assert data[0]["title"] == "Result 1"

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_error(self, mock_get_client):
        """web_search_tool handles errors gracefully."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(side_effect=Exception("API error"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert "error" in data

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_with_max_results(self, mock_get_client):
        """web_search_tool respects max_results config."""
        mock_client = MagicMock()
        # Return 10 results; the tool should slice to max_results=3
        mock_client.search = AsyncMock(return_value=[{"title": f"Result {i}", "url": f"https://example.com/{i}", "content": f"Desc {i}"} for i in range(10)])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"max_results": "3"}):
            await tools.web_search_tool.ainvoke("test query")

        # Verify that search was called with max_results=3 (coerced from string)
        mock_client.search.assert_called_once()
        call_kwargs = mock_client.search.call_args.kwargs
        assert call_kwargs["max_results"] == 3

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_unparseable_max_results_uses_default(self, mock_get_client):
        """A max_results the config cannot give as a number falls back to the default."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        # ``max_results:`` left blank in config.yaml loads as None; a word is a
        # typo an operator can just as easily make. Neither is a reason to stop
        # searching -- every sibling provider falls back to the default.
        for raw in (None, "many"):
            with patch("deerflow.community.searxng.tools._get_tool_config", return_value={"max_results": raw}):
                result = await tools.web_search_tool.ainvoke("test query")

            assert "error" not in json.loads(result), f"max_results={raw!r} failed the whole call"
            mock_client.search.assert_called_once_with("test query", max_results=5)
            mock_client.search.reset_mock()

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_forwards_time_range(self, mock_get_client):
        """web_search_tool forwards the requested relative time range."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(return_value=[])
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            await tools.web_search_tool.ainvoke({"query": "latest release", "time_range": "week"})

        mock_client.search.assert_called_once_with("latest release", max_results=5, time_range="week")

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_inf_max_results_falls_back_to_default(self, mock_get_client):
        """A YAML `.inf` max_results must fall back to the default, not error out."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(
            return_value=[
                {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
            ]
        )
        mock_get_client.return_value = mock_client

        with patch(
            "deerflow.community.searxng.tools._get_tool_config",
            return_value={"max_results": float("inf")},
        ):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert "error" not in data
        assert mock_client.search.call_args.kwargs["max_results"] == 5

    async def test_web_search_tool_reports_a_format_error_for_a_malformed_page(self):
        """The agent sees the provider's format error, not a raw Python error.

        The page parses but holds no usable entry, so the tool must answer with
        the provider's format error. Pre-fix, indexing the raw payload leaked an
        AttributeError/TypeError into the model-visible result instead.
        """
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": [1, None, "x"]}
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
                result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert data["error"] == "SearXNG returned an unexpected response format"
        assert data["query"] == "test query"

    async def test_web_search_tool_keeps_the_valid_rows_of_a_mixed_page(self):
        """A page with usable rows still answers with those rows."""
        with patch("deerflow.community.searxng.searxng_client.httpx.AsyncClient") as mock_cls:
            mock_ctx = MagicMock()
            mock_cls.return_value.__aenter__.return_value = mock_ctx

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "results": [
                    {"title": "Result 1", "url": "https://example.com/1", "content": "Desc 1"},
                    7,
                ]
            }
            mock_resp.raise_for_status.return_value = None
            mock_ctx.get = AsyncMock(return_value=mock_resp)

            with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
                result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert [row["title"] for row in data] == ["Result 1"]

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_keeps_other_failures_as_their_own_errors(self, mock_get_client):
        """Transport and configuration failures keep their existing error text."""
        mock_client = MagicMock()
        mock_client.search = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert "unexpected response format" not in data["error"]
        assert mock_client.search.call_args.kwargs["max_results"] == 5

    @patch("deerflow.community.searxng.tools._get_searxng_client")
    async def test_web_search_tool_routes_the_format_error_before_the_generic_handler(self, mock_get_client, caplog):
        """The format-error reply comes from its own handler, not the generic one.

        ``SearxngResponseError`` is a ``ValueError`` whose message is already the
        format-error string, so the generic ``except Exception`` below would
        return byte-identical JSON. What distinguishes the two paths is the log
        line: the generic branch records ``Error in web_search_tool: ...`` first.
        Without this assertion the dedicated handler could be deleted (or the
        exception message changed) with every test still green.
        """
        mock_client = MagicMock()
        mock_client.search = AsyncMock(side_effect=SearxngResponseError("SearXNG returned an unexpected response format"))
        mock_get_client.return_value = mock_client

        with patch("deerflow.community.searxng.tools._get_tool_config", return_value=None):
            with caplog.at_level(logging.ERROR, logger="deerflow.community.searxng.tools"):
                result = await tools.web_search_tool.ainvoke("test query")

        data = json.loads(result)
        assert data["error"] == "SearXNG returned an unexpected response format"
        assert data["query"] == "test query"
        assert "Error in web_search_tool" not in caplog.text
