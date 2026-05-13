"""Tests for GenUI block persistence and checkpoint recovery."""

import json

import pytest

from deerflow.agents.genui_persistence import (
    clear_thread_blocks,
    extract_blocks_from_messages,
    get_persisted_blocks,
    persist_block,
)


class TestInMemoryPersistence:
    def setup_method(self):
        clear_thread_blocks("test-thread")

    def test_persist_and_retrieve(self):
        block = {"block_id": "b1", "component": "chart", "props": {"title": "Test"}}
        persist_block("test-thread", block)
        blocks = get_persisted_blocks("test-thread")
        assert len(blocks) == 1
        assert blocks[0]["block_id"] == "b1"

    def test_clear_thread_blocks(self):
        persist_block("test-thread", {"block_id": "b1", "component": "card", "props": {}})
        clear_thread_blocks("test-thread")
        assert get_persisted_blocks("test-thread") == []

    def test_multiple_blocks(self):
        persist_block("test-thread", {"block_id": "b1", "component": "chart", "props": {}})
        persist_block("test-thread", {"block_id": "b2", "component": "table", "props": {}})
        blocks = get_persisted_blocks("test-thread")
        assert len(blocks) == 2


class TestExtractBlocksFromMessages:
    def _make_tool_msg(self, block: dict) -> dict:
        block_json = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
        content = f"UI component '{block['component']}' (create) rendered successfully. block_id={block['block_id']}\n<!--ui_block:{block_json}-->"
        return {"content": content}

    def test_extract_single_block(self):
        block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "abc-123",
            "component": "chart",
            "props": {"chart_type": "bar", "data": []},
            "interactive": False,
        }
        messages = [self._make_tool_msg(block)]
        result = extract_blocks_from_messages(messages)
        assert len(result) == 1
        assert result[0]["block_id"] == "abc-123"
        assert result[0]["component"] == "chart"

    def test_extract_multiple_blocks(self):
        block1 = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "b1",
            "component": "chart",
            "props": {"chart_type": "line", "data": []},
            "interactive": False,
        }
        block2 = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "b2",
            "component": "table",
            "props": {"columns": [], "data": []},
            "interactive": False,
        }
        messages = [self._make_tool_msg(block1), self._make_tool_msg(block2)]
        result = extract_blocks_from_messages(messages)
        assert len(result) == 2
        ids = {b["block_id"] for b in result}
        assert ids == {"b1", "b2"}

    def test_update_merges_props(self):
        create_block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "b1",
            "component": "card",
            "props": {"title": "Original", "value": "100"},
            "interactive": False,
        }
        update_block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "update",
            "block_id": "b1",
            "component": "card",
            "props": {"value": "200"},
            "interactive": False,
        }
        messages = [self._make_tool_msg(create_block), self._make_tool_msg(update_block)]
        result = extract_blocks_from_messages(messages)
        assert len(result) == 1
        assert result[0]["props"]["title"] == "Original"
        assert result[0]["props"]["value"] == "200"

    def test_delete_removes_block(self):
        create_block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "b1",
            "component": "chart",
            "props": {"chart_type": "pie", "data": []},
            "interactive": False,
        }
        delete_block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "delete",
            "block_id": "b1",
            "component": "chart",
            "props": {},
            "interactive": False,
        }
        messages = [self._make_tool_msg(create_block), self._make_tool_msg(delete_block)]
        result = extract_blocks_from_messages(messages)
        assert len(result) == 0

    def test_ignores_non_tool_messages(self):
        messages = [
            {"content": "Hello, how can I help you?"},
            {"content": "Please analyze this data."},
        ]
        result = extract_blocks_from_messages(messages)
        assert result == []

    def test_ignores_malformed_json(self):
        messages = [{"content": "result\n<!--ui_block:{invalid json}-->"}]
        result = extract_blocks_from_messages(messages)
        assert result == []

    def test_ignores_block_without_id(self):
        messages = [{"content": "result\n<!--ui_block:{\"component\":\"chart\",\"props\":{}}-->"}]
        result = extract_blocks_from_messages(messages)
        assert result == []

    def test_handles_object_messages(self):
        """Test with object-style messages that have .content attribute."""

        class FakeMessage:
            def __init__(self, content: str):
                self.content = content

        block = {
            "schema_version": "1.0",
            "type": "ui_block",
            "action": "create",
            "block_id": "obj-1",
            "component": "card",
            "props": {"title": "Test", "value": "42"},
            "interactive": False,
        }
        block_json = json.dumps(block, ensure_ascii=False, separators=(",", ":"))
        msg = FakeMessage(f"Success\n<!--ui_block:{block_json}-->")
        result = extract_blocks_from_messages([msg])
        assert len(result) == 1
        assert result[0]["block_id"] == "obj-1"

    def test_empty_messages(self):
        result = extract_blocks_from_messages([])
        assert result == []

    def test_none_content(self):
        messages = [{"content": None}, {"content": ""}]
        result = extract_blocks_from_messages(messages)
        assert result == []
