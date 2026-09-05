from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException

from app.gateway.routers import ad_links


def test_validate_target_url_rejects_non_http():
    with pytest.raises(HTTPException, match="absolute HTTP"):
        ad_links._validate_target_url("javascript:alert(1)")


def test_extract_deep_link_reads_api_response():
    payload = {"data": [{"deeplink_url": "https://vbtrax.com/track"}]}
    assert ad_links._extract_deep_link(payload) == "https://vbtrax.com/track"


def test_extract_deep_link_rejects_empty_response():
    assert ad_links._extract_deep_link({"data": []}) is None


@pytest.mark.asyncio
async def test_generate_deep_link_forwards_key_and_payload(monkeypatch):
    monkeypatch.setenv("AFFILIATES_ONE_API_KEY", "test-key")
    response = httpx.Response(
        200,
        json={"data": [{"deeplink_url": "https://vbtrax.com/track"}]},
        request=httpx.Request("POST", ad_links.AFFILIATES_ONE_DEEP_LINK_URL),
    )
    post = AsyncMock(return_value=response)
    entered_client = SimpleNamespace(post=post)
    class FakeClient:
        async def __aenter__(self):
            return entered_client

        async def __aexit__(self, *_args):
            return None

    client = FakeClient()
    body = ad_links.DeepLinkRequest(target_url="https://shop.example/item", aff_uniq_id="creator")

    with patch.object(ad_links.httpx, "AsyncClient", return_value=client):
        result = await ad_links.generate_deep_link.__wrapped__(body, request=SimpleNamespace())

    assert result.deeplink_url == "https://vbtrax.com/track"
    sent = post.await_args.kwargs["json"]
    assert sent["meta"]["api_key"] == "test-key"
    assert sent["data"]["target_url"] == "https://shop.example/item"
