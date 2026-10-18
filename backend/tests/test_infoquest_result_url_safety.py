"""InfoQuest screens every untrusted result URL through the shared owner.

``community/url_safety.safe_public_result_url`` is the single owner for the
result-URL policy the sibling providers already follow (brave and serper import
it under the ``_safe_public_url`` alias, and their ``AGENTS.md`` says "do not
add a provider-local copy"). InfoQuest registers the ``image_search`` tool too,
so the policy covers its three result fields: ``organic[].url``,
``top_stories.items[].url`` and ``images_results[].original``.

A row whose URL is not a public HTTP(S) result is dropped rather than raising:
one hostile entry must not turn an otherwise valid search into the provider's
format error, which is the containment rule #6932 established for this client.
"""

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from deerflow.community import url_safety
from deerflow.community.infoquest import infoquest_client as infoquest_module
from deerflow.community.infoquest.infoquest_client import InfoQuestClient

NON_PUBLIC_URLS: list[Any] = [
    "http://127.0.0.1/record",
    "http://localhost./record",
    "http://metadata.google.internal/record",
    "http://169.254.169.254/latest/meta-data",
    "http://224.0.0.1/record",
    "http://240.0.0.1/record",
    "http://3758096385/record",
    "http://0x7f000001/record",
    "http://0177.0.0.1/record",
    "http://[::ffff:127.0.0.1]/record",
    "http://[64:ff9b::7f00:1]/record",
    "http://[2002:7f00:1::]/record",
    "http://[ff02::1]/record",
    "http://127。0。0。1/record",
    "file:///etc/passwd",
    "",
    "   ",
    None,
    {"url": "https://example.com"},
]

PUBLIC_URL = "https://example.com/keep"


def _envelope(**sections: Any) -> list[dict]:
    return [{"content": {"results": sections}}]


def _rows_for(field: str, url: Any) -> list[dict]:
    if field == "images_results":
        return [{"original": url, "title": "Row"}]
    return [{"url": url, "title": "Row"}]


def _clean(field: str, url: Any) -> list[dict]:
    if field == "images_results":
        return InfoQuestClient.clean_results_with_image_search(_envelope(images_results=_rows_for(field, url)))
    if field == "top_stories":
        return InfoQuestClient.clean_results(_envelope(top_stories={"items": [{"url": url, "title": "Row", "source": "wire"}]}))
    return InfoQuestClient.clean_results(_envelope(organic=[{"url": url, "title": "Row"}]))


def test_client_uses_the_shared_owner_without_a_local_copy():
    assert infoquest_module._safe_public_url is url_safety.safe_public_result_url


@pytest.mark.parametrize("field", ["organic", "images_results", "top_stories"])
@pytest.mark.parametrize("url", NON_PUBLIC_URLS)
def test_non_public_result_urls_are_dropped(field, url):
    assert _clean(field, url) == []


@pytest.mark.parametrize("field", ["organic", "images_results", "top_stories"])
def test_public_result_urls_are_kept(field):
    cleaned = _clean(field, PUBLIC_URL)

    assert len(cleaned) == 1
    assert PUBLIC_URL in json.dumps(cleaned, ensure_ascii=False)


def test_screened_value_is_the_one_returned():
    # Returning the raw string after screening only the decision would hand the
    # model a URL the owner never vetted.
    organic = InfoQuestClient.clean_results(_envelope(organic=[{"url": "  https://example.com/p  ", "title": "Row"}]))
    images = InfoQuestClient.clean_results_with_image_search(_envelope(images_results=[{"original": "  https://example.com/p  ", "title": "Row"}]))
    news = InfoQuestClient.clean_results(_envelope(top_stories={"items": [{"url": "  https://example.com/p  ", "title": "Row"}]}))

    assert [item["url"] for item in organic] == ["https://example.com/p"]
    assert [item["image_url"] for item in images] == ["https://example.com/p"]
    assert [item["url"] for item in news] == ["https://example.com/p"]


def test_whitespace_variant_collapses_onto_the_same_url_for_deduplication():
    cleaned = InfoQuestClient.clean_results(_envelope(organic=[{"url": "https://example.com/dup", "title": "A"}, {"url": "  https://example.com/dup  ", "title": "B"}]))

    assert [item["title"] for item in cleaned] == ["A"]


def test_one_hostile_row_does_not_sink_the_rest_of_the_payload():
    cleaned = InfoQuestClient.clean_results(_envelope(organic=[{"url": "http://127.0.0.1/x", "title": "Private"}, {"url": "https://example.com/y", "title": "Public"}]))

    assert [(item["type"], item["url"]) for item in cleaned] == [("page", "https://example.com/y")]


def test_rows_without_a_url_are_still_dropped():
    assert InfoQuestClient.clean_results(_envelope(organic=[{"title": "No url"}])) == []
    assert InfoQuestClient.clean_results(_envelope(top_stories={"items": [{"title": "No url news"}]})) == []
    assert InfoQuestClient.clean_results_with_image_search(_envelope(images_results=[{"title": "No original"}])) == []


def test_other_fields_survive_screening_of_the_url():
    cleaned = InfoQuestClient.clean_results(_envelope(organic=[{"url": PUBLIC_URL, "title": "Title", "desc": "Snippet"}]))

    assert cleaned[0]["title"] == "Title"
    assert cleaned[0]["snippet"] == "Snippet"


def test_web_search_output_never_carries_a_non_public_result_url():
    hostile = "http://169.254.169.254/latest/meta-data"
    payload = {"search_result": {"results": _envelope(organic=[{"url": hostile, "title": "Private"}, {"url": PUBLIC_URL, "title": "Public"}])}}
    client = InfoQuestClient()

    with patch.object(type(client), "web_search_raw_results", new=AsyncMock(return_value=payload)):
        output = asyncio.run(client.web_search("query"))

    assert json.loads(output) == [{"type": "page", "title": "Public", "url": PUBLIC_URL}]
    assert hostile not in output


def test_image_search_output_never_carries_a_non_public_result_url():
    hostile = "http://169.254.169.254/latest/meta-data"
    payload = {"search_result": {"results": _envelope(images_results=[{"original": hostile, "title": "Private"}, {"original": PUBLIC_URL, "title": "Public"}])}}
    client = InfoQuestClient()

    with patch.object(type(client), "image_search_raw_results", new=AsyncMock(return_value=payload)):
        output = asyncio.run(client.image_search("query"))

    assert json.loads(output) == [{"image_url": PUBLIC_URL, "title": "Public"}]
    assert hostile not in output


@pytest.mark.parametrize("method", ["web_search", "image_search"])
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"url": "http://169.254.169.254/latest/meta-data", "marker": "untrusted-provider-payload"},
        {"results": [{"url": PUBLIC_URL}, {"url": "http://127.0.0.1/admin"}]},
        {"unexpected": {"images_results": [{"original": "http://169.254.169.254/latest/meta-data"}]}},
    ],
)
def test_search_without_result_envelope_never_returns_raw_payload(method, payload):
    client = InfoQuestClient()
    with patch.object(type(client), f"{method}_raw_results", new=AsyncMock(return_value=payload)) as request:
        output = asyncio.run(getattr(client, method)("query"))

    assert output == "Error: InfoQuest returned an unexpected response format"
    assert "169.254.169.254" not in output
    assert "127.0.0.1" not in output
    assert "untrusted-provider-payload" not in output
    request.assert_awaited_once()
