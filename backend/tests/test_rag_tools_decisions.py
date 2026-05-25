"""Tests for the ``decision`` field on ``search_knowledge_base`` (Sprint A.3 + B.2.2).

Every code path through the tool must include a ``decision`` payload in
its JSON return — same shape as ``RagDecisionEvent.to_dict()`` — so the
SSE transparency stream can show *what the tool did*.

After Sprint B.2.2 the tool is async-native; tests use ``ainvoke`` and
patch ``resolve_runtime_kb_selection`` directly instead of the removed
``_resolve_pool`` ThreadPoolExecutor.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.rag.tools import search_knowledge_base


class TestSearchKnowledgeBaseDecisions:
    def teardown_method(self) -> None:
        set_rag_config(RagConfig())

    @pytest.mark.asyncio
    async def test_decision_disabled_when_rag_disabled(self) -> None:
        set_rag_config(RagConfig(enabled=False))

        result = await search_knowledge_base.ainvoke({"query": "what is x?"})
        data = json.loads(result)

        assert "decision" in data
        assert data["decision"]["outcome"] == "disabled"
        assert data["decision"]["source"] == "tool"
        assert data["decision"]["query"] == "what is x?"

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_decision_failed_on_unexpected_exception(
        self, mock_resolve, mock_get_config
    ) -> None:
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "t1", "user_id": "u1"}
        config = {"configurable": {"__pregel_runtime": runtime}}
        mock_resolve.side_effect = RuntimeError("boom")

        result = await search_knowledge_base.ainvoke(
            {"query": "test", "collection": "default"}, config=config
        )
        data = json.loads(result)

        assert data["decision"]["outcome"] == "failed"
        assert "RuntimeError" in data["decision"]["reason"]

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    async def test_decision_blocked_on_missing_tenant(self, mock_get_config) -> None:
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "", "user_id": ""}
        config = {"configurable": {"__pregel_runtime": runtime}}

        async def _no_selection(_cfg):
            return None

        with patch(
            "deerflow.rag.tools._extract_kb_selection",
            side_effect=_no_selection,
        ), patch(
            "deerflow.rag.tools.get_effective_user_id", return_value=""
        ), patch(
            "deerflow.rag.tools.get_current_tenant_id", return_value=""
        ):
            result = await search_knowledge_base.ainvoke(
                {"query": "x", "collection": "kb1"}, config=config
            )
        data = json.loads(result)

        assert data["decision"]["outcome"] == "blocked"
        assert (
            "tenant" in data["decision"]["reason"]
            or "user" in data["decision"]["reason"]
        )

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    async def test_decision_blocked_for_no_auth_user(self, mock_get_config) -> None:
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.allow_no_auth_kb = False
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {"tenant_id": "t1", "user_id": "default"}
        config = {"configurable": {"__pregel_runtime": runtime}}

        async def _no_selection(_cfg):
            return None

        with patch(
            "deerflow.rag.tools._extract_kb_selection",
            side_effect=_no_selection,
        ):
            result = await search_knowledge_base.ainvoke(
                {"query": "x", "collection": "kb1"}, config=config
            )
        data = json.loads(result)

        assert data["decision"]["outcome"] == "blocked"
        assert "no-auth" in data["decision"]["reason"]

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_decision_injected_when_results_returned(
        self, mock_resolve, mock_get_config
    ) -> None:
        from deerflow.rag.vector_store import SearchResult

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_config.cross_kb_score_strategy = "absolute"
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {
            "tenant_id": "t1",
            "user_id": "u1",
            "thread_id": "th1",
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
                    content="hit",
                    metadata={"kb_name": "KB One", "title": "doc"},
                    score=0.95,
                ),
            ]

            result = await search_knowledge_base.ainvoke(
                {"query": "hello"}, config=config
            )
            data = json.loads(result)

        assert data["decision"]["outcome"] == "injected"
        assert data["decision"]["chunks_returned"] == 1
        assert data["decision"]["chunks_injected"] == 1
        assert data["decision"]["selected_kb_ids"] == ["kb-1"]
        assert data["decision"]["accessible_kb_ids"] == ["kb-1"]
        assert data["decision"]["score_strategy"] == "absolute"

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_decision_blocked_with_denied_kb_ids(
        self, mock_resolve, mock_get_config
    ) -> None:
        """When all requested KBs are denied, response includes structured denied detail."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {
            "tenant_id": "t1",
            "user_id": "u1",
            "thread_id": "th1",
        }
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolve.return_value = (
            {"enabled": True, "selected_ids": ["kb-1", "kb-2"]},
            "thread_metadata",
        )

        with patch(
            "deerflow.persistence.engine.get_session_factory"
        ) as mock_sf, patch(
            "deerflow.persistence.knowledge_base.repository.KnowledgeBaseRepository.resolve_accessible_by_ids",
            new_callable=AsyncMock,
        ) as mock_resolve_ids:
            mock_sf.return_value = MagicMock()
            # All requested KBs are denied — resolve returns empty
            mock_resolve_ids.return_value = []

            result = await search_knowledge_base.ainvoke(
                {"query": "hello"}, config=config
            )
            data = json.loads(result)

        assert data["decision"]["outcome"] == "blocked"
        assert data["decision"]["selected_kb_ids"] == ["kb-1", "kb-2"]
        assert data["decision"]["accessible_kb_ids"] == []
        assert data["decision"]["denied_kb_ids"] == ["kb-1", "kb-2"]
        assert "denied" in data
        assert data["denied"]["reason"] == "access_denied"
        assert "denied_kb_ids" in data["denied"]

    @pytest.mark.asyncio
    @patch("deerflow.rag.tools.get_rag_config")
    @patch(
        "deerflow.rag.tools.resolve_runtime_kb_selection",
        new_callable=AsyncMock,
    )
    async def test_decision_denied_kb_ids_alongside_results(
        self, mock_resolve, mock_get_config
    ) -> None:
        """When some KBs are denied, results include both chunks and denied info."""
        from deerflow.rag.vector_store import SearchResult

        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.retrieval_top_k = 5
        mock_config.max_selected_kbs = 5
        mock_config.allow_no_auth_kb = True
        mock_config.cross_kb_score_strategy = "absolute"
        mock_get_config.return_value = mock_config

        runtime = MagicMock()
        runtime.context = {
            "tenant_id": "t1",
            "user_id": "u1",
            "thread_id": "th1",
        }
        config = {"configurable": {"__pregel_runtime": runtime}}

        mock_resolve.return_value = (
            {"enabled": True, "selected_ids": ["kb-1", "kb-2", "kb-3"]},
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
            # Only kb-1 and kb-3 are accessible; kb-2 is denied
            mock_resolve_ids.return_value = [
                {"id": "kb-1", "collection_name": "col_1", "name": "KB One", "visibility": "tenant", "tenant_id": "t1", "owner_user_id": "u1", "deleted_at": None},
                {"id": "kb-3", "collection_name": "col_3", "name": "KB Three", "visibility": "tenant", "tenant_id": "t1", "owner_user_id": "u1", "deleted_at": None},
            ]
            mock_multi.return_value = [
                SearchResult(
                    chunk_id="c1",
                    content="hit from kb-1",
                    metadata={"kb_name": "KB One", "title": "doc"},
                    score=0.95,
                ),
            ]

            result = await search_knowledge_base.ainvoke(
                {"query": "hello"}, config=config
            )
            data = json.loads(result)

        assert data["decision"]["outcome"] == "injected"
        assert data["decision"]["selected_kb_ids"] == ["kb-1", "kb-2", "kb-3"]
        assert data["decision"]["accessible_kb_ids"] == ["kb-1", "kb-3"]
        assert data["decision"]["denied_kb_ids"] == ["kb-2"]
        assert "denied" in data
        assert data["denied"]["reason"] == "access_denied"
        assert len(data["results"]) == 1
