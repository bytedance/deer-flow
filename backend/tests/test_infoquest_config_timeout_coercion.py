"""InfoQuest reads its crawl timeouts straight out of ``config.yaml``.

``config.example.yaml`` documents ``timeout``, ``fetch_time`` and ``navigation_timeout``
as seconds (with -1 to disable), and a ``$VAR`` reference in the config is substituted
verbatim from the environment, so the value the tool receives can be a string. The
client then compares those values with ``0``, which raises for anything but a number and
takes the whole ``web_fetch`` / ``web_search`` call down with it.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from deerflow.community.infoquest import tools

_URL = "https://example.com"
_FETCH_PAYLOAD = {"reader_result": "<p>Content</p>"}
_SEARCH_PAYLOAD = {"search_result": {"results": []}}


def _app_config(web_search=None, web_fetch=None, image_search=None):
    """One get_app_config() double whose tool sections are read in order.

    The tool calls get_app_config() once per section, so the same double must be
    returned every time or its read queue restarts and the wrong section is served.
    """
    config = MagicMock()
    config.get_tool_config.side_effect = [
        MagicMock(model_extra=web_search or {}),
        MagicMock(model_extra=web_fetch or {}),
        MagicMock(model_extra=image_search or {}),
    ]
    return config


def _mock_transport(monkeypatch, payload):
    client = MagicMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = None
    client.post = AsyncMock(
        return_value=httpx.Response(
            200,
            json=payload,
            request=httpx.Request("POST", "https://search.infoquest.bytepluses.com"),
        )
    )
    cls = MagicMock()
    cls.return_value = client
    monkeypatch.setattr("deerflow.community.infoquest.infoquest_client.httpx.AsyncClient", cls)
    monkeypatch.setenv("INFOQUEST_API_KEY", "test-placeholder")
    return client


def _client_from_config(monkeypatch, **extras):
    config = _app_config(**extras)
    monkeypatch.setattr(tools, "get_app_config", lambda: config)
    return tools._get_infoquest_client()


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("10", 10),
        (" 10 ", 10),
        ("-1", -1),
        (10, 10),
        (10.0, 10),
        ("", -1),
        ("off", -1),
        (2.5, -1),
        (True, -1),
        (None, -1),
        ({"seconds": 10}, -1),
    ],
)
def test_timeouts_reach_the_client_as_integers(monkeypatch, configured, expected):
    client = _client_from_config(monkeypatch, web_fetch={"timeout": configured})

    assert client.fetch_timeout == expected
    assert isinstance(client.fetch_timeout, int)


def test_configured_numbers_keep_their_meaning(monkeypatch):
    """The shapes that already work must not change."""
    client = _client_from_config(
        monkeypatch,
        web_search={"search_time_range": 24},
        web_fetch={"timeout": 10, "fetch_time": 5, "navigation_timeout": 30},
        image_search={"image_search_time_range": 7, "image_size": "l"},
    )

    assert (client.search_time_range, client.image_search_time_range) == (24, 7)
    assert (client.fetch_timeout, client.fetch_time, client.fetch_navigation_timeout) == (10, 5, 30)


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("10", 10),
        ("", -1),
        ("off", -1),
        (None, -1),
    ],
)
def test_string_timeouts_apply_to_every_configured_option(monkeypatch, configured, expected):
    client = _client_from_config(
        monkeypatch,
        web_search={"search_time_range": configured},
        web_fetch={"timeout": configured, "fetch_time": configured, "navigation_timeout": configured},
        image_search={"image_search_time_range": configured},
    )

    assert client.search_time_range == expected
    assert client.fetch_timeout == expected
    assert client.fetch_time == expected
    assert client.fetch_navigation_timeout == expected
    assert client.image_search_time_range == expected


@pytest.mark.anyio
async def test_env_string_timeout_reaches_the_crawl_request_as_a_number(monkeypatch):
    """``timeout: $FETCH_TIMEOUT`` is documented, and an outbound crawl must carry 10."""
    client = _client_from_config(
        monkeypatch,
        web_fetch={"timeout": "10", "navigation_timeout": "30", "fetch_time": "5"},
    )
    transport = _mock_transport(monkeypatch, _FETCH_PAYLOAD)

    assert await client.fetch(_URL) == "<p>Content</p>"

    sent = transport.post.call_args.kwargs["json"]
    assert sent["timeout"] == 10
    assert sent["navi_timeout"] == 30
    assert sent["fetch_time"] == 5


@pytest.mark.anyio
async def test_env_string_time_range_reaches_the_search_request_as_a_number(monkeypatch):
    client = _client_from_config(monkeypatch, web_search={"search_time_range": "24"})
    transport = _mock_transport(monkeypatch, _SEARCH_PAYLOAD)

    assert await client.web_search("query") == "[]"

    assert transport.post.call_args.kwargs["json"]["time_range"] == 24


@pytest.mark.anyio
async def test_an_unusable_timeout_disables_the_filter_instead_of_failing_the_tool(monkeypatch, caplog):
    client = _client_from_config(
        monkeypatch,
        web_fetch={"timeout": "", "navigation_timeout": "off"},
    )
    transport = _mock_transport(monkeypatch, _FETCH_PAYLOAD)

    assert await client.fetch(_URL) == "<p>Content</p>"

    sent = transport.post.call_args.kwargs["json"]
    assert "timeout" not in sent
    assert "navi_timeout" not in sent
    assert "fetch_time" not in sent
    assert "Invalid InfoQuest" in caplog.text
