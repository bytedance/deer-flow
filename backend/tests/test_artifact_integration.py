"""Integration coverage for the artifact handle registry cycle (issue #4676).

Covers spec §14.4: capture from a tool result -> handle injected into model
context -> model references the handle in a later tool call -> resolution
rewrites it to the real reference at the tool-call boundary.
"""

from typing import Any

from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.thread_state import ThreadState
from deerflow.tools.artifact_registry import generate_handle

THREAD_ID = "artifact-cycle-thread"
REAL_REF = "/mnt/user-data/outputs/report.md"
FRESH_HANDLE = generate_handle(THREAD_ID, "call_make", 0)

seen_read_args: list[dict] = []


class RecordingToolCallingModel(FakeToolCallingModel):
    """FakeToolCallingModel that records the messages sent to each model call."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        object.__setattr__(self, "received", [])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
        self.received.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


@tool("make_file", parse_docstring=True)
def make_file(name: str) -> str:
    """Create a report file.

    Args:
        name: file name to create.
    """
    return f"Saved {REAL_REF} successfully"


@tool("read_file", parse_docstring=True)
def spy_read_file(path: str) -> str:
    """Read a file.

    Args:
        path: path of the file to read.
    """
    seen_read_args.append({"path": path})
    return f"contents of {path}"


def _cycle_model() -> RecordingToolCallingModel:
    return RecordingToolCallingModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "make_file", "args": {"name": "report.md"}, "id": "call_make", "type": "tool_call"}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"name": "read_file", "args": {"path": FRESH_HANDLE}, "id": "call_read", "type": "tool_call"}],
            ),
            AIMessage(content="done"),
        ]
    )


def _build_agent(model: FakeToolCallingModel):
    return create_agent(
        model=model,
        tools=[make_file, spy_read_file],
        middleware=[
            DurableContextMiddleware(),
            ArtifactCaptureMiddleware(),
            ArtifactResolutionMiddleware(),
        ],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )


def test_full_capture_inject_resolve_cycle():
    seen_read_args.clear()
    agent = _build_agent(_cycle_model())
    config = {"configurable": {"thread_id": THREAD_ID}}

    result = agent.invoke({"messages": [HumanMessage(content="make then read")]}, config, context={"thread_id": THREAD_ID})

    assert seen_read_args == [{"path": REAL_REF}], f"handle was not resolved at the tool boundary: {seen_read_args}"

    entries = {entry["handle"]: entry for entry in result["tool_artifacts"]}
    assert FRESH_HANDLE in entries
    assert entries[FRESH_HANDLE]["real_ref"] == REAL_REF
    assert entries[FRESH_HANDLE]["consumed_by"] == ["call_read"]


def test_handle_projected_into_model_context():
    seen_read_args.clear()
    model = _cycle_model()
    agent = _build_agent(model)
    config = {"configurable": {"thread_id": THREAD_ID}}

    agent.invoke({"messages": [HumanMessage(content="make then read")]}, config, context={"thread_id": THREAD_ID})

    # Round 3 is the request after both capture and consumption happened.
    round3 = model.received[-1]
    durable_blocks = [
        message.content
        for message in round3
        if getattr(message, "additional_kwargs", {}).get("durable_context_data")
    ]
    assert any(FRESH_HANDLE in content for content in durable_blocks), (
        "captured handle never reached the model-facing durable context block"
    )
