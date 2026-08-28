import json
from unittest.mock import MagicMock, patch


def _config(**extra):
    cfg = MagicMock()
    cfg.model_extra = extra
    return cfg


def test_playwright_web_fetch_uses_config_and_truncates():
    from deerflow.community.playwright import tools

    def get_tool_config(name):
        if name == "web_fetch":
            return _config(
                base_url="http://playwright:3000/scrape",
                wait_for_ms=1234,
                timeout_s=9,
                retries=0,
                max_chars=10,
            )
        return None

    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"content": "abcdefghijklmnopqrstuvwxyz", "pageStatusCode": 200}).encode()
    response.__enter__.return_value = response

    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.urllib.request.urlopen", return_value=response) as mock_urlopen,
    ):
        mock_get_app_config.return_value.get_tool_config.side_effect = get_tool_config
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert result == "abcdefghij\n\n[truncated to 10 characters]"
    mock_get_app_config.return_value.get_tool_config.assert_called_with("web_fetch")
    request = mock_urlopen.call_args.args[0]
    assert request.full_url == "http://playwright:3000/scrape"
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/json"
    assert mock_urlopen.call_args.kwargs["timeout"] == 9
    assert json.loads(request.data.decode()) == {"url": "https://example.com/page", "waitFor": 1234}


def test_playwright_web_fetch_prefers_markdown_content():
    from deerflow.community.playwright import tools

    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps(
        {
            "html": "<h1>Rendered HTML</h1>",
            "content": "Rendered text",
            "markdown": "# Rendered markdown",
            "pageStatusCode": 200,
        }
    ).encode()
    response.__enter__.return_value = response

    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.urllib.request.urlopen", return_value=response),
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config(retries=0)
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert result == "# Rendered markdown"


def test_playwright_web_fetch_rejects_json_without_content():
    from deerflow.community.playwright import tools

    response = MagicMock()
    response.status = 200
    response.read.return_value = json.dumps({"status": 200}).encode()
    response.__enter__.return_value = response

    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.urllib.request.urlopen", return_value=response),
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config(retries=0)
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert result == "Error: no content (status=200)"


def test_playwright_web_fetch_retries_after_initial_attempt():
    from deerflow.community.playwright import tools

    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.time.sleep") as mock_sleep,
        patch(
            "deerflow.community.playwright.tools.urllib.request.urlopen",
            side_effect=tools.urllib.error.URLError("temporary failure"),
        ) as mock_urlopen,
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config(retries=2, retry_delay_s=0.01)
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert mock_urlopen.call_count == 3
    assert mock_sleep.call_count == 2
    assert result.startswith("Error: Playwright fetch failed after 3 attempt(s):")


def test_playwright_web_fetch_does_not_retry_non_retryable_http_error():
    from deerflow.community.playwright import tools

    error = tools.urllib.error.HTTPError(
        url="http://playwright:3000/scrape",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=None,
    )
    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.time.sleep") as mock_sleep,
        patch("deerflow.community.playwright.tools.urllib.request.urlopen", side_effect=error) as mock_urlopen,
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config(retries=2, retry_delay_s=0.01)
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert mock_urlopen.call_count == 1
    assert mock_sleep.call_count == 0
    assert result.startswith("Error: Playwright fetch failed after 1 attempt(s):")


def test_playwright_web_fetch_retries_retryable_http_error():
    from deerflow.community.playwright import tools

    error = tools.urllib.error.HTTPError(
        url="http://playwright:3000/scrape",
        code=503,
        msg="Service Unavailable",
        hdrs=None,
        fp=None,
    )
    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value=None),
        patch("deerflow.community.playwright.tools.time.sleep") as mock_sleep,
        patch("deerflow.community.playwright.tools.urllib.request.urlopen", side_effect=error) as mock_urlopen,
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config(retries=2, retry_delay_s=0.01)
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert mock_urlopen.call_count == 3
    assert mock_sleep.call_count == 2
    assert result.startswith("Error: Playwright fetch failed after 3 attempt(s):")


def test_playwright_web_fetch_rejects_private_url_by_default():
    from deerflow.community.playwright import tools

    with patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config:
        mock_get_app_config.return_value.get_tool_config.return_value = _config()
        result = tools.web_fetch_tool.invoke({"url": "http://127.0.0.1/admin"})

    assert result.startswith("Error: Refusing to fetch")


def test_playwright_web_fetch_returns_validation_error_verbatim():
    from deerflow.community.playwright import tools

    with (
        patch("deerflow.community.playwright.tools.get_app_config") as mock_get_app_config,
        patch("deerflow.community.playwright.tools.validate_public_http_url", return_value="Blocked by policy"),
    ):
        mock_get_app_config.return_value.get_tool_config.return_value = _config()
        result = tools.web_fetch_tool.invoke({"url": "https://example.com/page"})

    assert result == "Blocked by policy"
