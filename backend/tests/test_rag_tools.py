"""Tests for RAG tools."""

import json

from deerflow.config.rag_config import RagConfig, set_rag_config
from deerflow.rag.tools import search_knowledge_base


class TestSearchKnowledgeBaseTool:
    def test_returns_error_when_disabled(self):
        original = set_rag_config
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
        # Just verify the schema accepts the parameter
        schema = search_knowledge_base.args_schema
        assert "collection" in schema.model_fields
