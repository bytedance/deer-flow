"""Tests for RAG tools."""

import json
from unittest.mock import MagicMock, patch

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.rag.tools import search_knowledge_base


class TestSearchKnowledgeBaseTool:
    def test_returns_error_when_disabled(self):
        set_rag_config(RagConfig(enabled=False))
        try:
            result = search_knowledge_base.invoke({"query": "test"})
            data = json.loads(result)
            assert "error" in data
            assert data["results"] == []
        finally:
            set_rag_config(RagConfig())

    def test_tool_has_correct_name(self):
        assert search_knowledge_base.name == "search_knowledge_base"

    def test_tool_accepts_collection_param(self):
        schema = search_knowledge_base.args_schema
        assert "collection" in schema.model_fields

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_returns_generic_error_on_failure(self, mock_pool, mock_get_config):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "t1", "user_id": "u1"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf:
            mock_sf.return_value = MagicMock()
            mock_pool.submit.side_effect = RuntimeError("sensitive backend detail")

            result = search_knowledge_base.invoke({"query": "test", "collection": "default"}, config=config)
            data = json.loads(result)
            assert data["error"] == "Knowledge base search failed"
            assert data["results"] == []

    @patch("deerflow.rag.tools._resolve_pool")
    def test_extract_kb_selection_uses_shared_resolver(self, mock_pool):
        from deerflow.rag.tools import _extract_kb_selection

        runtime = MagicMock()
        runtime.context = {"thread_id": "t1"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_future = MagicMock()
        mock_future.result.return_value = ({"enabled": True, "selected_ids": ["kb-1"]}, "thread_metadata")
        mock_pool.submit.return_value = mock_future

        selection = _extract_kb_selection(config)

        assert selection == {"enabled": True, "selected_ids": ["kb-1"]}
        assert mock_pool.submit.call_count == 1

    @patch("deerflow.rag.tools.get_rag_config")
    @patch("deerflow.rag.tools._resolve_pool")
    def test_search_uses_thread_metadata_fallback_selection(self, mock_pool, mock_get_config):
        from deerflow.rag.vector_store import SearchResult

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "t1", "user_id": "u1", "thread_id": "thread-1"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolver_future = MagicMock()
        mock_resolver_future.result.side_effect = [
            ({"enabled": True, "selected_ids": ["kb-1"]}, "thread_metadata"),
            [{"id": "kb-1", "collection_name": "col_1", "name": "KB One"}],
        ]
        mock_pool.submit.return_value = mock_resolver_future

        with patch("deerflow.persistence.engine.get_session_factory") as mock_sf, patch(
            "deerflow.knowledge_base.retrieval.multi_kb_retrieve"
        ) as mock_multi:
            mock_sf.return_value = MagicMock()
            mock_multi.return_value = [
                SearchResult(
                    chunk_id="c1",
                    content="found it",
                    metadata={"kb_name": "KB One", "title": "Doc1"},
                    score=0.9,
                ),
            ]

            result = search_knowledge_base.invoke({"query": "test"}, config=config)
            data = json.loads(result)

            assert len(data["results"]) == 1
            assert data["results"][0]["kb_name"] == "KB One"
