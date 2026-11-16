"""Web-fetch policy uses transport evidence; page titles remain untrusted content."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY, normalize_tool_message


def _msg(content: str, *, name: str = "web_fetch", artifact=None) -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="tc-1", name=name, artifact=artifact)


def _meta(msg: ToolMessage):
    return msg.additional_kwargs[TOOL_META_KEY]


@pytest.mark.parametrize(
    "title",
    [
        "404 Not Found",
        "Page not found",
        "Not Found",
        "403 Forbidden",
        "Access Denied",
        "Permission denied",
        "401 Unauthorized",
        "407 Proxy Authentication Required",
        "429 Too Many Requests",
        "500 Internal Server Error",
        "501 Not Implemented",
        "502 Bad Gateway",
        "503 Service Unavailable",
        "504 Gateway Timeout",
        "404 Ways to Cook Rice",
        "Forbidden Planet",
        "Gone",
        "Untitled",
        "No results found",
    ],
)
def test_page_titles_cannot_establish_failure(title):
    result = normalize_tool_message(_msg(f"# {title}\n\nExample document body."))
    assert _meta(result)["status"] == "success"
    assert _meta(result)["error_type"] is None


@pytest.mark.parametrize("code", [None, True, "404", 200, 399, 600, [], {}])
def test_malformed_or_non_error_transport_metadata_is_not_failure(code):
    result = normalize_tool_message(_msg("# Access Denied", artifact={"deerflow_http_response": {"status_code": code}}))
    assert _meta(result)["status"] == "success"


def test_existing_producer_stamp_is_preserved():
    msg = _msg("# 404 Not Found")
    existing = {"status": "partial_success", "source": "tool_return", "error_type": None}
    msg.additional_kwargs[TOOL_META_KEY] = existing
    assert _meta(normalize_tool_message(msg)) is existing


_NGINX_404 = "<html>\r\n<head><title>404 Not Found</title></head>\r\n<body>\r\n<center><h1>404 Not Found</h1></center>\r\n<hr><center>nginx/1.24.0</center>\r\n</body>\r\n</html>\r\n"
_NGINX_503 = "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n<body>\r\n<center><h1>503 Service Temporarily Unavailable</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
_APACHE_403 = "<html><head>\n<title>403 Forbidden</title>\n</head><body>\n<h1>Forbidden</h1>\n<p>You don't have permission to access this resource.</p>\n<hr>\n<address>Apache/2.4.58 Server at example.org</address>\n</body></html>\n"
_IIS_404 = "<!DOCTYPE html>\n<html>\n<head><title>404 - File or directory not found.</title></head>\n<body>\n<h2>404 - File or directory not found.</h2>\n<h3>The resource may have been removed.</h3>\n</body>\n</html>\n"
_CLOUDFLARE_429 = "<!DOCTYPE html><html><head><title>429 Too Many Requests</title></head><body><center><h1>429 Too Many Requests</h1></center><hr><center>cloudflare</center></body></html>"
_SPA_404 = "<!DOCTYPE html><html><head><title>Page not found</title></head><body><div id=root><h1>Page not found</h1><p>Sorry, we couldn't find that page.</p></div></body></html>"
_LEGIT_ARTICLE = "<html><head><title>404 Ways to Cook Rice</title></head><body><article><h1>404 Ways to Cook Rice</h1><p>Rice is a staple for most of the planet, and great rice is technique.</p></article></body></html>"
_LEGIT_ESSAY = "<html><head><title>Not Found: a short history of the 404</title></head><body><article><h1>Not Found: a short history of the 404</h1><p>The code was introduced at CERN.</p></article></body></html>"


def _render(html: str, code: str, status: str) -> ToolMessage:
    """Real producer and LangChain tool envelope; only network dependencies are faked."""
    from deerflow.community.browserless import tools as browserless_tools
    from deerflow.community.browserless.browserless_client import BrowserlessFetchResult

    client = MagicMock()
    client.fetch_html_with_status = AsyncMock(return_value=BrowserlessFetchResult(html=html, target_status_code=code, target_status=status))
    with (
        patch.object(browserless_tools, "_get_browserless_client", return_value=client),
        patch("deerflow.utils.readability._readability_js_available", return_value=False),
        patch.object(browserless_tools, "_get_tool_config", return_value=None),
        patch.object(browserless_tools, "validate_public_http_url", return_value=None),
        patch.object(browserless_tools, "_validate_backend_base_url", return_value=None),
    ):
        return asyncio.run(browserless_tools.web_fetch_tool.ainvoke({"name": "web_fetch", "args": {"url": "https://example.org/x"}, "id": "tc-1", "type": "tool_call"}))


def _through_chain(message: ToolMessage, *, progress=None):
    progress = progress or ToolProgressMiddleware()
    errors = ToolErrorHandlingMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "run_id": "r1"}
    request = SimpleNamespace(tool_call={"name": "web_fetch", "id": "tc-1"}, runtime=runtime)
    return progress.wrap_tool_call(request, lambda req: errors.wrap_tool_call(req, lambda _: message.model_copy(deep=True)))


@pytest.mark.parametrize(
    "html,code,category",
    [
        (_NGINX_404, "404", "not_found"),
        (_APACHE_403, "403", "auth"),
        (_IIS_404, "404", "not_found"),
        (_CLOUDFLARE_429, "429", "rate_limited"),
        (_NGINX_503, "503", "transient"),
        (_SPA_404, "404", "not_found"),
        (_LEGIT_ARTICLE, "404", "not_found"),
    ],
)
def test_real_producer_preserves_http_failure_independently_of_title(html, code, category):
    message = _render(html, code, "diagnostic reason")
    assert message.artifact["deerflow_http_response"]["status_code"] == int(code)
    meta = _meta(_through_chain(message))
    assert meta["status"] == "error"
    assert meta["error_type"] == category
    assert meta["recoverable_by_model"] is True


@pytest.mark.parametrize("html", [_NGINX_404, _NGINX_503, _LEGIT_ARTICLE, _LEGIT_ESSAY])
@pytest.mark.parametrize("code", ["", "200", "unavailable"])
def test_missing_or_success_status_does_not_fall_back_to_title(html, code):
    meta = _meta(_through_chain(_render(html, code, "")))
    assert meta["status"] == "success"
    assert meta["error_type"] is None


def test_transport_warning_is_still_visible():
    assert "warning: target page responded 404 Not Found" in _render(_NGINX_404, "404", "Not Found").content


def test_structured_failure_warns_without_claiming_permanent_unavailability():
    message = _render(_NGINX_503, "503", "Service Temporarily Unavailable")
    progress = ToolProgressMiddleware()
    results = [_through_chain(message, progress=progress) for _ in range(6)]
    assert _meta(results[0])["error_type"] == "transient"
    assert _meta(results[-1])["error_type"] == "transient"
    assert progress._phase_states["t1"]["web_fetch"].phase == "warned"


@pytest.mark.parametrize("markdown", ["# 404 Not Found\nnginx/1.24.0\n", "# 503 Service Temporarily Unavailable\nnginx\n", "# 404 Ways to Cook Rice\nAn article about food.\n"])
def test_crawl4ai_without_target_status_does_not_guess_from_markdown(markdown):
    from deerflow.community.crawl4ai import tools as crawl4ai_tools

    client = MagicMock()
    client.fetch_markdown = AsyncMock(return_value=markdown)
    with (
        patch.object(crawl4ai_tools, "_build_client", return_value=client),
        patch.object(crawl4ai_tools, "_get_tool_config", return_value=None),
        patch.object(crawl4ai_tools, "validate_public_http_url", return_value=None),
        patch.object(crawl4ai_tools, "_validate_backend_base_url", return_value=None),
    ):
        rendered = asyncio.run(crawl4ai_tools.web_fetch_tool.ainvoke("https://example.org/x"))
    assert _meta(_through_chain(_msg(rendered)))["status"] == "success"
