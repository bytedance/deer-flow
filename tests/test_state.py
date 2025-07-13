# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import sys
import os
from typing import Annotated

# Import MessagesState directly from langgraph rather than through our application
from langgraph.graph import MessagesState


# Create stub versions of Plan/Step/StepType to avoid dependencies
class StepType:
    RESEARCH = "research"
    PROCESSING = "processing"


class Step:
    def __init__(self, need_search, title, description, step_type):
        self.need_search = need_search
        self.title = title
        self.description = description
        self.step_type = step_type


class Plan:
    def __init__(self, locale, has_enough_context, thought, title, steps):
        self.locale = locale
        self.has_enough_context = has_enough_context
        self.thought = thought
        self.title = title
        self.steps = steps


# Import the actual State class by loading the module directly
# This avoids the cascade of imports that would normally happen
def load_state_class():
    # Get the absolute path to the types.py file
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    types_path = os.path.join(src_dir, "graph", "types.py")

    # Create a namespace for the module
    import types

    module_name = "src.graph.types_direct"
    spec = types.ModuleType(module_name)

    # Add the module to sys.modules to avoid import loops
    sys.modules[module_name] = spec

    # Set up the namespace with required imports
    spec.__dict__["operator"] = __import__("operator")
    spec.__dict__["Annotated"] = Annotated
    spec.__dict__["MessagesState"] = MessagesState
    spec.__dict__["Plan"] = Plan

    # Execute the module code
    with open(types_path, "r") as f:
        module_code = f.read()

    exec(module_code, spec.__dict__)

    # Return the State class
    return spec.State


# Load the actual State class
State = load_state_class()


def test_state_initialization():
    """Test that State class has correct default attribute definitions."""
    # Test that the class has the expected attribute definitions
    assert State.locale == "en-US"
    assert State.observations == []
    assert State.plan_iterations == 0
    assert State.current_plan is None
    assert State.final_report == ""
    assert State.auto_accepted_plan is False
    assert State.enable_background_investigation is True
    assert State.background_investigation_results is None

    # Verify state initialization
    state = State(messages=[])
    assert "messages" in state

    # Without explicitly passing attributes, they're not in the state
    assert "locale" not in state
    assert "observations" not in state


def test_state_with_custom_values():
    """Test that State can be initialized with custom values."""
    test_step = Step(
        need_search=True,
        title="Test Step",
        description="Step description",
        step_type=StepType.RESEARCH,
    )

    test_plan = Plan(
        locale="en-US",
        has_enough_context=False,
        thought="Test thought",
        title="Test Plan",
        steps=[test_step],
    )

    # Initialize state with custom values and required messages field
    state = State(
        messages=[],
        locale="fr-FR",
        observations=["Observation 1"],
        plan_iterations=2,
        current_plan=test_plan,
        final_report="Test report",
        auto_accepted_plan=True,
        enable_background_investigation=False,
        background_investigation_results="Test results",
    )

    # Access state keys - these are explicitly initialized
    assert state["locale"] == "fr-FR"
    assert state["observations"] == ["Observation 1"]
    assert state["plan_iterations"] == 2
    assert state["current_plan"].title == "Test Plan"
    assert state["current_plan"].thought == "Test thought"
    assert len(state["current_plan"].steps) == 1
    assert state["current_plan"].steps[0].title == "Test Step"
    assert state["final_report"] == "Test report"
    assert state["auto_accepted_plan"] is True
    assert state["enable_background_investigation"] is False
    assert state["background_investigation_results"] == "Test results"
