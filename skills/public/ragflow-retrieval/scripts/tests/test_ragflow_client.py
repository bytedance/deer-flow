"""Unit tests for scripts/ragflow_client.py."""
import json
from pathlib import Path
from unittest import mock

import pytest
import requests

import ragflow_client as rc


@pytest.fixture
def ragflow_env(monkeypatch):
    monkeypatch.setenv("RAGFLOW_BASE_URL", "http://ragflow.lan:9380")
    monkeypatch.setenv("RAGFLOW_API_KEY", "ragflow-test-key")


def test_parse_retrieval_body_doc_aggs_list_format():
    resp = rc._parse_retrieval_body(
        {
            "code": 0,
            "data": {
                "chunks": [],
                "total": 1,
                "doc_aggs": [
                    {
                        "count": 1,
                        "doc_id": "5c5999ec7be811ef9cab0242ac120005",
                        "doc_name": "1.txt",
                    }
                ],
            },
        }
    )
    assert resp.doc_aggs == [
        {
            "count": 1,
            "doc_id": "5c5999ec7be811ef9cab0242ac120005",
            "doc_name": "1.txt",
        }
    ]


def test_parse_retrieval_body_doc_aggs_dict_format():
    resp = rc._parse_retrieval_body(
        {
            "code": 0,
            "data": {
                "chunks": [],
                "total": 2,
                "doc_aggs": {
                    "INSTALL.md": {
                        "doc_name": "INSTALL.md",
                        "doc_id": "4bd7fdd85e1511f0907f09f583941b45",
                        "count": 2,
                    }
                },
            },
        }
    )
    assert resp.doc_aggs["INSTALL.md"]["count"] == 2


def test_real_client_retrieve_happy(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": {
            "chunks": [{"id": "c1", "content": "hello", "similarity": 0.9}],
            "total": 1,
        },
    }
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "post", return_value=fake_response) as m_post:
        resp = rc.RealRAGFlowClient().retrieve(
            question="hello",
            dataset_ids=["kb-1"],
            metadata_condition={
                "logic": "and",
                "conditions": [{"name": "author", "comparison_operator": "=", "value": "A"}],
            },
        )

    assert resp.code == 0
    assert len(resp.chunks) == 1
    m_post.assert_called_once()
    args, kwargs = m_post.call_args
    assert args[0] == "http://ragflow.lan:9380/api/v1/retrieval"
    assert kwargs["json"]["metadata_condition"]["conditions"][0]["name"] == "author"
    assert kwargs["headers"]["Authorization"] == "Bearer ragflow-test-key"


def test_real_client_search_uses_single_dataset_route(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {"code": 0, "data": {"chunks": [], "total": 0}}
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "post", return_value=fake_response) as m_post:
        rc.RealRAGFlowClient().search(
            question="q",
            dataset_ids=["kb-1"],
            meta_data_filter={"method": "manual", "manual": [{"key": "author", "op": "=", "value": "A"}]},
        )

    args, _ = m_post.call_args
    assert args[0] == "http://ragflow.lan:9380/api/v1/datasets/kb-1/search"


def test_real_client_search_multi_dataset_route(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {"code": 0, "data": {"chunks": [], "total": 0}}
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "post", return_value=fake_response) as m_post:
        rc.RealRAGFlowClient().search(
            question="q",
            dataset_ids=["kb-1", "kb-2"],
        )

    args, _ = m_post.call_args
    assert args[0] == "http://ragflow.lan:9380/api/v1/datasets/search"


def test_real_client_raises_ragflow_error_on_business_failure(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {"code": 102, "message": "Dataset not found"}
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "post", return_value=fake_response):
        with pytest.raises(rc.RAGFlowError, match="Dataset not found"):
            rc.RealRAGFlowClient().retrieve(question="q", dataset_ids=["kb-1"])


def test_real_client_resolve_default_rerank_id(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": {
            "models": [
                {
                    "model_name": "BAAI/bge-reranker-v2-m3",
                    "model_provider": "Builtin",
                    "model_instance": "default",
                    "model_type": "rerank",
                    "enable": True,
                }
            ]
        },
    }
    fake_response.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "get", return_value=fake_response):
        client = rc.RealRAGFlowClient()
        assert client.resolve_default_rerank_id() == "BAAI/bge-reranker-v2-m3@Builtin"


def test_execute_run_rerank_fallback_on_http_500(ragflow_env):
    route = {
        "ok": True,
        "intent": "信贷",
        "label": "信贷知识库",
        "dataset_ids": ["kb-1"],
        "question": "贷款利率",
        "rerank_id": "bad-rerank-model@Builtin",
        "recall_top_k": 64,
        "page_size": 10,
        "filters": {"filter_enabled": False, "mode": "search"},
    }
    fail_resp = mock.Mock()
    fail_resp.status_code = 500
    fail_resp.text = "Internal server error"
    fail_resp.json.return_value = {"message": "Internal server error"}
    fail_resp.raise_for_status.side_effect = requests.HTTPError(
        "500 Server Error",
        response=fail_resp,
    )
    ok_resp = mock.Mock()
    ok_resp.json.return_value = {
        "code": 0,
        "data": {"chunks": [{"id": "c1", "content": "x", "similarity": 0.9}], "total": 1},
    }
    ok_resp.raise_for_status = mock.Mock()

    # retrieve() retries HTTP errors up to 3 times before propagating.
    with mock.patch.object(
        rc.requests,
        "post",
        side_effect=[fail_resp, fail_resp, fail_resp, ok_resp],
    ):
        payload = rc.execute_run(route, client=rc.RealRAGFlowClient())
    assert payload["code"] == 0
    assert payload["route"]["rerank_fallback"] is True


def test_resolve_runtime_rerank_id_expands_two_part_id(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": {
            "models": [
                {
                    "model_name": "bge-rerank-large",
                    "model_provider": "HugginFace",
                    "model_instance": "bge-rerank-large",
                    "model_type": "rerank",
                    "enable": True,
                }
            ]
        },
    }
    fake_response.raise_for_status = mock.Mock()
    client = rc.RealRAGFlowClient()
    with mock.patch.object(rc.requests, "get", return_value=fake_response):
        resolved = rc._resolve_runtime_rerank_id(client, "bge-rerank-large@HugginFace")
    assert resolved == "bge-rerank-large@bge-rerank-large@HugginFace"


def test_resolve_runtime_rerank_id_expands_bare_model_name(ragflow_env):
    fake_response = mock.Mock()
    fake_response.json.return_value = {
        "code": 0,
        "data": {
            "models": [
                {
                    "model_name": "BAAI/bge-reranker-v2-m3",
                    "model_provider": "Builtin",
                    "model_instance": "default",
                    "model_type": "rerank",
                    "enable": True,
                }
            ]
        },
    }
    fake_response.raise_for_status = mock.Mock()
    client = rc.RealRAGFlowClient()
    with mock.patch.object(rc.requests, "get", return_value=fake_response):
        resolved = rc._resolve_runtime_rerank_id(client, "BAAI/bge-reranker-v2-m3")
    assert resolved == "BAAI/bge-reranker-v2-m3@Builtin"


def test_execute_run_rerank_fallback(ragflow_env):
    route = {
        "ok": True,
        "intent": "信贷",
        "label": "信贷知识库",
        "dataset_ids": ["kb-1"],
        "question": "贷款利率",
        "rerank_id": "bad-rerank-model@Builtin",
        "recall_top_k": 64,
        "page_size": 10,
        "filters": {"filter_enabled": False, "mode": "search"},
    }
    fail_resp = mock.Mock()
    fail_resp.json.return_value = {
        "code": 102,
        "message": "Provider  not found for model bad-rerank-model@Builtin.",
    }
    fail_resp.raise_for_status = mock.Mock()
    ok_resp = mock.Mock()
    ok_resp.json.return_value = {
        "code": 0,
        "data": {"chunks": [{"id": "c1", "content": "x", "similarity": 0.9}], "total": 1},
    }
    ok_resp.raise_for_status = mock.Mock()

    with mock.patch.object(rc.requests, "post", side_effect=[fail_resp, ok_resp]):
        payload = rc.execute_run(route, client=rc.RealRAGFlowClient())
    assert payload["code"] == 0
    assert payload["route"]["rerank_fallback"] is True
    assert payload["route"]["rerank_id"] is None


def test_mock_client_filters_by_metadata_condition():
    fixture = Path(__file__).resolve().parents[2] / "example" / "mock_retrieval" / "chunks.json"
    client = rc.MockRAGFlowClient(str(fixture))
    resp = client.retrieve(
        question="q",
        dataset_ids=["kb-demo-001"],
        metadata_condition={
            "logic": "and",
            "conditions": [{"name": "author", "comparison_operator": "=", "value": "InfiniFlow"}],
        },
    )
    assert len(resp.chunks) == 1
    assert resp.chunks[0]["id"] == "chunk-001"


def test_cli_retrieve_mock(tmp_path):
    out = tmp_path / "out.json"
    rc.main(
        [
            "retrieve",
            "--mock",
            "--question",
            "metadata",
            "--dataset-ids",
            "kb-demo-001",
            "--metadata-condition",
            str(Path(__file__).resolve().parents[2] / "example" / "metadata_condition.author.json"),
            "--out",
            str(out),
        ]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["code"] == 0
    assert len(payload["data"]["chunks"]) == 1


def test_cli_run_from_route_mock(tmp_path):
    route_path = tmp_path / "route.json"
    out = tmp_path / "out.json"
    route_path.write_text(
        json.dumps(
            {
                "ok": True,
                "intent": "信贷",
                "label": "信贷知识库",
                "dataset_ids": ["kb-demo-001"],
                "question": "贷款利率",
                "filters": {
                    "mode": "retrieve",
                    "filter_enabled": True,
                    "active_filter_type": "metadata_condition",
                    "active_filter": {
                        "logic": "and",
                        "conditions": [
                            {
                                "name": "author",
                                "comparison_operator": "=",
                                "value": "InfiniFlow",
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    rc.main(
        [
            "run",
            "--mock",
            "--route",
            str(route_path),
            "--question",
            "metadata filtering",
            "--out",
            str(out),
        ]
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["code"] == 0
    assert payload["route"]["intent"] == "信贷"
    assert len(payload["data"]["chunks"]) >= 1
    assert len(payload["citations"]) >= 1
    citations_md = tmp_path / "out.citations.md"
    assert citations_md.exists()


def test_build_run_summary():
    payload = {
        "code": 0,
        "data": {"total": 2, "chunks": []},
        "citations": [{"ref": 1, "document_name": "a.pdf", "content": "x", "similarity": 0.9}],
        "route": {
            "intent": "信贷",
            "label": "信贷知识库",
            "filters": {
                "department_selection": {
                    "selected_departments": [{"id": "零售", "label": "零售金融部"}],
                }
            },
        },
    }
    summary = rc.build_run_summary(payload)
    assert summary["intent"] == "信贷"
    assert summary["departments"] == ["零售金融部"]
    assert summary["citation_count"] == 1
