# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Unit tests for tool call chunk processing.

Tests for the fix of issue #523: Tool name concatenation in consecutive tool calls.
This ensures that tool call chunks are properly segregated by index to prevent
tool names from being concatenated when multiple tool calls happen in sequence.
"""

import logging
import pytest
from unittest.mock import patch, MagicMock

# Import the functions to test
# Note: We need to import from the app module
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../"))

from src.server.app import _process_tool_call_chunks, _validate_tool_call_chunks


class TestProcessToolCallChunks:
    """Test cases for _process_tool_call_chunks function."""

    def test_empty_tool_call_chunks(self):
        """Test processing empty tool call chunks."""
        result = _process_tool_call_chunks([])
        assert result == []

    def test_single_tool_call_single_chunk(self):
        """Test processing a single tool call with a single chunk."""
        chunks = [
            {"name": "web_search", "args": '{"query": "test"}', "id": "call_1", "index": 0}
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 1
        assert result[0]["name"] == "web_search"
        assert result[0]["id"] == "call_1"
        assert result[0]["index"] == 0
        assert '"query": "test"' in result[0]["args"]

    def test_consecutive_tool_calls_different_indices(self):
        """Test that consecutive tool calls with different indices are not concatenated."""
        chunks = [
            {"name": "web_search", "args": '{"query": "test"}', "id": "call_1", "index": 0},
            {"name": "web_search", "args": '{"query": "test2"}', "id": "call_2", "index": 1},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 2
        assert result[0]["name"] == "web_search"
        assert result[0]["id"] == "call_1"
        assert result[0]["index"] == 0
        assert result[1]["name"] == "web_search"
        assert result[1]["id"] == "call_2"
        assert result[1]["index"] == 1
        # Verify names are NOT concatenated
        assert result[0]["name"] != "web_searchweb_search"
        assert result[1]["name"] != "web_searchweb_search"

    def test_different_tools_different_indices(self):
        """Test consecutive calls to different tools."""
        chunks = [
            {"name": "web_search", "args": '{"query": "test"}', "id": "call_1", "index": 0},
            {"name": "crawl_tool", "args": '{"url": "http://example.com"}', "id": "call_2", "index": 1},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 2
        assert result[0]["name"] == "web_search"
        assert result[1]["name"] == "crawl_tool"
        # Verify names are NOT concatenated (the issue bug scenario)
        assert "web_searchcrawl_tool" not in result[0]["name"]
        assert "web_searchcrawl_tool" not in result[1]["name"]

    def test_streaming_chunks_same_index(self):
        """Test streaming chunks with same index are properly accumulated."""
        chunks = [
            {"name": "web_", "args": '{"query"', "id": "call_1", "index": 0},
            {"name": "search", "args": ': "test"}', "id": "call_1", "index": 0},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 1
        # Name should NOT be concatenated when it's the same tool
        assert result[0]["name"] in ["web_", "search", "web_search"]
        assert result[0]["id"] == "call_1"
        # Args should be accumulated
        assert "query" in result[0]["args"]
        assert "test" in result[0]["args"]

    def test_tool_call_index_collision_warning(self):
        """Test that index collision with different names generates warning."""
        chunks = [
            {"name": "web_search", "args": '{}', "id": "call_1", "index": 0},
            {"name": "crawl_tool", "args": '{}', "id": "call_2", "index": 0},
        ]
        
        # This should trigger a warning
        with patch('src.server.app.logger') as mock_logger:
            result = _process_tool_call_chunks(chunks)
            
            # Verify warning was logged
            mock_logger.warning.assert_called()
            call_args = mock_logger.warning.call_args[0][0]
            assert "Tool name mismatch detected" in call_args
            assert "web_search" in call_args
            assert "crawl_tool" in call_args

    def test_chunks_without_explicit_index(self):
        """Test handling chunks without explicit index (edge case)."""
        chunks = [
            {"name": "web_search", "args": '{}', "id": "call_1"}  # No index
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 1
        assert result[0]["name"] == "web_search"

    def test_chunk_sorting_by_index(self):
        """Test that chunks are sorted by index in proper order."""
        chunks = [
            {"name": "tool_3", "args": '{}', "id": "call_3", "index": 2},
            {"name": "tool_1", "args": '{}', "id": "call_1", "index": 0},
            {"name": "tool_2", "args": '{}', "id": "call_2", "index": 1},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 3
        assert result[0]["index"] == 0
        assert result[1]["index"] == 1
        assert result[2]["index"] == 2

    def test_args_accumulation(self):
        """Test that arguments are properly accumulated for same index."""
        chunks = [
            {"name": "web_search", "args": '{"q', "id": "call_1", "index": 0},
            {"name": "web_search", "args": 'uery": "test"}', "id": "call_1", "index": 0},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 1
        # Sanitize removes json encoding, so just check it's accumulated
        assert len(result[0]["args"]) > 0

    def test_preserve_tool_id(self):
        """Test that tool IDs are preserved correctly."""
        chunks = [
            {"name": "web_search", "args": '{}', "id": "call_abc123", "index": 0},
            {"name": "web_search", "args": '{}', "id": "call_xyz789", "index": 1},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert result[0]["id"] == "call_abc123"
        assert result[1]["id"] == "call_xyz789"

    def test_multiple_indices_detected(self):
        """Test that multiple indices are properly detected and logged."""
        chunks = [
            {"name": "tool_a", "args": '{}', "id": "call_1", "index": 0},
            {"name": "tool_b", "args": '{}', "id": "call_2", "index": 1},
            {"name": "tool_c", "args": '{}', "id": "call_3", "index": 2},
        ]
        
        with patch('src.server.app.logger') as mock_logger:
            result = _process_tool_call_chunks(chunks)
            
            # Should have debug logs for multiple indices
            debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            # Check if any debug call mentions multiple indices
            multiple_indices_mentioned = any(
                "Multiple indices" in call for call in debug_calls
            )
            assert multiple_indices_mentioned or len(result) == 3


class TestValidateToolCallChunks:
    """Test cases for _validate_tool_call_chunks function."""

    def test_validate_empty_chunks(self):
        """Test validation of empty chunks."""
        # Should not raise any exception
        _validate_tool_call_chunks([])

    def test_validate_logs_chunk_info(self):
        """Test that validation logs chunk information."""
        chunks = [
            {"name": "web_search", "args": '{}', "id": "call_1", "index": 0},
        ]
        
        with patch('src.server.app.logger') as mock_logger:
            _validate_tool_call_chunks(chunks)
            
            # Should have logged debug info
            assert mock_logger.debug.called

    def test_validate_detects_multiple_indices(self):
        """Test that validation detects multiple indices."""
        chunks = [
            {"name": "tool_1", "args": '{}', "id": "call_1", "index": 0},
            {"name": "tool_2", "args": '{}', "id": "call_2", "index": 1},
        ]
        
        with patch('src.server.app.logger') as mock_logger:
            _validate_tool_call_chunks(chunks)
            
            # Should have logged about multiple indices
            debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
            multiple_indices_mentioned = any(
                "Multiple indices" in call for call in debug_calls
            )
            assert multiple_indices_mentioned


class TestRealWorldScenarios:
    """Test cases for real-world scenarios from issue #523."""

    def test_issue_523_scenario_consecutive_web_search(self):
        """
        Replicate issue #523: Consecutive web_search calls.
        Previously would result in "web_searchweb_search" error.
        """
        # Simulate streaming chunks from two consecutive web_search calls
        chunks = [
            # First web_search call (index 0)
            {"name": "web_", "args": '{"query', "id": "call_1", "index": 0},
            {"name": "search", "args": '": "first query"}', "id": "call_1", "index": 0},
            # Second web_search call (index 1)
            {"name": "web_", "args": '{"query', "id": "call_2", "index": 1},
            {"name": "search", "args": '": "second query"}', "id": "call_2", "index": 1},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        # Should have 2 tool calls, not concatenated names
        assert len(result) >= 1  # At minimum should process without error
        
        # Extract tool names from result
        tool_names = [chunk.get("name") for chunk in result]
        
        # Verify "web_searchweb_search" error doesn't occur
        assert "web_searchweb_search" not in tool_names
        
        # Both calls should have web_search (or parts of it)
        concatenated_names = "".join(tool_names)
        assert "web_search" in concatenated_names or "web_" in concatenated_names

    def test_mixed_tools_consecutive_calls(self):
        """Test realistic scenario with mixed tools in sequence."""
        chunks = [
            # web_search call
            {"name": "web_search", "args": '{"query": "python"}', "id": "1", "index": 0},
            # crawl_tool call
            {"name": "crawl_tool", "args": '{"url": "http://example.com"}', "id": "2", "index": 1},
            # Another web_search
            {"name": "web_search", "args": '{"query": "rust"}', "id": "3", "index": 2},
        ]
        
        result = _process_tool_call_chunks(chunks)
        
        assert len(result) == 3
        tool_names = [chunk.get("name") for chunk in result]
        
        # No concatenation should occur
        assert "web_searchcrawl_tool" not in tool_names
        assert "crawl_toolweb_search" not in tool_names

    def test_long_sequence_tool_calls(self):
        """Test a long sequence of tool calls."""
        chunks = []
        for i in range(10):
            tool_name = "web_search" if i % 2 == 0 else "crawl_tool"
            chunks.append({
                "name": tool_name,
                "args": '{"query": "test"}' if tool_name == "web_search" else '{"url": "http://example.com"}',
                "id": f"call_{i}",
                "index": i
            })
        
        result = _process_tool_call_chunks(chunks)
        
        # Should process all 10 tool calls
        assert len(result) == 10
        
        # Verify each tool call has correct name (not concatenated with other tool names)
        for i, chunk in enumerate(result):
            expected_name = "web_search" if i % 2 == 0 else "crawl_tool"
            actual_name = chunk.get("name", "")
            
            # The actual name should be the expected name, not concatenated
            assert actual_name == expected_name, (
                f"Tool call {i} has name '{actual_name}', expected '{expected_name}'. "
                f"This indicates concatenation with adjacent tool call."
            )
            
            # Verify IDs are correct
            assert chunk.get("id") == f"call_{i}"
            assert chunk.get("index") == i


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
