from __future__ import annotations

import asyncio

import httpx
import pytest

from deerflow.models.openai_response import GuardedChatOpenAI
from deerflow.models.response_errors import EmptyModelResponseError


def test_http_200_with_empty_choices_raises_retryable_response_error():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={
                "id": "chatcmpl-empty",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [],
            },
        )
    )
    http_client = httpx.Client(transport=transport, trust_env=False)
    http_async_client = httpx.AsyncClient(transport=transport, trust_env=False)
    model = GuardedChatOpenAI(
        model="test-model",
        api_key="sk-test",
        base_url="https://provider.invalid/v1",
        max_retries=0,
        http_client=http_client,
        http_async_client=http_async_client,
    )

    try:
        with pytest.raises(EmptyModelResponseError, match="empty choices"):
            model.invoke("hello")
    finally:
        http_client.close()
        asyncio.run(http_async_client.aclose())
