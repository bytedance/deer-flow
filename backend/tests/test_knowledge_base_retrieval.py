"""Tests for multi-KB retrieval pipeline (prompt formatting, fan-out retrieval, middleware)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.rag.prompt import format_multi_kb_context
from deerflow.rag.vector_store import SearchResult


class TestFormatMultiKbContext:
    def test_empty_results(self):
        assert format_multi_kb_context([]) == ""

    def test_single_result(self):
        results = [
            SearchResult(
                chunk_id="c1",
                content="Hello world",
                metadata={"knowledge_base_id": "kb-1", "kb_name": "My KB", "title": "Doc 1"},
                score=0.95,
            )
        ]
        output = format_multi_kb_context(results)
        assert "<knowledge_base_context>" in output
        assert "</knowledge_base_context>" in output
        assert 'kb_id="kb-1"' in output
        assert 'kb_name="My KB"' in output
        assert 'doc_title="Doc 1"' in output
        assert 'score="0.95"' in output
        assert "Hello world" in output

    def test_multiple_results(self):
        results = [
            SearchResult(chunk_id="c1", content="First", metadata={"knowledge_base_id": "kb-1", "kb_name": "KB1", "title": "D1"}, score=0.9),
            SearchResult(chunk_id="c2", content="Second", metadata={"knowledge_base_id": "kb-2", "kb_name": "KB2", "title": "D2"}, score=0.8),
        ]
        output = format_multi_kb_context(results)
        assert "First" in output
        assert "Second" in output
        assert output.index("First") < output.index("Second")

    def test_truncation_by_max_tokens(self):
        results = [
            SearchResult(chunk_id=f"c{i}", content="x" * 200, metadata={"knowledge_base_id": "kb-1", "kb_name": "KB", "title": "D"}, score=0.9 - i * 0.01)
            for i in range(50)
        ]
        output = format_multi_kb_context(results, max_tokens=100)
        assert "<knowledge_base_context>" in output
        assert output.count("<source") < 50

    def test_xml_escaping(self):
        results = [
            SearchResult(
                chunk_id="c1",
                content='<script>alert("xss")</script>',
                metadata={"knowledge_base_id": "kb&1", "kb_name": 'KB "test"', "title": "Doc<1>"},
                score=0.9,
            )
        ]
        output = format_multi_kb_context(results)
        assert "&lt;script&gt;" in output
        assert "kb&amp;1" in output
        assert "&lt;1&gt;" in output


class TestMultiKbRetrieve:
    def test_empty_knowledge_bases(self):
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve

        results = multi_kb_retrieve([], query="test", top_k=5)
        assert results == []

    @patch("deerflow.knowledge_base.retrieval.DocumentRetriever")
    def test_single_kb(self, mock_retriever_cls):
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve
        from deerflow.rag.retrieval import RetrievalResult

        mock_retriever = MagicMock()
        mock_retriever_cls.return_value = mock_retriever
        mock_retriever.retrieve.return_value = RetrievalResult(
            query="test",
            results=[
                SearchResult(chunk_id="c1", content="result 1", metadata={}, score=0.9),
                SearchResult(chunk_id="c2", content="result 2", metadata={}, score=0.8),
            ],
            collection="kb_abc",
        )

        kbs = [{"id": "kb-1", "collection_name": "kb_abc", "name": "Test KB"}]
        results = multi_kb_retrieve(kbs, query="test", top_k=5)

        assert len(results) == 2
        assert results[0].score >= results[1].score
        assert results[0].metadata["kb_name"] == "Test KB"
        assert results[0].metadata["knowledge_base_id"] == "kb-1"

    @patch("deerflow.knowledge_base.retrieval.DocumentRetriever")
    def test_multi_kb_merge_and_sort(self, mock_retriever_cls):
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve
        from deerflow.rag.retrieval import RetrievalResult

        mock_retriever = MagicMock()
        mock_retriever_cls.return_value = mock_retriever

        def side_effect(query, collection, top_k):
            if collection == "col_a":
                return RetrievalResult(query=query, results=[
                    SearchResult(chunk_id="a1", content="from A high", metadata={}, score=0.95),
                    SearchResult(chunk_id="a2", content="from A low", metadata={}, score=0.5),
                ], collection=collection)
            return RetrievalResult(query=query, results=[
                SearchResult(chunk_id="b1", content="from B high", metadata={}, score=0.97),
                SearchResult(chunk_id="b2", content="from B low", metadata={}, score=0.3),
            ], collection=collection)

        mock_retriever.retrieve.side_effect = side_effect

        kbs = [
            {"id": "kb-a", "collection_name": "col_a", "name": "KB A"},
            {"id": "kb-b", "collection_name": "col_b", "name": "KB B"},
        ]
        results = multi_kb_retrieve(kbs, query="test", top_k=10)

        assert len(results) == 4
        assert results[0].score == results[1].score == 1.0
        assert results[0].metadata["kb_name"] in ("KB A", "KB B")

    @patch("deerflow.knowledge_base.retrieval.DocumentRetriever")
    def test_deduplication(self, mock_retriever_cls):
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve
        from deerflow.rag.retrieval import RetrievalResult

        mock_retriever = MagicMock()
        mock_retriever_cls.return_value = mock_retriever

        mock_retriever.retrieve.return_value = RetrievalResult(
            query="test",
            results=[
                SearchResult(chunk_id="c1", content="duplicate content", metadata={}, score=0.9),
            ],
            collection="col",
        )

        kbs = [
            {"id": "kb-1", "collection_name": "col", "name": "KB1"},
            {"id": "kb-2", "collection_name": "col", "name": "KB2"},
        ]
        results = multi_kb_retrieve(kbs, query="test", top_k=10)

        assert len(results) == 1

    @patch("deerflow.knowledge_base.retrieval.DocumentRetriever")
    def test_top_k_limit(self, mock_retriever_cls):
        from deerflow.knowledge_base.retrieval import multi_kb_retrieve
        from deerflow.rag.retrieval import RetrievalResult

        mock_retriever = MagicMock()
        mock_retriever_cls.return_value = mock_retriever
        mock_retriever.retrieve.return_value = RetrievalResult(
            query="test",
            results=[
                SearchResult(chunk_id=f"c{i}", content=f"content {i}", metadata={}, score=0.9 - i * 0.01)
                for i in range(10)
            ],
            collection="col",
        )

        kbs = [{"id": "kb-1", "collection_name": "col", "name": "KB"}]
        results = multi_kb_retrieve(kbs, query="test", top_k=3)

        assert len(results) == 3


class TestResolveActiveByIds:
    @pytest.mark.asyncio
    async def test_resolve_active_by_ids(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        repo = KnowledgeBaseRepository(sf)
        kb1 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB1")
        kb2 = await repo.create(tenant_id="t1", owner_user_id="u1", name="KB2")
        kb3 = await repo.create(tenant_id="t1", owner_user_id="u2", name="KB3")

        results = await repo.resolve_active_by_ids(
            [kb1["id"], kb2["id"], kb3["id"]],
            tenant_id="t1",
            owner_user_id="u1",
        )
        assert len(results) == 2
        ids = {r["id"] for r in results}
        assert kb1["id"] in ids
        assert kb2["id"] in ids
        assert kb3["id"] not in ids

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_resolve_empty_list(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        repo = KnowledgeBaseRepository(sf)
        results = await repo.resolve_active_by_ids([], tenant_id="t1", owner_user_id="u1")
        assert results == []

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_resolve_excludes_deleted(self):
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from deerflow.persistence.base import Base
        from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        repo = KnowledgeBaseRepository(sf)
        kb = await repo.create(tenant_id="t1", owner_user_id="u1", name="ToDelete")
        await repo.soft_delete(kb["id"], tenant_id="t1", owner_user_id="u1")

        results = await repo.resolve_active_by_ids([kb["id"]], tenant_id="t1", owner_user_id="u1")
        assert results == []

        await engine.dispose()


class TestResolveRuntimeKbSelection:
    @pytest.mark.asyncio
    async def test_uses_runtime_config_thread_id_fallback(self):
        from deerflow.knowledge_base.retrieval import resolve_runtime_kb_selection

        runtime = MagicMock()
        runtime.context = {"user_id": "u1"}
        runtime.config = {"configurable": {"thread_id": "thread-1"}}
        runtime.store = MagicMock()

        with patch("deerflow.knowledge_base.retrieval.get_session_factory") as mock_sf, patch(
            "deerflow.knowledge_base.retrieval.make_thread_store"
        ) as mock_make_store:
            mock_sf.return_value = None
            mock_store = MagicMock()
            mock_store.get = AsyncMock(
                return_value={
                    "metadata": {
                        "knowledge_base_selection": {"enabled": True, "selected_ids": ["kb-1"]}
                    }
                }
            )
            mock_make_store.return_value = mock_store

            selection, source = await resolve_runtime_kb_selection(runtime)

            assert selection == {"enabled": True, "selected_ids": ["kb-1"]}
            assert source == "thread_metadata"
            mock_store.get.assert_awaited_once_with("thread-1", user_id="u1")


class TestRagMiddlewareKbSelection:
    def test_normalize_kb_selection_none_when_disabled(self):
        from deerflow.knowledge_base.retrieval import normalize_kb_selection

        assert normalize_kb_selection(None) is None
        assert normalize_kb_selection({"enabled": False, "selected_ids": ["kb-1"]}) is None

    def test_normalize_kb_selection_none_when_empty_ids(self):
        from deerflow.knowledge_base.retrieval import normalize_kb_selection

        assert normalize_kb_selection({"enabled": True, "selected_ids": []}) is None

    def test_normalize_kb_selection_returns_dict_when_valid(self):
        from deerflow.knowledge_base.retrieval import normalize_kb_selection

        result = normalize_kb_selection({"enabled": True, "selected_ids": ["kb-1", "kb-2"]})
        assert result is not None
        assert result["selected_ids"] == ["kb-1", "kb-2"]

    @patch("deerflow.agents.middlewares.rag_middleware.resolve_runtime_kb_selection")
    @patch("deerflow.agents.middlewares.rag_middleware._resolve_pool")
    def test_resolve_kb_selection_uses_shared_helper(self, mock_pool, mock_resolve):
        from deerflow.agents.middlewares.rag_middleware import RagMiddleware

        middleware = RagMiddleware()
        runtime = MagicMock()
        runtime.context = {"thread_id": "t-1"}

        mock_future = MagicMock()
        mock_future.result.return_value = ({"enabled": True, "selected_ids": ["kb-1"]}, "thread_metadata")
        mock_pool.submit.return_value = mock_future

        selection, source = middleware._resolve_kb_selection(runtime)

        assert selection == {"enabled": True, "selected_ids": ["kb-1"]}
        assert source == "thread_metadata"
        assert mock_pool.submit.call_count == 1

    def test_extract_last_user_message(self):
        from deerflow.agents.middlewares.rag_middleware import RagMiddleware

        msg1 = MagicMock()
        msg1.type = "human"
        msg1.content = "Hello"

        msg2 = MagicMock()
        msg2.type = "ai"
        msg2.content = "Hi there"

        msg3 = MagicMock()
        msg3.type = "human"
        msg3.content = "What is RAG?"

        result = RagMiddleware._extract_last_user_message([msg1, msg2, msg3])
        assert result == "What is RAG?"


class TestRagMiddlewareAfterAgent:
    def test_after_agent_no_context_returns_none(self):
        from deerflow.agents.middlewares.rag_middleware import RagMiddleware, _rag_retrieval_context

        _rag_retrieval_context.set(None)
        middleware = RagMiddleware()
        runtime = MagicMock()
        result = middleware.after_agent({"messages": []}, runtime)
        assert result is None

    def test_after_agent_attaches_metadata_to_ai_message(self):
        from langchain_core.messages import AIMessage

        from deerflow.agents.middlewares.rag_middleware import (
            KB_RETRIEVAL_TRACE_KEY,
            KB_SELECTION_SNAPSHOT_KEY,
            RagMiddleware,
            _rag_retrieval_context,
        )

        snapshot = {"enabled": True, "selected_ids": ["kb-1", "kb-2"], "resolved_kbs": [], "source": "runtime"}
        trace_data = {"query": "q", "per_kb_hits": [], "final_chunk_count": 0, "filtered_ids": [], "timeouts": [], "sources": [
            {"kb_id": "kb-1", "kb_name": "KB One", "doc_title": "Doc A", "score": 0.95},
            {"kb_id": "kb-2", "kb_name": "KB Two", "doc_title": "Doc B", "score": 0.88},
        ]}
        _rag_retrieval_context.set({"selection_snapshot": snapshot, "retrieval_trace": trace_data})

        ai_msg = AIMessage(content="Here is the answer based on your knowledge base.", id="msg-1")
        middleware = RagMiddleware()
        runtime = MagicMock()

        result = middleware.after_agent({"messages": [ai_msg]}, runtime)

        assert result is not None
        updated_msg = result["messages"][0]
        assert updated_msg.additional_kwargs[KB_SELECTION_SNAPSHOT_KEY] == snapshot
        assert updated_msg.additional_kwargs[KB_RETRIEVAL_TRACE_KEY] == trace_data
        assert updated_msg.content == "Here is the answer based on your knowledge base."
        assert updated_msg.id == "msg-1"

    def test_after_agent_handles_dict_knowledge_bases(self):
        from langchain_core.messages import AIMessage

        from deerflow.agents.middlewares.rag_middleware import RagMiddleware, _rag_retrieval_context

        snapshot = {"enabled": True, "selected_ids": ["kb-1"], "resolved_kbs": [], "source": "runtime"}
        trace_data = {"query": "q", "per_kb_hits": [], "final_chunk_count": 0, "filtered_ids": [], "timeouts": [], "sources": [
            {"kb_id": "kb-1", "kb_name": "KB One", "doc_title": "Doc A", "score": 0.95},
        ]}
        _rag_retrieval_context.set({"selection_snapshot": snapshot, "retrieval_trace": trace_data})

        ai_msg = AIMessage(content="answer", id="msg-1")
        middleware = RagMiddleware()
        runtime = MagicMock()

        result = middleware.after_agent({"messages": [ai_msg]}, runtime)

        assert result is not None
        updated_msg = result["messages"][0]
        assert updated_msg.additional_kwargs["knowledge_base_selection_snapshot"]["source"] == "runtime"

    def test_after_agent_clears_context_after_use(self):
        from langchain_core.messages import AIMessage

        from deerflow.agents.middlewares.rag_middleware import RagMiddleware, _rag_retrieval_context

        _rag_retrieval_context.set({"selection_snapshot": {}, "retrieval_trace": []})

        ai_msg = AIMessage(content="answer", id="msg-2")
        middleware = RagMiddleware()
        runtime = MagicMock()
        middleware.after_agent({"messages": [ai_msg]}, runtime)

        assert _rag_retrieval_context.get() is None

    def test_after_agent_skips_non_ai_message(self):
        from langchain_core.messages import HumanMessage

        from deerflow.agents.middlewares.rag_middleware import RagMiddleware, _rag_retrieval_context

        _rag_retrieval_context.set({"selection_snapshot": {}, "retrieval_trace": []})

        human_msg = HumanMessage(content="hello", id="msg-3")
        middleware = RagMiddleware()
        runtime = MagicMock()

        result = middleware.after_agent({"messages": [human_msg]}, runtime)
        assert result is None

    def test_after_agent_preserves_existing_additional_kwargs(self):
        from langchain_core.messages import AIMessage

        from deerflow.agents.middlewares.rag_middleware import (
            KB_RETRIEVAL_TRACE_KEY,
            KB_SELECTION_SNAPSHOT_KEY,
            RagMiddleware,
            _rag_retrieval_context,
        )

        _rag_retrieval_context.set({"selection_snapshot": {"selected_ids": ["kb-1"]}, "retrieval_trace": []})

        ai_msg = AIMessage(content="answer", id="msg-4", additional_kwargs={"existing_key": "value"})
        middleware = RagMiddleware()
        runtime = MagicMock()

        result = middleware.after_agent({"messages": [ai_msg]}, runtime)

        assert result is not None
        updated_msg = result["messages"][0]
        assert updated_msg.additional_kwargs["existing_key"] == "value"
        assert KB_SELECTION_SNAPSHOT_KEY in updated_msg.additional_kwargs
        assert KB_RETRIEVAL_TRACE_KEY in updated_msg.additional_kwargs


class TestBuildRetrievalTraceData:
    def test_empty_results(self):
        from deerflow.knowledge_base.retrieval import build_retrieval_trace_data

        result = build_retrieval_trace_data(query="q", results=[], knowledge_bases=[])
        assert result == {
            "query": "q",
            "per_kb_hits": [],
            "final_chunk_count": 0,
            "filtered_ids": [],
            "timeouts": [],
            "sources": [],
        }

    def test_builds_structured_sources(self):
        from deerflow.knowledge_base.retrieval import build_retrieval_trace_data

        kb = {"id": "kb-1", "name": "Test KB"}
        chunk = MagicMock()
        chunk.metadata = {"knowledge_base_id": "kb-1", "title": "Doc 1", "kb_name": "Test KB"}
        chunk.score = 0.923

        result = build_retrieval_trace_data(query="q", results=[chunk], knowledge_bases=[kb])
        assert result["sources"][0] == {"kb_id": "kb-1", "kb_name": "Test KB", "doc_title": "Doc 1", "score": 0.923}
        assert result["final_chunk_count"] == 1

    def test_deduplicates_by_kb_and_doc(self):
        from deerflow.knowledge_base.retrieval import build_retrieval_trace_data

        kb = {"id": "kb-1", "name": "KB"}

        chunk1 = MagicMock()
        chunk1.metadata = {"knowledge_base_id": "kb-1", "title": "Same Doc"}
        chunk1.score = 0.9

        chunk2 = MagicMock()
        chunk2.metadata = {"knowledge_base_id": "kb-1", "title": "Same Doc"}
        chunk2.score = 0.8

        result = build_retrieval_trace_data(query="q", results=[chunk1, chunk2], knowledge_bases=[kb])
        assert len(result["sources"]) == 1


class TestSearchToolKbSelection:
    """Tests for P0: search_knowledge_base tool respecting KB selection from runtime context."""

    def _make_config(self, kb_selection=None, tenant_id="t1", user_id="u1"):
        """Build a RunnableConfig with a mock __pregel_runtime."""
        runtime = MagicMock()
        context = {"tenant_id": tenant_id, "user_id": user_id}
        if kb_selection is not None:
            context["knowledge_base_selection"] = kb_selection
        runtime.context = context
        return {"configurable": {"__pregel_runtime": runtime}}

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_falls_back_to_single_collection_when_no_selection(self, mock_pool, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.score_threshold = 0.0
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        config = self._make_config(kb_selection=None)

        from deerflow.rag.vector_store import SearchResult

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf, \
             patch("deerflow.knowledge_base.retrieval.multi_kb_retrieve") as mock_multi:
            mock_sf.return_value = MagicMock()

            mock_future = MagicMock()
            mock_future.result.side_effect = [
                (None, None),  # _resolve_kb_selection: no selection found
                [{"id": "kb-1", "collection_name": "my_col", "name": "My KB"}],  # resolve_active_by_collections
            ]
            mock_pool.submit.return_value = mock_future

            mock_multi.return_value = [
                SearchResult(chunk_id="c1", content="found it", metadata={"kb_name": "My KB", "title": "Doc1"}, score=0.9),
            ]

            result = search_knowledge_base.invoke({"query": "test", "collection": "my_col"}, config=config)
            data = json.loads(result)
            assert data["collection"] == "my_col"
            assert len(data["results"]) == 1

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_uses_kb_selection_when_present(self, mock_pool, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        kb_selection = {"enabled": True, "selected_ids": ["kb-1", "kb-2"]}
        config = self._make_config(kb_selection=kb_selection)

        from deerflow.rag.vector_store import SearchResult

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf, \
             patch("deerflow.knowledge_base.retrieval.multi_kb_retrieve") as mock_multi:
            mock_sf.return_value = MagicMock()

            mock_future = MagicMock()
            mock_future.result.side_effect = [
                ({"enabled": True, "selected_ids": ["kb-1", "kb-2"]}, "runtime"),  # _resolve_kb_selection
                [{"id": "kb-1", "collection_name": "col_1", "name": "KB One"}],  # resolve_active_by_ids
            ]
            mock_pool.submit.return_value = mock_future

            mock_multi.return_value = [
                SearchResult(chunk_id="c1", content="found it", metadata={"kb_name": "KB One", "title": "Doc1"}, score=0.9),
            ]

            result = search_knowledge_base.invoke({"query": "test"}, config=config)
            data = json.loads(result)
            assert "collection" not in data
            assert len(data["results"]) == 1
            assert data["results"][0]["kb_name"] == "KB One"

    @patch("deerflow.rag.tools.get_rag_config")
    def test_blocked_in_no_auth_mode(self, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = False
        mock_get_config.return_value = mock_config

        kb_selection = {"enabled": True, "selected_ids": ["kb-1"]}
        config = self._make_config(kb_selection=kb_selection, user_id="default")

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf:
            mock_sf.return_value = MagicMock()
            result = search_knowledge_base.invoke({"query": "test"}, config=config)
            data = json.loads(result)
            assert "authentication" in data["error"].lower()
            assert data["results"] == []

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_allowed_in_no_auth_when_configured(self, mock_pool, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        kb_selection = {"enabled": True, "selected_ids": ["kb-1"]}
        config = self._make_config(kb_selection=kb_selection, user_id="default")

        from deerflow.rag.vector_store import SearchResult

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf, \
             patch("deerflow.knowledge_base.retrieval.multi_kb_retrieve") as mock_multi:
            mock_sf.return_value = MagicMock()

            mock_future = MagicMock()
            mock_future.result.side_effect = [
                ({"enabled": True, "selected_ids": ["kb-1"]}, "runtime"),  # _resolve_kb_selection
                [{"id": "kb-1", "collection_name": "col_1", "name": "KB One"}],  # resolve_active_by_ids
            ]
            mock_pool.submit.return_value = mock_future

            mock_multi.return_value = [
                SearchResult(chunk_id="c1", content="ok", metadata={"kb_name": "KB One", "title": "Doc1"}, score=0.85),
            ]

            result = search_knowledge_base.invoke({"query": "test"}, config=config)
            data = json.loads(result)
            assert "error" not in data
            assert len(data["results"]) >= 1

    @patch("deerflow.rag.tools.get_rag_config")
    def test_no_config_returns_context_error(self, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.score_threshold = 0.0
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        result = search_knowledge_base.invoke({"query": "test"})
        data = json.loads(result)
        assert "Missing tenant or user context" == data["error"]
        assert data["results"] == []

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_explicit_collection_is_blocked_when_not_owned(self, mock_pool, mock_get_config):
        import json

        from deerflow.rag.tools import search_knowledge_base

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.score_threshold = 0.0
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        config = self._make_config(kb_selection=None)

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf, \
             patch("deerflow.knowledge_base.retrieval.multi_kb_retrieve") as mock_multi:
            mock_sf.return_value = MagicMock()
            mock_future = MagicMock()
            mock_future.result.side_effect = [
                (None, None),  # _resolve_kb_selection: no selection
                [],  # resolve_active_by_collections: not owned
            ]
            mock_pool.submit.return_value = mock_future

            result = search_knowledge_base.invoke({"query": "test", "collection": "foreign_col"}, config=config)
            data = json.loads(result)
            assert "error" in data
            assert data["results"] == []
            mock_multi.assert_not_called()


class TestMiddlewareNoAuthGuard:
    """Tests for P1: middleware blocks KB access in no-auth mode."""

    def test_middleware_blocked_in_no_auth_mode(self):
        from deerflow.agents.middlewares.rag_middleware import RagMiddleware

        middleware = RagMiddleware()
        runtime = MagicMock()
        runtime.context = {
            "knowledge_base_selection": {"enabled": True, "selected_ids": ["kb-1"]},
            "tenant_id": "t1",
            "user_id": "default",
        }

        with patch("deerflow.agents.middlewares.rag_middleware.get_rag_config") as mock_cfg:
            mock_config = MagicMock()
            mock_config.enabled = True
            mock_config.injection_enabled = True
            mock_config.max_selected_kbs = 5
            mock_config.allow_no_auth_kb = False
            mock_cfg.return_value = mock_config

            result = middleware._retrieve_from_selected_kbs(
                {"enabled": True, "selected_ids": ["kb-1"]}, "test query", runtime,
                selection_source="runtime",
            )
            assert result is None

    def test_middleware_allowed_when_configured(self):
        from deerflow.agents.middlewares.rag_middleware import RagMiddleware

        middleware = RagMiddleware()
        runtime = MagicMock()
        runtime.context = {
            "knowledge_base_selection": {"enabled": True, "selected_ids": ["kb-1"]},
            "tenant_id": "t1",
            "user_id": "default",
        }

        with patch("deerflow.agents.middlewares.rag_middleware.get_rag_config") as mock_cfg, \
             patch("deerflow.persistence.engine.get_session_factory") as mock_sf:
            mock_config = MagicMock()
            mock_config.enabled = True
            mock_config.injection_enabled = True
            mock_config.max_selected_kbs = 5
            mock_config.allow_no_auth_kb = True
            mock_cfg.return_value = mock_config
            mock_sf.return_value = None  # short-circuit at session factory check

            result = middleware._retrieve_from_selected_kbs(
                {"enabled": True, "selected_ids": ["kb-1"]}, "test query", runtime,
                selection_source="runtime",
            )
            # Returns None because sf is None, but importantly it passed the no-auth guard
            assert result is None
            mock_sf.assert_called_once()
