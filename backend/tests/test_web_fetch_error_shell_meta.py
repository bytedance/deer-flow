"""web_fetch error-page classification (issue #4273).

Fetching a missing URL succeeds at the transport layer, so the server's error page
reached the model stamped ``deerflow_tool_meta.status="success"``: none of the existing
error branches (tool ``status="error"``, an ``Error:`` prefix, a JSON ``error`` field)
apply to a 200-with-an-error-body, and it fell through to success. ToolProgress then
counted the shell as evidence.

The classifier keys on the *extracted title* being nothing but an HTTP status line.
``TestRenderedByRealProducer`` is the load-bearing suite: it drives the real
``web_fetch_tool`` over real server error-page HTML, so the payload shape under test is
the one production actually produces rather than a hand-written approximation.

Every assertion checks the whole metadata tuple, not just ``status``.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_result_meta import (
    _ATTRS_BY_ERROR_TYPE,
    _ERROR_SHELL_PHRASES,
    TOOL_META_KEY,
    _classify_error_shell,
    _classify_error_text,
    normalize_tool_message,
)

_SUBSTANTIVE_BODY = "Rice is a staple for most of the planet, and the difference between good rice and great rice is almost always technique rather than equipment."


def _msg(content: str, *, name: str = "web_fetch", status: str = "success") -> ToolMessage:
    return ToolMessage(content=content, tool_call_id="tc-1", name=name, status=status, additional_kwargs={})


def _meta(msg: ToolMessage) -> dict[str, object]:
    return msg.additional_kwargs[TOOL_META_KEY]


def _tuple(status: str, error_type: str | None, recoverable: bool, next_action: str) -> dict[str, object]:
    return {
        "status": status,
        "error_type": error_type,
        "recoverable_by_model": recoverable,
        "recommended_next_action": next_action,
        "source": "content_analysis",
    }


_SUCCESS = _tuple("success", None, True, "continue")


# ---------------------------------------------------------------------------
# Titles that are nothing but a status line


@pytest.mark.parametrize(
    "title,error_type,recoverable,next_action",
    [
        ("# 404 Not Found", "not_found", True, "rewrite_query"),
        ("# Page not found", "not_found", True, "rewrite_query"),
        ("# Not Found", "not_found", True, "rewrite_query"),
        ("# 404 - File or directory not found.", "not_found", True, "rewrite_query"),
        ("# HTTP Error 404 - Not Found", "not_found", True, "rewrite_query"),
        ("# 403 Forbidden", "permission", True, "try_alternative"),
        ("# Access Denied", "permission", True, "try_alternative"),
        ("# Permission denied", "permission", True, "try_alternative"),
        ("# 401 Unauthorized", "auth", False, "stop"),
        ("# 407 Proxy Authentication Required", "auth", False, "stop"),
        ("# 429 Too Many Requests", "rate_limited", False, "summarize"),
        # The 5xx split (review on #4314): 500/501 stay `internal` (stop), 502/503/504
        # are `transient` (try_alternative) — a gateway error page warns and escalates
        # instead of hard-blocking web_fetch on first sight.
        ("# 500 Internal Server Error", "internal", False, "stop"),
        ("# 501 Not Implemented", "internal", False, "stop"),
        ("# 502 Bad Gateway", "transient", False, "try_alternative"),
        ("# 503 Service Unavailable", "transient", False, "try_alternative"),
        ("# 503 Service Temporarily Unavailable", "transient", False, "try_alternative"),
        ("# 504 Gateway Timeout", "transient", False, "try_alternative"),
    ],
)
def test_status_line_title_is_classified_as_error(title: str, error_type: str, recoverable: bool, next_action: str):
    content = f"{title}\n\n---\n\nnginx/1.24.0"

    assert _meta(normalize_tool_message(_msg(content))) == _tuple("error", error_type, recoverable, next_action)


def test_body_prose_does_not_rescue_an_error_title():
    """Apache ships a sentence of body; it is still an error page."""
    content = "# 404 Not Found\n\nThe requested URL was not found on this server.\n\n---\n\nApache/2.4.58"

    assert _meta(normalize_tool_message(_msg(content)))["error_type"] == "not_found"


# ---------------------------------------------------------------------------
# Negative controls: documents that merely mention a status stay successful.


@pytest.mark.parametrize(
    "content",
    [
        # Legitimate titles that begin with a bare status number. This is why a bare
        # numeric code is stripped but never matched on its own.
        f"# 404 Ways to Cook Rice\n\n{_SUBSTANTIVE_BODY}",
        "# 404 Ways to Cook Rice",
        f"# 404 ways to improve API reliability\n\n{_SUBSTANTIVE_BODY}",
        "# 500 Startup Ideas Worth Stealing",
        "# 403",
        "404",
        # A document *about* a status: the phrase is there, but so are other words, and
        # matching is by equality. This is the case a substring scan would break.
        f"# Not Found: a short history of the 404\n\n{_SUBSTANTIVE_BODY}",
        "# Not Found: a short history of the 404",
        "# The Page Not Found Problem",
        "# Forbidden Planet",
        # Single-word document titles that collide with a reason phrase. "Gone" was dropped
        # from the phrase table for exactly this reason (410 is rare; the title is not), so
        # this is the control that records the decision.
        "# Gone",
        "# Gone\n\nA novel about a disappearance.",
        # API documentation listing status codes. Every reason phrase appears verbatim
        # as its own line, so this is what keeps the rule anchored to the *title* rather
        # than scanning the body. Dropping it makes a whole-document scan look safe.
        "# HTTP Status Codes\n\nThe most common client errors are:\n\nNot Found\n\nForbidden\n\nToo Many Requests\n\nAll are defined in RFC 9110.",
        f"# Debugging 404s\n\nWhen a page is not found, check the router first.\n\n{_SUBSTANTIVE_BODY}",
        # Explicitly *not* failure evidence per the issue triage: an untitled page, an
        # untitled-but-substantive page, and short valid content.
        "# Untitled",
        f"# Untitled\n\n{_SUBSTANTIVE_BODY}",
        "# Untitled\n\nNo content could be extracted from this page",
        "# Status\n\nAll systems operational.",
        "OK",
        # Empty / whitespace-only content must not be classified as an error.
        "",
        "   \n\n  ",
    ],
)
def test_document_content_stays_successful(content: str):
    assert _meta(normalize_tool_message(_msg(content))) == _SUCCESS


# ---------------------------------------------------------------------------
# Cross-path consistency: a phrase must not classify differently through the shell
# table than the same words would through _classify_error_text. (Review on #4314:
# "service temporarily unavailable" was `internal` here while _ERROR_RULES'
# "temporarily unavailable" keyword → `transient`; "gateway timeout" had the same
# split via the "timeout" keyword.) Phrases the keyword rules are silent on pass
# vacuously — the table deliberately knows phrases the rules don't.


@pytest.mark.parametrize("phrase,shell_type", sorted(_ERROR_SHELL_PHRASES.items()))
def test_shell_phrase_category_agrees_with_the_keyword_rules(phrase: str, shell_type: str):
    rules_type = _classify_error_text(phrase)["error_type"]

    assert rules_type in ("unknown", shell_type)


def test_shell_attrs_are_a_fresh_copy_per_call():
    """Match _classify_error_text's copy pattern: never hand out the rules-table dict."""
    msg = _msg("# 404 Not Found")
    first = _classify_error_shell(msg, "# 404 Not Found")
    second = _classify_error_shell(msg, "# 404 Not Found")

    assert first == _ATTRS_BY_ERROR_TYPE["not_found"]
    assert first is not _ATTRS_BY_ERROR_TYPE["not_found"]
    assert first is not second


def test_partial_marker_on_web_fetch_still_wins():
    """Direction two: the new branch must not swallow the existing partial path."""
    meta = _meta(normalize_tool_message(_msg("No results found")))

    assert meta["status"] == "partial_success"
    assert meta["recommended_next_action"] == "rewrite_query"


def test_existing_structured_stamp_is_not_overwritten():
    """Composition, not reclassification: a producer that already stamped wins."""
    existing = {"status": "partial_success", "source": "tool_return", "error_type": None}
    msg = ToolMessage(content="# 404 Not Found", tool_call_id="tc-1", name="web_fetch", additional_kwargs={TOOL_META_KEY: existing})

    assert _meta(normalize_tool_message(msg)) is existing


# ---------------------------------------------------------------------------
# Scoping: normalize_tool_message() normalizes EVERY tool, so the rule is gated on
# web_fetch identity. Other tools legitimately return these exact words.


@pytest.mark.parametrize("tool_name", ["read_file", "bash", "grep", "web_search", "memory_search", "test_tool"])
@pytest.mark.parametrize("content", ["# 404 Not Found", "Access denied", "Not Found", "Too Many Requests"])
def test_unrelated_tools_returning_the_same_wording_are_unchanged(tool_name: str, content: str):
    assert _meta(normalize_tool_message(_msg(content, name=tool_name))) == _SUCCESS


def test_unnamed_tool_message_is_unchanged():
    msg = ToolMessage(content="# 404 Not Found", tool_call_id="tc-1", additional_kwargs={})

    assert _meta(normalize_tool_message(msg)) == _SUCCESS


# ---------------------------------------------------------------------------
# Rendered by the real producer, then through the real middleware chain.

_NGINX_404 = "<html>\r\n<head><title>404 Not Found</title></head>\r\n<body>\r\n<center><h1>404 Not Found</h1></center>\r\n<hr><center>nginx/1.24.0</center>\r\n</body>\r\n</html>\r\n"
_NGINX_503 = "<html>\r\n<head><title>503 Service Temporarily Unavailable</title></head>\r\n<body>\r\n<center><h1>503 Service Temporarily Unavailable</h1></center>\r\n<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
_APACHE_403 = "<html><head>\n<title>403 Forbidden</title>\n</head><body>\n<h1>Forbidden</h1>\n<p>You don't have permission to access this resource.</p>\n<hr>\n<address>Apache/2.4.58 Server at example.org</address>\n</body></html>\n"
_IIS_404 = "<!DOCTYPE html>\n<html>\n<head><title>404 - File or directory not found.</title></head>\n<body>\n<h2>404 - File or directory not found.</h2>\n<h3>The resource may have been removed.</h3>\n</body>\n</html>\n"
_CLOUDFLARE_429 = "<!DOCTYPE html><html><head><title>429 Too Many Requests</title></head><body><center><h1>429 Too Many Requests</h1></center><hr><center>cloudflare</center></body></html>"
_SPA_404 = "<!DOCTYPE html><html><head><title>Page not found</title></head><body><div id=root><h1>Page not found</h1><p>Sorry, we couldn't find that page.</p></div></body></html>"
_LEGIT_ARTICLE = "<html><head><title>404 Ways to Cook Rice</title></head><body><article><h1>404 Ways to Cook Rice</h1><p>Rice is a staple for most of the planet, and great rice is technique.</p></article></body></html>"
_LEGIT_ESSAY = "<html><head><title>Not Found: a short history of the 404</title></head><body><article><h1>Not Found: a short history of the 404</h1><p>The code was introduced at CERN.</p></article></body></html>"


def _render(html: str, code: str, status: str) -> str:
    """Run the real web_fetch_tool over *html*; only the network client is faked."""
    from deerflow.community.browserless import tools as browserless_tools
    from deerflow.community.browserless.browserless_client import BrowserlessFetchResult

    client = MagicMock()
    client.fetch_html_with_status = AsyncMock(return_value=BrowserlessFetchResult(html=html, target_status_code=code, target_status=status))
    with (
        patch.object(browserless_tools, "_get_browserless_client", return_value=client),
        patch.object(browserless_tools, "_get_tool_config", return_value=None),
        patch.object(browserless_tools, "validate_public_http_url", return_value=None),
    ):
        return asyncio.run(browserless_tools.web_fetch_tool.ainvoke("https://example.org/x"))


def _through_chain(content: str, *, tool_name: str = "web_fetch", progress: ToolProgressMiddleware | None = None) -> ToolMessage:
    """Real ToolProgressMiddleware -> ToolErrorHandlingMiddleware nesting.

    ToolProgress is the outer wrapper around ToolErrorHandling (backend/AGENTS.md,
    middleware chain #12/#13), so this is the production order. Pass *progress* to
    share stagnation state across calls.
    """
    progress = progress if progress is not None else ToolProgressMiddleware()
    errors = ToolErrorHandlingMiddleware()
    runtime = MagicMock()
    runtime.context = {"thread_id": "t1", "run_id": "r1"}
    request = SimpleNamespace(tool_call={"name": tool_name, "id": "tc-1"}, runtime=runtime)

    def tool(_req):
        return ToolMessage(content=content, tool_call_id="tc-1", name=tool_name, additional_kwargs={})

    return progress.wrap_tool_call(request, lambda req: errors.wrap_tool_call(req, tool))


class TestRenderedByRealProducer:
    """Real server error-page HTML -> real web_fetch_tool -> real middleware chain."""

    @pytest.mark.parametrize(
        "html,code,status,error_type,recoverable,next_action",
        [
            (_NGINX_404, "404", "Not Found", "not_found", True, "rewrite_query"),
            (_APACHE_403, "403", "Forbidden", "permission", True, "try_alternative"),
            (_IIS_404, "404", "Not Found", "not_found", True, "rewrite_query"),
            (_CLOUDFLARE_429, "429", "Too Many Requests", "rate_limited", False, "summarize"),
            (_NGINX_503, "503", "Service Temporarily Unavailable", "transient", False, "try_alternative"),
            (_SPA_404, "404", "Not Found", "not_found", True, "rewrite_query"),
        ],
    )
    def test_error_pages_are_classified(self, html: str, code: str, status: str, error_type: str, recoverable: bool, next_action: str):
        rendered = _render(html, code, status)

        assert _meta(_through_chain(rendered)) == _tuple("error", error_type, recoverable, next_action)

    @pytest.mark.parametrize("html", [_LEGIT_ARTICLE, _LEGIT_ESSAY])
    def test_legitimate_pages_stay_successful(self, html: str):
        rendered = _render(html, "200", "OK")

        assert _meta(_through_chain(rendered)) == _SUCCESS

    def test_target_status_warning_from_4239_does_not_break_the_title(self):
        """#4239 appends the target status to the rendered markdown; compose with it."""
        rendered = _render(_NGINX_404, "404", "Not Found")

        assert "warning: target page responded 404 Not Found" in rendered
        assert _meta(_through_chain(rendered))["status"] == "error"

    def test_missing_provider_status_still_classifies_from_content(self):
        """No X-Response-Code header: the content-only fallback must still fire."""
        rendered = _render(_NGINX_404, "", "")

        assert "warning:" not in rendered
        assert _meta(_through_chain(rendered)) == _tuple("error", "not_found", True, "rewrite_query")

    def test_chain_negative_control_unrelated_tool(self):
        rendered = _render(_NGINX_404, "404", "Not Found")

        assert _meta(_through_chain(rendered, tool_name="read_file")) == _SUCCESS

    def test_gateway_error_page_warns_and_escalates_instead_of_blocking_on_sight(self):
        """The 5xx split's behavioral consequence (review on #4314): a 503 page is
        `transient`, so web_fetch keeps executing through the warn window (calls 1-5,
        WARNED at 3, escalation at 3+2) instead of `internal`'s first-sight block —
        while repeated failures still end in BLOCKED, so the guard is not hollowed out."""
        rendered = _render(_NGINX_503, "503", "Service Temporarily Unavailable")
        progress = ToolProgressMiddleware()

        results = [_through_chain(rendered, progress=progress) for _ in range(6)]

        for executed in results[:5]:
            assert _meta(executed)["error_type"] == "transient"
        assert _meta(results[5])["error_type"] == "blocked_by_progress_guard"
        assert results[5].content.startswith("[TOOL_BLOCKED]")


# Measured output of crawl4ai 0.9.2's DefaultMarkdownGenerator over the same corpus
# HTML: "fit" (PruningContentFilter — the tool's default f=fit) shown; "raw" agrees on
# the leading line. The body heading renders first, so the title rule keys on the same
# line the in-process renderers produce.
_CRAWL4AI_NGINX_404_FIT = "# 404 Not Found\nnginx/1.24.0\n"
_CRAWL4AI_NGINX_503_FIT = "# 503 Service Temporarily Unavailable\nnginx\n"
_CRAWL4AI_ARTICLE_FIT = "# 404 Ways to Cook Rice\nRice is a staple for most of the planet, and great rice is technique.\n"


def _render_crawl4ai(markdown: str) -> str:
    """Run the real crawl4ai web_fetch_tool; only the remote /md call is faked."""
    from deerflow.community.crawl4ai import tools as crawl4ai_tools

    client = MagicMock()
    client.fetch_markdown = AsyncMock(return_value=markdown)
    with (
        patch.object(crawl4ai_tools, "_build_client", return_value=client),
        patch.object(crawl4ai_tools, "_get_tool_config", return_value=None),
        patch.object(crawl4ai_tools, "validate_public_http_url", return_value=None),
    ):
        return asyncio.run(crawl4ai_tools.web_fetch_tool.ainvoke("https://example.org/x"))


class TestCrawl4aiRecordedProducer:
    """crawl4ai renders server-side (POST /md), so its renderer cannot run in-repo.

    The fixtures above are recorded from the real generator (provenance in the comment);
    these tests pin our handling of that recorded shape through the real tool and the
    real middleware chain. A future server-side format change is out of this repo's
    reach and would degrade to a silent success — the safe direction (no false
    positives), accepted in review.
    """

    @pytest.mark.parametrize(
        "markdown,error_type,recoverable,next_action",
        [
            (_CRAWL4AI_NGINX_404_FIT, "not_found", True, "rewrite_query"),
            (_CRAWL4AI_NGINX_503_FIT, "transient", False, "try_alternative"),
        ],
    )
    def test_recorded_error_pages_are_classified(self, markdown: str, error_type: str, recoverable: bool, next_action: str):
        rendered = _render_crawl4ai(markdown)

        assert _meta(_through_chain(rendered)) == _tuple("error", error_type, recoverable, next_action)

    def test_recorded_legitimate_page_stays_successful(self):
        rendered = _render_crawl4ai(_CRAWL4AI_ARTICLE_FIT)

        assert _meta(_through_chain(rendered)) == _SUCCESS
