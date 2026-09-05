import json

import httpx
import pytest

from deerflow.community.lightrag.client import (
    LightRAGAPIError,
    LightRAGClient,
    LightRAGConnectionError,
    LightRAGProtocolError,
)


@pytest.mark.anyio
async def test_query_data_sends_documented_body_and_api_key_header() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "POST"
        assert request.url == httpx.URL("http://lightrag.test/query/data")
        assert request.headers["X-API-Key"] == "lightrag-secret"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "message": None,
                "data": {"chunks": [], "references": [], "entities": [], "relationships": []},
            },
        )

    client = LightRAGClient(
        base_url="http://lightrag.test/",
        api_key="lightrag-secret",
        timeout=12,
        transport=httpx.MockTransport(handler),
    )

    data = await client.query_data("annual leave", mode="hybrid", top_k=60)

    assert data == {"chunks": [], "references": [], "entities": [], "relationships": []}
    assert len(requests) == 1
    assert json.loads(requests[0].content) == {"query": "annual leave", "mode": "hybrid", "top_k": 60}


@pytest.mark.anyio
async def test_query_data_omits_api_key_header_when_unauthenticated() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert "Authorization" not in request.headers
        assert "X-API-Key" not in request.headers
        return httpx.Response(200, json={"status": "success", "data": {"chunks": []}})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key=None,
        transport=httpx.MockTransport(handler),
    )

    await client.query_data("annual leave")

    assert len(requests) == 1


@pytest.mark.anyio
async def test_query_data_sends_chunk_top_k_only_when_configured() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "success", "data": {"chunks": []}})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    await client.query_data("annual leave", mode="mix", top_k=15, chunk_top_k=8)
    await client.query_data("annual leave", mode="mix", top_k=15)

    assert json.loads(requests[0].content) == {"query": "annual leave", "mode": "mix", "top_k": 15, "chunk_top_k": 8}
    assert json.loads(requests[1].content) == {"query": "annual leave", "mode": "mix", "top_k": 15}


@pytest.mark.anyio
async def test_query_data_rejects_unknown_mode_before_request() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="mode must be one of"):
        await client.query_data("fallback search", mode="vector")

    assert called is False


@pytest.mark.anyio
async def test_non_success_envelope_is_normalized_and_redacts_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "failure", "message": "invalid credential lightrag-secret"},
        )

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError) as exc_info:
        await client.query_data("annual leave")

    assert "invalid credential" in str(exc_info.value)
    assert "lightrag-secret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.anyio
async def test_http_error_envelope_message_is_used() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"status": "failure", "message": "RAG query is too short"},
        )

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError, match="RAG query is too short"):
        await client.query_data("ab")


@pytest.mark.anyio
async def test_http_error_detail_string_is_used() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Invalid API key provided"})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError, match="Invalid API key provided"):
        await client.query_data("annual leave")


@pytest.mark.anyio
async def test_structured_validation_error_message_is_extracted_from_detail() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "detail": [
                    {
                        "type": "value_error",
                        "loc": ["body", "query"],
                        "msg": "Value error, RAG query is too short. Enter at least 3 English characters or an equivalent combination where each Chinese, Japanese or Korean character counts as 2.",
                    }
                ]
            },
        )

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError) as exc_info:
        await client.query_data("ab")

    assert "RAG query is too short" in str(exc_info.value)
    assert "Value error," not in str(exc_info.value)


@pytest.mark.anyio
async def test_structured_validation_error_without_readable_msg_falls_back_to_protocol_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"type": "missing", "loc": ["body"]}]})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGProtocolError, match=r"LightRAG request failed \(HTTP 422\)"):
        await client.query_data("annual leave")


@pytest.mark.anyio
@pytest.mark.parametrize("body", [None, '{"detail": "Not Found"}'])
async def test_404_returns_upgrade_guidance_instead_of_plain_not_found(body: str | None) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text=body, headers={"Content-Type": "application/json"} if body else None)

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError, match="v1.4.8"):
        await client.query_data("annual leave")


@pytest.mark.anyio
async def test_http_error_text_body_cannot_echo_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error: lightrag-secret")

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGProtocolError) as exc_info:
        await client.query_data("annual leave")

    assert str(exc_info.value) == "LightRAG request failed (HTTP 500)."
    assert "lightrag-secret" not in str(exc_info.value)


@pytest.mark.anyio
async def test_server_500_detail_string_is_used_verbatim() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "Internal server error"})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGAPIError, match="^Internal server error$"):
        await client.query_data("annual leave")


@pytest.mark.anyio
async def test_timeout_is_english_and_does_not_leak_api_key(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with lightrag-secret", request=request)

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        timeout=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGConnectionError) as exc_info:
        await client.query_data("annual leave")

    assert str(exc_info.value) == "LightRAG request timed out after 2 seconds."
    assert "lightrag-secret" not in str(exc_info.value)
    assert "lightrag-secret" not in caplog.text


@pytest.mark.anyio
async def test_request_error_is_normalized_and_redacts_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused with lightrag-secret", request=request)

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGConnectionError) as exc_info:
        await client.query_data("annual leave")

    assert "ConnectError" in str(exc_info.value)
    assert "lightrag-secret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.anyio
async def test_invalid_json_response_is_normalized_in_english() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGProtocolError, match="LightRAG returned invalid JSON"):
        await client.query_data("annual leave")


@pytest.mark.anyio
async def test_non_object_json_payload_is_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "an", "object"])

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGProtocolError, match="non-object JSON payload"):
        await client.query_data("annual leave")


@pytest.mark.anyio
async def test_non_dict_data_payload_is_rejected() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "data": ["not-a-dict"]})

    client = LightRAGClient(
        base_url="http://lightrag.test",
        api_key="lightrag-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(LightRAGProtocolError, match="invalid retrieval result"):
        await client.query_data("annual leave")
