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
async def test_list_datasets_filters_by_bound_id_in_one_request() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url == httpx.URL("http://ragflow.test/api/v1/datasets?ids=dataset-1")
        assert request.headers["Authorization"] == "Bearer ragflow-secret"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": [{"id": "dataset-1", "name": "HR Policies"}],
                "total": 1,
            },
        )

    client = RAGFlowClient(
        base_url="http://ragflow.test/",
        api_key="ragflow-secret",
        timeout=12,
        transport=httpx.MockTransport(handler),
    )

    assert await client.list_datasets(dataset_id="dataset-1") == [{"id": "dataset-1", "name": "HR Policies"}]
    assert len(requests) == 1


@pytest.mark.anyio
async def test_list_datasets_without_id_fetches_every_page() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        assert request.url.params["page_size"] == "100"
        if page == 1:
            data = [{"id": f"dataset-{index}", "name": f"Dataset {index}"} for index in range(100)]
        elif page == 2:
            data = [{"id": "dataset-100", "name": "Dataset 100"}]
        else:
            pytest.fail(f"unexpected page {page}")
        return httpx.Response(200, json={"code": 0, "data": data, "total": 101})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    datasets = await client.list_datasets()

    assert len(datasets) == 101
    assert [request.url.params["page"] for request in requests] == ["1", "2"]


@pytest.mark.anyio
async def test_list_datasets_without_id_has_a_hard_page_cap() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data = [{"id": f"dataset-{index}", "name": f"Dataset {index}"} for index in range(100)]
        return httpx.Response(200, json={"code": 0, "data": data})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError, match="exceeded 100 pages"):
        await client.list_datasets()

    assert len(requests) == 100


@pytest.mark.anyio
async def test_list_datasets_accepts_reported_total_at_the_page_cap() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        page = int(request.url.params["page"])
        start = (page - 1) * 100
        data = [{"id": f"dataset-{index}", "name": f"Dataset {index}"} for index in range(start, start + 100)]
        return httpx.Response(200, json={"code": 0, "data": data, "total": 10_000})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    datasets = await client.list_datasets()

    assert len(datasets) == 10_000
    assert len(requests) == 100


@pytest.mark.anyio
async def test_retrieve_always_sends_nonempty_dataset_ids() -> None:
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
async def test_retrieve_rejects_empty_dataset_ids_before_request() -> None:
    called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValueError, match="dataset_ids must contain at least one dataset ID"):
        await client.retrieve("fallback search", dataset_ids=[])

    assert called is False


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
        await client.list_datasets(dataset_id="dataset-1")

    assert exc_info.value.code == 102
    assert "invalid credential" in str(exc_info.value)
    assert "ragflow-secret" not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.anyio
async def test_timeout_is_english_and_does_not_leak_api_key(caplog: pytest.LogCaptureFixture) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out with ragflow-secret", request=request)

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        timeout=2,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowConnectionError) as exc_info:
        await client.list_datasets(dataset_id="dataset-1")

    assert str(exc_info.value) == "RAGFlow request timed out after 2 seconds."
    assert "ragflow-secret" not in str(exc_info.value)
    assert "ragflow-secret" not in caplog.text


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
        await client.list_datasets(dataset_id="dataset-1")

    assert str(exc_info.value) == "RAGFlow request failed (HTTP 401)."
    assert "ragflow-secret" not in str(exc_info.value)


@pytest.mark.anyio
async def test_invalid_json_response_is_normalized_in_english() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not-json")

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError, match="RAGFlow returned invalid JSON"):
        await client.list_datasets(dataset_id="dataset-1")


@pytest.mark.anyio
async def test_list_datasets_rejects_unexpected_data_shape_in_english() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 0, "data": {"id": "not-a-list"}})

    client = RAGFlowClient(
        base_url="http://ragflow.test",
        api_key="ragflow-secret",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(RAGFlowProtocolError, match="invalid dataset list"):
        await client.list_datasets(dataset_id="dataset-1")
