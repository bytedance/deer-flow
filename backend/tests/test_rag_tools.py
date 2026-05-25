"""Tests for RAG tools (async-native after Sprint B.2.2)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.rag.tools import search_knowledge_base


class TestSearchKnowledgeBaseTool:
    @pytest.mark.asyncio
    async def test_returns_error_when_disabled(self):
        set_rag_config(RagConfig(enabled=False))
        try:
            result = await search_knowledge_base.ainvoke({"query": "test"})
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

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_returns_generic_error_on_failure(
        self, mock_resolve, mock_get_config
    ):
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "t1", "user_id": "u1"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolve.side_effect = RuntimeError("sensitive backend detail")

        result = await search_knowledge_base.ainvoke(
            {"query": "test", "collection": "default"}, config=config
        )
        data = json.loads(result)
        assert data["error"] == "Knowledge base search failed"
        assert data["results"] == []

    @pytest.mark.asyncio
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_extract_kb_selection_uses_shared_resolver(self, mock_resolve):
        from deerflow.rag.tools import _extract_kb_selection

        runtime = MagicMock()
        runtime.context = {"thread_id": "t1"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolve.return_value = (
            {"enabled": True, "selected_ids": ["kb-1"]},
            "thread_metadata",
        )

        selection = await _extract_kb_selection(config)

        assert selection == {"enabled": True, "selected_ids": ["kb-1"]}
        assert mock_resolve.call_count == 1

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_search_uses_thread_metadata_fallback_selection(
        self, mock_resolve, mock_get_config
    ):
        from deerflow.rag.vector_store import SearchResult

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_config.cross_kb_score_strategy = None
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {
            "tenant_id": "t1",
            "user_id": "u1",
            "thread_id": "thread-1",
        }
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolve.return_value = (
            {"enabled": True, "selected_ids": ["kb-1"]},
            "thread_metadata",
        )

        with patch(
            "deerflow.persistence.engine.get_session_factory"
        ) as mock_sf, patch(
            "deerflow.persistence.knowledge_base.repository.KnowledgeBaseRepository.resolve_accessible_by_ids",
            new_callable=AsyncMock,
        ) as mock_resolve_ids, patch(
            "deerflow.knowledge_base.retrieval.multi_kb_retrieve"
        ) as mock_multi:
            mock_sf.return_value = MagicMock()
            mock_resolve_ids.return_value = [
                {"id": "kb-1", "collection_name": "col_1", "name": "KB One", "visibility": "tenant", "tenant_id": "t1", "owner_user_id": "u1", "deleted_at": None}
            ]
            mock_multi.return_value = [
                SearchResult(
                    chunk_id="c1",
                    content="found it",
                    metadata={"kb_name": "KB One", "title": "Doc1"},
                    score=0.9,
                ),
            ]

            result = await search_knowledge_base.ainvoke(
                {"query": "test"}, config=config
            )
            data = json.loads(result)

            assert len(data["results"]) == 1
            assert data["results"][0]["kb_name"] == "KB One"
