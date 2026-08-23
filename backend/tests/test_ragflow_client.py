import json

import httpx
import pytest

from deerflow.community.ragflow.client import (
    RAGFlowAPIError,
    RAGFlowClient,
    RAGFlowConnectionError,
    RAGFlowProtocolError,
)


@pytest.mark.anyio
async def test_list_datasets_builds_authenticated_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL("http://ragflow.test/api/v1/datasets?page=1&page_size=100")
        assert request.headers["Authorization"] == "Bearer ragflow-secret"
        return httpx.Response(200, json={"code": 0, "data": [{"id": "dataset-1", "name": "Policies"}]})

    client = RAGFlowClient(
        base_url="http://ragflow.test/",
        api_key="ragflow-secret",
        timeout=12,
        transport=httpx.MockTransport(handler),
    )

    assert await client.list_datasets() == [{"id": "dataset-1", "name": "Policies"}]


@pytest.mark.anyio
async def test_list_datasets_follows_pagination_until_total_is_reached() -> None:
    requested_pages: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        requested_pages.append(page)
        if page == 1:
            data = [{"id": f"dataset-{index}", "name": f"Dataset {index}"} for index in range(100)]
        else:
            data = [{"id": "dataset-100", "name": "Dataset 100"}]
        return httpx.Response(200, json={"code": 0, "data": data, "total_datasets": 101})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    datasets = await client.list_datasets()

    assert requested_pages == [1, 2]
    assert len(datasets) == 101


@pytest.mark.anyio
async def test_retrieve_builds_expected_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL("http://ragflow.test/api/v1/retrieval")
        assert json.loads(request.content) == {
            "question": "annual leave",
            "dataset_ids": ["dataset-1"],
            "page_size": 8,
            "similarity_threshold": 0.2,
            "vector_similarity_weight": 0.3,
            "top_k": 256,
        }
        return httpx.Response(200, json={"code": 0, "data": {"chunks": [], "doc_aggs": [], "total": 0}})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    result = await client.retrieve(
        "annual leave",
        dataset_ids=["dataset-1"],
        page_size=8,
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        top_k=256,
    )

    assert result["total"] == 0


@pytest.mark.anyio
async def test_retrieve_omits_dataset_ids_when_unspecified() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert "dataset_ids" not in payload
        return httpx.Response(200, json={"code": 0, "data": {"chunks": []}})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    await client.retrieve("fallback search", dataset_ids=None)


@pytest.mark.anyio
async def test_nonzero_api_code_is_normalized_and_redacts_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 102, "message": "invalid credential ragflow-secret"},
        )

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowAPIError) as exc_info:
        await client.list_datasets()

    assert exc_info.value.code == 102
    assert "invalid credential" in str(exc_info.value)
    assert "ragflow-secret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.anyio
async def test_timeout_is_normalized_without_leaking_api_key(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with ragflow-secret", request=request)

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        timeout=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowConnectionError) as exc_info:
        await client.list_datasets()

    assert "ragflow-secret" not in str(exc_info.value)
    assert "ragflow-secret" not in caplog.text
    assert "超时" in str(exc_info.value)


@pytest.mark.anyio
async def test_http_error_body_cannot_echo_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized: ragflow-secret")

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError) as exc_info:
        await client.list_datasets()

    assert "HTTP 401" in str(exc_info.value)
    assert "ragflow-secret" not in str(exc_info.value)


@pytest.mark.anyio
async def test_invalid_json_response_is_normalized() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError, match="JSON"):
        await client.list_datasets()


@pytest.mark.anyio
async def test_list_datasets_rejects_unexpected_data_shape() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"id": "not-a-list"}})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError, match="知识库列表"):
        await client.list_datasets()
