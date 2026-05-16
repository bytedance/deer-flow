"""Unit tests for FAQ service — mock RAGFlow responses."""

import pytest

from deerflow.faq import FaqItem, FaqQuery, FaqResult, FaqService

pytestmark = pytest.mark.anyio


def _make_query(**overrides) -> FaqQuery:
    defaults = {
        "question": "如何重置密码",
        "dataset_ids": ["faq_ds_001"],
    }
    defaults.update(overrides)
    return FaqQuery(**defaults)


def _ragflow_chunk(score: float, content: str = "答案内容", doc_id: str = "doc1") -> dict:
    return {
        "content": content,
        "similarity": score,
        "document_keyword": "常见问题",
        "document_id": doc_id,
    }


def _ragflow_response(chunks: list[dict], code: int = 0) -> dict:
    return {"code": code, "data": {"chunks": chunks}}


# ── FaqQuery / FaqResult / FaqItem basic tests ─────────────────────────────


class TestFaqTypes:
    def test_faq_query_defaults(self):
        q = FaqQuery(question="test", dataset_ids=["ds1"])
        assert q.context is None
        assert q.top_k == 3
        assert q.metadata is None
        assert q.doc_ids is None
        assert q.page == 1
        assert q.size == 5
        assert q.use_kg is False
        assert q.cross_languages == []
        assert q.keyword is False
        assert q.search_id is None

    def test_faq_item(self):
        item = FaqItem(question="q", answer="a", score=0.9, faq_id="id1")
        assert item.score == 0.9

    def test_faq_result_defaults(self):
        r = FaqResult(user_question="q")
        assert r.best_faq is None
        assert r.all_matches == []
        assert r.match_level == "none"
        assert r.route_decision == "rag_only"
        assert r.should_call_rag is True
        assert r.metadata == {}


# ── Search result building ──────────────────────────────────────────────────


class TestSearchResultBuilding:
    """Verify search results are returned and sorted regardless of score."""

    def test_high_score_result(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.92)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is not None
        assert result.best_faq.score == 0.92
        assert len(result.all_matches) == 1
        assert result.match_level == "high"
        assert result.route_decision == "faq_only"
        assert result.should_call_rag is False

    def test_medium_score_result(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.72)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is not None
        assert result.best_faq.score == 0.72
        assert result.match_level == "medium"
        assert result.route_decision == "faq_plus_rag"
        assert result.should_call_rag is True

    def test_low_score_result(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.3)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is not None
        assert result.best_faq.score == 0.3
        assert result.match_level == "low"
        assert result.route_decision == "rag_only"
        assert result.should_call_rag is True

    def test_empty_chunks(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is None
        assert result.all_matches == []
        assert result.match_level == "none"
        assert result.route_decision == "rag_only"
        assert result.should_call_rag is True

    def test_custom_thresholds(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key", high_threshold=0.9, medium_threshold=0.75)

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.82)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.match_level == "medium"
        assert result.route_decision == "faq_plus_rag"
        assert result.metadata["high_threshold"] == 0.9
        assert result.metadata["medium_threshold"] == 0.75


# ── Error degradation ───────────────────────────────────────────────────────


class TestErrorDegradation:
    """Errors degrade to best_faq=None with error metadata."""

    def test_connection_error(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is None
        assert result.all_matches == []
        assert result.metadata.get("error") is True
        assert result.match_level == "error"
        assert result.route_decision == "rag_only"
        assert result.should_call_rag is True

    def test_http_error(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(500, text="Internal Server Error")
            resp._request = httpx.Request("POST", "http://fake" + url)
            raise httpx.HTTPStatusError("500", request=resp._request, response=resp)

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is None
        assert result.all_matches == []

    def test_ragflow_code_error(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(200, json={"code": 1, "message": "invalid dataset"})
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert result.best_faq is None
        assert result.metadata.get("error") is True


# ── Context injection ───────────────────────────────────────────────────────


class TestContextInjection:
    def test_context_prepended_to_question(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.9)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(context="登录相关"))

        assert captured["question"] == "登录相关 如何重置密码"


# ── Multiple results sorting ────────────────────────────────────────────────


class TestMultipleResults:
    def test_results_sorted_by_score_desc(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        chunks = [
            _ragflow_chunk(0.5, "低分答案", "doc1"),
            _ragflow_chunk(0.9, "高分答案", "doc2"),
            _ragflow_chunk(0.7, "中分答案", "doc3"),
        ]

        def mock_post(self_client, url, json=None):
            resp = httpx.Response(200, json=_ragflow_response(chunks))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        result = service.search(_make_query())

        assert len(result.all_matches) == 3
        assert result.all_matches[0].score == 0.9
        assert result.all_matches[1].score == 0.7
        assert result.all_matches[2].score == 0.5
        assert result.best_faq.score == 0.9


# ── Payload construction ────────────────────────────────────────────────────


class TestPayloadConstruction:
    def test_default_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query())

        assert captured["question"] == "如何重置密码"
        assert captured["dataset_ids"] == ["faq_ds_001"]
        assert captured["top_k"] == 3
        assert captured["page"] == 1
        assert captured["size"] == 5

    def test_doc_ids_in_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(doc_ids=["doc_a", "doc_b"]))

        assert captured["doc_ids"] == ["doc_a", "doc_b"]

    def test_use_kg_in_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(use_kg=True))

        assert captured["use_kg"] is True

    def test_keyword_in_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(keyword=True))

        assert captured["keyword"] is True

    def test_cross_languages_in_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(cross_languages=["en", "ja"]))

        assert captured["cross_languages"] == ["en", "ja"]

    def test_rerank_id_from_service(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key", rerank_id="rerank_model_1")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query())

        assert captured["rerank_id"] == "rerank_model_1"

    def test_search_id_in_payload(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query(search_id="search_model_1"))

        assert captured["search_id"] == "search_model_1"

    def test_optional_fields_omitted_when_default(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query())

        assert "doc_ids" not in captured
        assert "use_kg" not in captured
        assert "keyword" not in captured
        assert "cross_languages" not in captured
        assert "search_id" not in captured
        assert "rerank_id" not in captured
        assert "tenant_rerank_id" not in captured

    def test_vector_similarity_weight_default(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")
        captured: dict = {}

        def mock_post(self_client, url, json=None):
            captured.update(json or {})
            resp = httpx.Response(200, json=_ragflow_response([]))
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        service.search(_make_query())

        assert captured["vector_similarity_weight"] == 1.0


# ── Async tests ─────────────────────────────────────────────────────────────


class TestAsyncSearch:
    async def test_async_high_match(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        async def mock_post(self_client, url, json=None):
            resp = httpx.Response(
                200,
                json=_ragflow_response([_ragflow_chunk(0.88)]),
            )
            resp._request = httpx.Request("POST", "http://fake" + url)
            return resp

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await service.asearch(_make_query())

        assert result.best_faq is not None
        assert result.best_faq.score == 0.88

    async def test_async_error_degradation(self, monkeypatch):
        import httpx

        service = FaqService(base_url="http://fake", api_key="key")

        async def mock_post(self_client, url, json=None):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
        result = await service.asearch(_make_query())

        assert result.best_faq is None
        assert result.metadata.get("error") is True
