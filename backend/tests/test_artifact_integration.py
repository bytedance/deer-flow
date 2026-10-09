"""Integration coverage for the artifact handle registry cycle (issue #4676).

Covers spec §14.4: capture from a tool result -> handle injected into model
context -> model references the handle in a later tool call -> resolution
rewrites it to the real reference at the tool-call boundary.
"""

import re
from typing import Any

import httpx
import pytest
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
        if self.i == 1:
            data = next(m.content for m in messages if m.additional_kwargs.get("durable_context_data"))
            handle = re.search(r"art_[0-9a-f]{8}", data).group()
            self.responses[1].tool_calls[0]["args"]["path"] = handle
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
    made = next(e for e in entries.values() if e["tool_call_id"] == "call_make")
    assert made["real_ref"] == REAL_REF
    assert made["consumed_by"] == ["call_read"]


def test_handle_projected_into_model_context():
    seen_read_args.clear()
    model = _cycle_model()
    agent = _build_agent(model)
    config = {"configurable": {"thread_id": THREAD_ID}}

    result = agent.invoke({"messages": [HumanMessage(content="make then read")]}, config, context={"thread_id": THREAD_ID})

    # Round 3 is the request after both capture and consumption happened.
    round3 = model.received[-1]
    durable_blocks = [message.content for message in round3 if getattr(message, "additional_kwargs", {}).get("durable_context_data")]
    handle = next(e["handle"] for e in result["tool_artifacts"] if e["tool_call_id"] == "call_make")
    assert any(handle in content for content in durable_blocks), "captured handle never reached the model-facing durable context block"


@pytest.mark.parametrize(
    ("url", "closing_punctuation"),
    [
        ("https://files.example/report.pdf?token=part.csvX", "]"),
        ("https://files.example/report.pdf?token=abc&download=copy.csvX#page=2", "]"),
        ("https://files.example/report.pdf?token=abc", "]"),
        pytest.param("https://files.example/report.pdf?token=part.csvX#page=2", "\u3002\u201d\uff09", id="cjk-punctuation"),
        pytest.param("https://files.example/report.PdF?token=part.csvX#page=2", "]", id="mixed-case-extension"),
    ],
)
def test_remote_url_survives_capture_checkpoint_and_resolved_download(url, closing_punctuation):
    """Exercise the real agent graph with a fake model and offline HTTP transport."""
    downloaded = []

    @tool("make_file")
    def remote_report(name: str) -> str:
        """Create a remotely hosted report."""
        return f"Download [{url}{closing_punctuation}"

    def serve_report(request: httpx.Request) -> httpx.Response:
        downloaded.append(request.url)
        return httpx.Response(200 if request.url.query == httpx.URL(url).query else 403, content=b"report")

    @tool("read_file")
    def download_report(path: str) -> str:
        """Download a report by its URL or artifact handle."""
        assert path == url
        with httpx.Client(transport=httpx.MockTransport(serve_report)) as client:
            response = client.get(path)
            response.raise_for_status()
        return response.text

    agent = create_agent(
        model=_cycle_model(),
        tools=[remote_report, download_report],
        middleware=[DurableContextMiddleware(), ArtifactCaptureMiddleware(), ArtifactResolutionMiddleware()],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": THREAD_ID}}

    result = agent.invoke({"messages": [HumanMessage(content="make then download")]}, config, context={"thread_id": THREAD_ID})

    assert downloaded == [httpx.URL(url)]
    made = next(entry for entry in result["tool_artifacts"] if entry["tool_call_id"] == "call_make")
    assert made["real_ref"] == url
    assert made["consumed_by"] == ["call_read"]
    persisted = next(entry for entry in agent.get_state(config).values["tool_artifacts"] if entry["tool_call_id"] == "call_make")
    assert persisted["real_ref"] == url
