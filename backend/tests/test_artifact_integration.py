"""Integration coverage for the artifact handle registry cycle (issue #4676).

Covers spec §14.4: capture from a tool result -> handle injected into model
context -> model references the handle in a later tool call -> resolution
rewrites it to the real reference at the tool-call boundary.
"""

import asyncio
import ipaddress
import json
import re
import sys
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import acp
import httpx
import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactResolutionMiddleware
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_output_budget_middleware import ToolOutputBudgetMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.agents.thread_state import ThreadState
from deerflow.community.crawl4ai import crawl4ai_client
from deerflow.community.crawl4ai import tools as crawl4ai_tools
from deerflow.config import paths as paths_module
from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.sandbox import sandbox_provider
from deerflow.sandbox.sandbox import CommandOutput, Sandbox
from deerflow.sandbox.tools import bash_tool
from deerflow.tools.artifact_registry import generate_handle
from deerflow.tools.builtins import view_image_tool
from deerflow.tools.builtins.invoke_acp_agent_tool import build_invoke_acp_agent_tool

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


_COMPACTION_SUMMARY = "The first request finished."


def _compacting_agent(model, selected_tool):
    return create_agent(
        model=model,
        tools=[selected_tool],
        middleware=[
            ToolOutputBudgetMiddleware(),
            ToolErrorHandlingMiddleware(),
            ArtifactCaptureMiddleware(),
            DurableContextMiddleware(),
            DeerFlowSummarizationMiddleware(
                model=FakeMessagesListChatModel(responses=[AIMessage(content=_COMPACTION_SUMMARY)]),
                trigger=("messages", 5),
                keep=("messages", 2),
                token_counter=len,
            ),
        ],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )


def _one_tool_model(name, args, call_id):
    return RecordingToolCallingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id, "type": "tool_call"}]),
            AIMessage(content="The first request finished."),
            AIMessage(content="Ready to continue."),
        ]
    )


async def _compact_and_check_artifacts(agent, model, config, context, expected):
    before = (await agent.aget_state(config)).values
    await agent.ainvoke({"messages": [HumanMessage(content="Continue with the next request.")]}, config, context=context)
    after = (await agent.aget_state(config)).values
    compacted_request = model.received[-1]
    assert after["summary_text"] == _COMPACTION_SUMMARY
    assert not any(isinstance(message, ToolMessage) for message in [*after["messages"], *compacted_request])
    assert [entry["real_ref"] for entry in before.get("tool_artifacts", [])] == expected
    assert after.get("tool_artifacts", []) == before.get("tool_artifacts", [])
    context_blocks = [message.content for message in compacted_request if message.additional_kwargs.get("durable_context_data")]
    for entry in after.get("tool_artifacts", []):
        assert any(f"`{entry['handle']}` -> {entry['artifact_type']}: {entry['display_name']} [available]" in block for block in context_blocks)
    return compacted_request


class ArtifactCycleModel(RecordingToolCallingModel):
    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ANN003
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


def _cycle_model() -> ArtifactCycleModel:
    return ArtifactCycleModel(
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


@pytest.mark.asyncio
async def test_missing_image_creates_no_artifact_before_or_after_compaction(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    missing_path = "/mnt/user-data/uploads/missing.png"
    model = _one_tool_model("view_image", {"image_path": missing_path}, "call_view")
    agent = _compacting_agent(model, view_image_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    await agent.ainvoke(
        {"messages": [HumanMessage(content="Open the uploaded image.")], "thread_data": {"uploads_path": str(uploads)}},
        config,
        context=context,
    )
    before = (await agent.aget_state(config)).values
    stored_result = next(message for message in before["messages"] if isinstance(message, ToolMessage))
    model_result = next(message for message in model.received[1] if isinstance(message, ToolMessage))
    error_text = f"Error: Image file not found: {missing_path}"
    assert stored_result.content == error_text
    assert stored_result.additional_kwargs[TOOL_META_KEY]["status"] == "error"
    assert json.loads(model_result.content) == {TOOL_META_KEY: {"status": "error", "source": "tool_return"}, "content": error_text}

    compacted_request = await _compact_and_check_artifacts(agent, model, config, context, [])
    assert not any("missing.png [available]" in message.content for message in compacted_request)


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False], ids=["completed-report", "failed-invocation"])
async def test_acp_report_artifacts_follow_invocation_status_through_compaction(tmp_path, monkeypatch, success):
    report_url = "https://files.example/report.pdf"
    report = f"Error: the report describes past failures. Download [{report_url}]"
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})))

    @asynccontextmanager
    async def spawn_agent_process(client, *_args, **_kwargs):
        async def prompt(session_id, **_kwargs):
            await client.session_update(session_id, acp.update_agent_message_text(report))
            if not success:
                raise RuntimeError("The ACP connection failed during the prompt.")
            return acp.schema.PromptResponse(stop_reason="end_turn")

        connection = SimpleNamespace(
            initialize=AsyncMock(),
            new_session=AsyncMock(return_value=acp.schema.NewSessionResponse(session_id="session-1")),
            prompt=prompt,
        )
        yield connection, SimpleNamespace(stderr=None, wait=asyncio.Event().wait)

    monkeypatch.setattr(acp, "spawn_agent_process", spawn_agent_process)
    selected_tool = build_invoke_acp_agent_tool({"test": ACPAgentConfig(command=sys.executable, description="Test ACP agent")})
    model = _one_tool_model("invoke_acp_agent", {"agent": "test", "prompt": "Generate a report."}, "call_acp")
    agent = _compacting_agent(model, selected_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    result = await agent.ainvoke({"messages": [HumanMessage(content="Generate the report.")]}, config, context=context)
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    if success:
        assert message.content == report
    expected_status = "success" if success else "error"
    assert message.status == expected_status
    await _compact_and_check_artifacts(agent, model, config, context, [report_url] if success else [])
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False], ids=["successful-page", "failed-fetch"])
async def test_crawl4ai_artifacts_follow_fetch_status_through_compaction(monkeypatch, success):
    report_url = "https://files.example/report.pdf"
    markdown = f"Error: the report describes past failures. Download [{report_url}]"
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url.path == "/md"
        return httpx.Response(200, json={"success": success, "markdown": markdown})

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(
        crawl4ai_client,
        "httpx",
        SimpleNamespace(AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs), TimeoutException=httpx.TimeoutException, RequestError=httpx.RequestError),
    )
    monkeypatch.setattr(crawl4ai_tools, "_get_tool_config", lambda _: {"network_isolation_confirmed": True})
    monkeypatch.setattr("deerflow.community.url_safety.resolve_host_addresses", lambda *args, **kwargs: [ipaddress.ip_address("93.184.216.34")])
    model = _one_tool_model("web_fetch", {"url": report_url}, "call_fetch")
    agent = _compacting_agent(model, crawl4ai_tools.web_fetch_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    result = await agent.ainvoke({"messages": [HumanMessage(content="Fetch the report.")]}, config, context=context)
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert requests == [{"url": report_url, "f": "fit"}]
    assert message.content == (markdown if success else f"Error: Crawl4AI reported failure for {report_url}")
    await _compact_and_check_artifacts(agent, model, config, context, [report_url] if success else [])
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == ("success" if success else "error")


@pytest.mark.asyncio
async def test_failed_bash_diagnostic_artifact_survives_compaction(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    missing_path = "/mnt/user-data/outputs/missing.pdf"
    stdout = f"Could not produce {missing_path}\n" + "diagnostic line\n" * 850 + "Exit Code: 2"
    sandbox = Mock(spec=Sandbox, id="fixture:diagnostics", execute_command=Mock(return_value=CommandOutput(stdout, 2)), supports_command_cancellation=False)
    provider = Mock(spec=sandbox_provider.SandboxProvider, uses_thread_data_mounts=True)
    provider.get.return_value = sandbox
    provider.get_scoped.return_value = sandbox
    monkeypatch.setattr(sandbox_provider, "_default_sandbox_provider", provider)
    model = _one_tool_model("bash", {"command": "run-report"}, "call_bash")
    agent = _compacting_agent(model, bash_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    result = await agent.ainvoke(
        {
            "messages": [HumanMessage(content="Run the report command.")],
            "thread_data": {"outputs_path": str(outputs)},
            "sandbox": {"sandbox_id": sandbox.id},
        },
        config,
        context=context,
    )
    sandbox.execute_command.assert_called_once()
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert message.status == "error"
    assert message.additional_kwargs[TOOL_META_KEY]["exit_code"] == 2
    assert missing_path in message.content
    (log,) = (outputs / ".tool-results").glob("*.log")
    assert log.read_text(encoding="utf-8") == stdout
    ref = f"/mnt/user-data/outputs/{log.relative_to(outputs).as_posix()}"
    await _compact_and_check_artifacts(agent, model, config, context, [ref])


@pytest.mark.parametrize(
    ("url", "closing_punctuation"),
    [
        ("https://files.example/report.pdf?token=part.csvX", "]"),
        ("https://files.example/report.pdf?token=abc&download=copy.csvX#page=2", "]"),
        ("https://files.example/report.pdf?token=abc", "]"),
        pytest.param("https://files.example/report.pdf?token=part.csvX#page=2", "\u3002\u201d\uff09", id="cjk-punctuation"),
        pytest.param("https://files.example/report.PdF?token=part.csvX#page=2", "]", id="mixed-case-extension"),
        pytest.param("https://files.example/report.pdf?label=(old)", "]", id="ascii-query-parentheses"),
        pytest.param("https://files.example/report.pdf#section[1]", "]", id="ascii-fragment-brackets"),
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


@pytest.mark.parametrize("directory_name", ["项目（归档）", "archive(old)", "archive[old]", "archive{old}", "archive(old[1])"])
def test_glob_directory_survives_capture_checkpoint_and_resolved_listing(tmp_path, directory_name):
    from deerflow.sandbox.tools import _format_glob_results

    real_ref = f"/mnt/user-data/workspace/{directory_name}"
    directory = tmp_path / directory_name
    directory.mkdir()
    (directory / "report.txt").write_text("report", encoding="utf-8")
    listed = []

    @tool("glob")
    def glob_directory(path: str, include_dirs: bool) -> str:
        """Find a directory using the sandbox's numbered glob result format."""
        assert path == "/mnt"
        assert include_dirs is True
        return _format_glob_results(path, [real_ref], truncated=False)

    @tool("ls")
    def list_directory(path: str) -> str:
        """List a directory by its sandbox path or artifact handle."""
        listed.append(path)
        return "\n".join(sorted(child.name for child in (tmp_path / path.rsplit("/", 1)[-1]).iterdir()))

    model = _cycle_model()
    model.responses[0].tool_calls[0].update(name="glob", args={"path": "/mnt", "include_dirs": True}, id="call_glob")
    model.responses[1].tool_calls[0].update(name="ls", id="call_ls")
    agent = create_agent(
        model=model,
        tools=[glob_directory, list_directory],
        middleware=[DurableContextMiddleware(), ArtifactCaptureMiddleware(), ArtifactResolutionMiddleware()],
        state_schema=ThreadState,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": THREAD_ID}}

    result = agent.invoke({"messages": [HumanMessage(content="find then list the archive directory")]}, config, context={"thread_id": THREAD_ID})

    assert listed == [real_ref]
    assert next(message.content for message in result["messages"] if getattr(message, "tool_call_id", None) == "call_ls") == "report.txt"
    found = next(entry for entry in result["tool_artifacts"] if entry["tool_call_id"] == "call_glob")
    assert found["real_ref"] == real_ref
    assert found["consumed_by"] == ["call_ls"]
    persisted = next(entry for entry in agent.get_state(config).values["tool_artifacts"] if entry["tool_call_id"] == "call_glob")
    assert persisted["real_ref"] == real_ref


@pytest.mark.parametrize(("opener", "closer"), [("「", "」"), ("『", "』")])
def test_corner_quoted_artifact_resolves_after_source_message_is_gone(tmp_path, opener, closer):
    filename = "季度 报告.txt"
    (tmp_path / filename).write_text("report contents", encoding="utf-8")
    real_ref = f"/mnt/user-data/outputs/{filename}"
    runtime = SimpleNamespace(context={"thread_id": THREAD_ID})
    source = ToolMessage(id="corner-report", content=f"已生成{opener}{real_ref}{closer}。", tool_call_id="call_make", name="make_file")
    update = ArtifactCaptureMiddleware().before_model({"messages": [source]}, runtime)
    assert update is not None
    # Restore only the persisted registry: the tool result may have been compacted away.
    registry = json.loads(json.dumps(update["tool_artifacts"]))
    assert len(registry) == 1
    request = ToolCallRequest(
        tool_call={"name": "read_file", "args": {"path": registry[0]["handle"]}, "id": "call_read", "type": "tool_call"},
        tool=None,
        state={"messages": [], "tool_artifacts": registry},
        runtime=runtime,
    )
    reads = []

    def read_report(resolved):
        path = resolved.tool_call["args"]["path"]
        reads.append(path)
        relative = PurePosixPath(path).relative_to("/mnt/user-data/outputs")
        return ToolMessage(content=(tmp_path / str(relative)).read_text(encoding="utf-8"), tool_call_id="call_read")

    result = ArtifactResolutionMiddleware().wrap_tool_call(request, read_report)

    assert reads == [real_ref]
    assert result.content == "report contents"
    assert registry[0]["display_name"] == filename
