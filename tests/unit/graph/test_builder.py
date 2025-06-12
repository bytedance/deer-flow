# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import MagicMock, patch
import importlib
import sys

import src.graph.builder as builder_mod


@pytest.fixture
def mock_state():
    class Step:
        def __init__(self, execution_res=None, step_type=None):
            self.execution_res = execution_res
            self.step_type = step_type

    class Plan:
        def __init__(self, steps):
            self.steps = steps

    return {
        "Step": Step,
        "Plan": Plan,
    }


def test_continue_to_running_research_team_no_plan(mock_state):
    state = {"current_plan": None}
    assert builder_mod.continue_to_running_research_team(state) == "planner"


def test_continue_to_running_research_team_no_steps(mock_state):
    state = {"current_plan": mock_state["Plan"](steps=[])}
    assert builder_mod.continue_to_running_research_team(state) == "planner"


def test_continue_to_running_research_team_all_executed(mock_state):
    Step = mock_state["Step"]
    Plan = mock_state["Plan"]
    steps = [Step(execution_res=True), Step(execution_res=True)]
    state = {"current_plan": Plan(steps=steps)}
    assert builder_mod.continue_to_running_research_team(state) == "planner"


def test_continue_to_running_research_team_next_researcher(mock_state):
    Step = mock_state["Step"]
    Plan = mock_state["Plan"]
    steps = [
        Step(execution_res=True),
        Step(execution_res=None, step_type=builder_mod.StepType.RESEARCH),
    ]
    state = {"current_plan": Plan(steps=steps)}
    assert builder_mod.continue_to_running_research_team(state) == "researcher"


def test_continue_to_running_research_team_next_coder(mock_state):
    Step = mock_state["Step"]
    Plan = mock_state["Plan"]
    steps = [
        Step(execution_res=True),
        Step(execution_res=None, step_type=builder_mod.StepType.PROCESSING),
    ]
    state = {"current_plan": Plan(steps=steps)}
    assert builder_mod.continue_to_running_research_team(state) == "coder"


def test_continue_to_running_research_team_default_planner(mock_state):
    Step = mock_state["Step"]
    Plan = mock_state["Plan"]
    steps = [Step(execution_res=True), Step(execution_res=None, step_type=None)]
    state = {"current_plan": Plan(steps=steps)}
    assert builder_mod.continue_to_running_research_team(state) == "planner"


@patch("src.graph.builder.StateGraph")
def test_build_base_graph_adds_nodes_and_edges(MockStateGraph):
    mock_builder = MagicMock()
    MockStateGraph.return_value = mock_builder

    builder_mod._build_base_graph()

    # Check that all nodes and edges are added
    assert mock_builder.add_edge.call_count >= 2
    assert mock_builder.add_node.call_count >= 8
    mock_builder.add_conditional_edges.assert_called_once()


@patch("src.graph.builder._build_base_graph")
@patch("src.graph.builder.MemorySaver")
def test_build_graph_with_memory_uses_memory(MockMemorySaver, mock_build_base_graph):
    mock_builder = MagicMock()
    mock_build_base_graph.return_value = mock_builder
    mock_memory = MagicMock()
    MockMemorySaver.return_value = mock_memory

    builder_mod.build_graph_with_memory()

    mock_builder.compile.assert_called_once_with(checkpointer=mock_memory)


@patch("src.graph.builder._build_base_graph")
def test_build_graph_without_memory(mock_build_base_graph):
    mock_builder = MagicMock()
    mock_build_base_graph.return_value = mock_builder

    builder_mod.build_graph()

    mock_builder.compile.assert_called_once_with()


def test_graph_is_compiled():
    # The graph object should be the result of build_graph()
    with patch("src.graph.builder._build_base_graph") as mock_base:
        mock_builder = MagicMock()
        mock_base.return_value = mock_builder
        mock_builder.compile.return_value = "compiled_graph"
        # reload the module to re-run the graph assignment
        importlib.reload(sys.modules["src.graph.builder"])
        assert builder_mod.graph is not None
