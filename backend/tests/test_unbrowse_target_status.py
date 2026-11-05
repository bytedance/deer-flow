"""Preserve the target HTTP status across both Unbrowse MCP payload forms."""

import json
from types import SimpleNamespace

import httpx
import pytest

from deerflow.community.unbrowse import tools


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503, 599])
@pytest.mark.parametrize("markdown", ["Body", "", None])
def test_fetch_warns_about_target_http_failure(monkeypatch, structured, status, markdown):
    result = _fetch(monkeypatch, structured, {"title": "Page", "statusCode": status}, markdown=markdown)
    if markdown:
        assert result == f"Warning: target page responded with HTTP {status}.\n\n# Page\n\nBody"
    else:
        assert result == f"Error: No content found (target page responded with HTTP {status})"


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", "", None])
def test_fetch_reports_redirect_destination_for_target_failure(monkeypatch, structured, markdown):
    result = _fetch(monkeypatch, structured, {"title": "Page", "statusCode": 404}, markdown=markdown, finalUrl="https://example.invalid/missing")
    detail = "target page responded with HTTP 404 (final URL: https://example.invalid/missing)"
    if markdown:
        assert result == f"Warning: {detail}.\n\n# Page\n\nBody"
    else:
        assert result == f"Error: No content found ({detail})"


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
def test_fetch_bounds_redirect_destination(monkeypatch, structured):
    final_url = "https://example.invalid/?next=" + "x" * 10_000

    result = _fetch(monkeypatch, structured, {"statusCode": 404}, finalUrl=final_url)

    assert final_url[:500] in result
    assert final_url[:501] not in result


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", ""], ids=["warning", "error"])
@pytest.mark.parametrize(
    ("final_url", "safe_url", "secrets"),
    [
        ("https://alice:password@example.invalid/private", "https://example.invalid/private", ("alice", "password")),
        (
            "https://bob:p%40ss@[2001:db8::1]:8443/private",
            "https://[2001:db8::1]:8443/private",
            ("bob", "p%40ss"),
        ),
    ],
)
def test_fetch_strips_userinfo_from_failure_redirect_destination(monkeypatch, structured, markdown, final_url, safe_url, secrets):
    result = _fetch(monkeypatch, structured, {"statusCode": 404}, markdown=markdown, finalUrl=final_url)

    assert f"final URL: {safe_url}" in result
    assert all(secret not in result for secret in secrets)


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("final_url", [None, "", "   ", 42, {}, []])
def test_fetch_ignores_empty_or_non_string_final_url(monkeypatch, structured, final_url):
    result = _fetch(monkeypatch, structured, {"statusCode": 404}, finalUrl=final_url)
    assert result == "Warning: target page responded with HTTP 404.\n\n# Untitled\n\nBody"


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", "", None])
def test_fetch_preserves_success_response_with_final_url(monkeypatch, structured, markdown):
    result = _fetch(monkeypatch, structured, {"statusCode": 200}, markdown=markdown, finalUrl="https://example.invalid/redirected")
    assert result == ("# Untitled\n\nBody" if markdown else "Error: No content found")


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("metadata", [None, {}, {"statusCode": 200}, {"statusCode": 301}, {"statusCode": None}, {"statusCode": "404"}, {"statusCode": True}, {"statusCode": 404.5}, {"statusCode": []}, {"statusCode": 600}])
def test_fetch_preserves_response_without_valid_error_status(monkeypatch, structured, metadata):
    assert _fetch(monkeypatch, structured, metadata) == "# Untitled\n\nBody"


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", "", None], ids=["warning", "empty", "null"])
@pytest.mark.parametrize(
    "final_url,safe_url,secret",
    [
        ("https://alice:synthetic-password@example.invalid:8443/missing?next=a%2Fb#part", "https://example.invalid:8443/missing?next=a%2Fb#part", "synthetic-password"),
        ("https://alice@example.invalid/missing", "https://example.invalid/missing", "alice"),
        ("https://alice:synthetic%40password@example.invalid/missing", "https://example.invalid/missing", "synthetic%40password"),
        ("https://alice:synthetic@password@example.invalid/missing", "https://example.invalid/missing", "synthetic@password"),
        ("https://alice:synthetic-password@[2001:db8::1]:8443/missing", "https://[2001:db8::1]:8443/missing", "synthetic-password"),
    ],
    ids=["password", "username-only", "encoded", "at-in-password", "ipv6"],
)
def test_fetch_removes_final_url_userinfo(monkeypatch, structured, markdown, final_url, safe_url, secret):
    result = _fetch(monkeypatch, structured, {"title": "Page", "statusCode": 404}, markdown=markdown, finalUrl=final_url)
    detail = f"target page responded with HTTP 404 (final URL: {safe_url})"
    expected = f"Warning: {detail}.\n\n# Page\n\nBody" if markdown else f"Error: No content found ({detail})"
    assert result == expected
    assert secret not in result


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", ""], ids=["warning", "empty"])
def test_fetch_strips_userinfo_before_clipping_final_url(monkeypatch, structured, markdown):
    secret = "synthetic-password-" + "s" * 600
    safe_url = "https://example.invalid/missing?next=" + "x" * 10_000
    final_url = "https://alice:" + secret + "@" + safe_url.removeprefix("https://")
    result = _fetch(monkeypatch, structured, {"statusCode": 404}, markdown=markdown, finalUrl=final_url)
    assert secret[:500] not in result
    assert "alice:" not in result
    assert safe_url[:500] in result
    assert safe_url[:501] not in result


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("markdown", ["Body", ""], ids=["warning", "empty"])
@pytest.mark.parametrize(
    "final_url", ["https://alice:synthetic-password@[broken/missing", "https:/alice:synthetic-password@example.invalid/missing", "https://alice:synthetic-password@/missing"], ids=["invalid-brackets", "missing-authority", "missing-host"]
)
def test_fetch_omits_unparseable_final_url_without_echoing_credentials(monkeypatch, structured, markdown, final_url):
    result = _fetch(monkeypatch, structured, {"statusCode": 404}, markdown=markdown, finalUrl=final_url)
    detail = "target page responded with HTTP 404"
    expected = f"Warning: {detail}.\n\n# Untitled\n\nBody" if markdown else f"Error: No content found ({detail})"
    assert result == expected
    assert "synthetic-password" not in result


@pytest.mark.parametrize("structured", [False, True], ids=["text", "structured"])
@pytest.mark.parametrize("length", [499, 500, 501], ids=["below-limit", "at-limit", "over-limit"])
def test_fetch_keeps_userinfo_free_final_urls_unchanged_up_to_limit(monkeypatch, structured, length):
    prefix = "HTTPS://Example.invalid:8443/path@team?email=person@example.invalid&next="
    final_url = prefix + "x" * (length - len(prefix))
    result = _fetch(monkeypatch, structured, {"statusCode": 404}, finalUrl="  " + final_url + "  ")
    assert result == f"Warning: target page responded with HTTP 404 (final URL: {final_url[:500]}).\n\n# Untitled\n\nBody"


def _fetch(monkeypatch, structured, metadata, markdown="Body", **fields):
    payload = {"markdown": markdown, "metadata": metadata, **fields}
    result = {"content": [{"type": "text", "text": json.dumps(payload)}], "isError": False}
    if structured:
        result["structuredContent"] = payload
    requests = []

    def respond(request):
        requests.append(request)
        assert json.loads(request.content)["params"]["name"] == "unbrowse.scrape"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})

    real_client = httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(tools.httpx, "Client", lambda **kwargs: real_client(transport=transport, **kwargs))
    monkeypatch.setattr(tools, "get_app_config", lambda: SimpleNamespace(get_tool_config=lambda _: SimpleNamespace(model_extra={"api_key": "synthetic"})))
    output = tools.web_fetch_tool.invoke({"url": "https://example.invalid/page"})
    assert len(requests) == 1
    return output
