# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch, MagicMock

from src.prompt_enhancer.graph.builder import build_graph
from src.prompt_enhancer.graph.state import PromptEnhancerState


class TestBuildGraph:
    """Test cases for build_graph function."""

    @patch("src.prompt_enhancer.graph.builder.StateGraph")
    def test_build_graph_structure(self, mock_state_graph):
        """Test that build_graph creates the correct graph structure."""
        mock_builder = MagicMock()
        mock_compiled_graph = MagicMock()

        mock_state_graph.return_value = mock_builder
        mock_builder.compile.return_value = mock_compiled_graph

        result = build_graph()

        # Verify StateGraph was created with correct state type
        mock_state_graph.assert_called_once_with(PromptEnhancerState)

        # Verify entry point was set
        mock_builder.set_entry_point.assert_called_once_with("enhancer")

        # Verify finish point was set
        mock_builder.set_finish_point.assert_called_once_with("enhancer")

        # Verify graph was compiled
        mock_builder.compile.assert_called_once()

        # Verify return value
        assert result == mock_compiled_graph

    @patch("src.prompt_enhancer.graph.builder.StateGraph")
    @patch("src.prompt_enhancer.graph.builder.prompt_enhancer_node")
    def test_build_graph_node_function(self, mock_enhancer_node, mock_state_graph):
        """Test that the correct node function is added to the graph."""
        mock_builder = MagicMock()
        mock_compiled_graph = MagicMock()

        mock_state_graph.return_value = mock_builder
        mock_builder.compile.return_value = mock_compiled_graph

        build_graph()

        # Verify the correct node function was added
        mock_builder.add_node.assert_called_once_with("enhancer", mock_enhancer_node)

    def test_build_graph_returns_compiled_graph(self):
        """Test that build_graph returns a compiled graph object."""
        with patch("src.prompt_enhancer.graph.builder.StateGraph") as mock_state_graph:
            mock_builder = MagicMock()
            mock_compiled_graph = MagicMock()

            mock_state_graph.return_value = mock_builder
            mock_builder.compile.return_value = mock_compiled_graph

            result = build_graph()

            assert result is mock_compiled_graph

    @patch("src.prompt_enhancer.graph.builder.StateGraph")
    def test_build_graph_call_sequence(self, mock_state_graph):
        """Test that build_graph calls methods in the correct sequence."""
        mock_builder = MagicMock()
        mock_compiled_graph = MagicMock()

        mock_state_graph.return_value = mock_builder
        mock_builder.compile.return_value = mock_compiled_graph

        # Track call order
        call_order = []

        def track_add_node(*args, **kwargs):
            call_order.append("add_node")

        def track_set_entry_point(*args, **kwargs):
            call_order.append("set_entry_point")

        def track_set_finish_point(*args, **kwargs):
            call_order.append("set_finish_point")

        def track_compile(*args, **kwargs):
            call_order.append("compile")
            return mock_compiled_graph

        mock_builder.add_node.side_effect = track_add_node
        mock_builder.set_entry_point.side_effect = track_set_entry_point
        mock_builder.set_finish_point.side_effect = track_set_finish_point
        mock_builder.compile.side_effect = track_compile

        build_graph()

        # Verify the correct call sequence
        expected_order = ["add_node", "set_entry_point", "set_finish_point", "compile"]
        assert call_order == expected_order

    def test_build_graph_integration(self):
        """Integration test to verify the graph can be built without mocking."""
        # This test verifies that all imports and dependencies are correct
        try:
            graph = build_graph()
            assert graph is not None
            # The graph should be a compiled LangGraph object
            assert hasattr(graph, "invoke") or hasattr(graph, "stream")
        except ImportError as e:
            pytest.skip(f"Skipping integration test due to missing dependencies: {e}")
        except Exception as e:
            # If there are configuration issues (like missing LLM config),
            # we still consider the test successful if the graph structure is built
            if "LLM" in str(e) or "configuration" in str(e).lower():
                pytest.skip(
                    f"Skipping integration test due to configuration issues: {e}"
                )
            else:
                raise

    @patch("src.prompt_enhancer.graph.builder.StateGraph")
    def test_build_graph_single_node_workflow(self, mock_state_graph):
        """Test that the graph is configured as a single-node workflow."""
        mock_builder = MagicMock()
        mock_compiled_graph = MagicMock()

        mock_state_graph.return_value = mock_builder
        mock_builder.compile.return_value = mock_compiled_graph

        build_graph()

        # Verify only one node is added
        assert mock_builder.add_node.call_count == 1

        # Verify entry and finish points are the same node
        mock_builder.set_entry_point.assert_called_once_with("enhancer")
        mock_builder.set_finish_point.assert_called_once_with("enhancer")

    @patch("src.prompt_enhancer.graph.builder.StateGraph")
    def test_build_graph_state_type(self, mock_state_graph):
        """Test that the graph is initialized with the correct state type."""
        mock_builder = MagicMock()
        mock_compiled_graph = MagicMock()

        mock_state_graph.return_value = mock_builder
        mock_builder.compile.return_value = mock_compiled_graph

        build_graph()

        # Verify StateGraph was initialized with PromptEnhancerState
        args, kwargs = mock_state_graph.call_args
        assert args[0] == PromptEnhancerState
