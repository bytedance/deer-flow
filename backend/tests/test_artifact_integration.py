"""Integration coverage for the artifact handle registry cycle (issue #4676).

Covers spec §14.4: capture from a tool result -> handle injected into model
context -> model references the handle in a later tool call -> resolution
rewrites it to the real reference at the tool-call boundary.
"""

import ipaddress
import json
import re
import sys
from pathlib import PurePosixPath
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import httpx
import pytest
from _agent_e2e_helpers import FakeToolCallingModel
from deerflow_extension_api import ModelTool, PluginContribution, PluginToolResult
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt.tool_node import ToolCallRequest

from deerflow.agents.middlewares.artifact_capture_middleware import ArtifactCaptureMiddleware
from deerflow.agents.middlewares.artifact_resolution_middleware import ArtifactBlobRestoreMiddleware, ArtifactResolutionMiddleware
from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.middlewares.tool_error_handling_middleware import ToolErrorHandlingMiddleware
from deerflow.agents.middlewares.tool_output_budget_middleware import TOOL_OUTPUT_BLOB_KEY, ToolOutputBudgetMiddleware
from deerflow.agents.middlewares.tool_progress_middleware import ToolProgressMiddleware
from deerflow.agents.middlewares.tool_result_meta import TOOL_META_KEY
from deerflow.agents.thread_state import ThreadState
from deerflow.community.crawl4ai import crawl4ai_client
from deerflow.community.crawl4ai import tools as crawl4ai_tools
from deerflow.community.opensandbox.sandbox import OpenSandboxSandbox
from deerflow.config import paths as paths_module
from deerflow.config.acp_config import ACPAgentConfig
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.tool_output_config import ToolOutputConfig
from deerflow.extensions.plugin_tools import build_plugin_tools
from deerflow.extensions.registry import ExtensionRegistry
from deerflow.sandbox import sandbox_provider
from deerflow.sandbox.sandbox import CommandOutput, Sandbox
from deerflow.sandbox.tools import bash_tool, read_file_tool
from deerflow.storage.backends.local_fs.local_fs_store import LocalFsBlobStore
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
_SUCCESS_META = {"status": "success", "source": "tool_return", "error_type": None, "recoverable_by_model": True, "recommended_next_action": "continue"}


def _compacting_agent(model, *tools, checkpointer=None, output_budget=None):
    return create_agent(
        model=model,
        tools=tools,
        middleware=[
            output_budget or ToolOutputBudgetMiddleware(),
            ArtifactResolutionMiddleware(),
            ToolErrorHandlingMiddleware(),
            ArtifactBlobRestoreMiddleware(),
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
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
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


_PLUGIN_REPORT_URL = "https://files.example/report.pdf"
_PLUGIN_REPORT = "Error: the report summarizes past validation failures."
_PLUGIN_REPORT_ARTIFACT = {"structured_content": {"file": _PLUGIN_REPORT_URL}}
_PLUGIN_DIAGNOSTIC = "/mnt/user-data/outputs/diagnostic.log"


def _report_plugin_tool(handler):
    declaration = ModelTool("report", "Generate a report.", {"type": "object"}, handler, response_format="content_and_artifact")
    registry = ExtensionRegistry()
    with registry.attributed_to("test"):
        registry.plugin(PluginContribution(namespace="test.reports", title="Reports", enabled=True, tools=(declaration,)))
    (selected_tool,) = build_plugin_tools(registry.build())
    return selected_tool


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome,expected_error,expected_refs",
    [
        pytest.param(PluginToolResult("The report is ready.", _PLUGIN_REPORT_ARTIFACT), None, [_PLUGIN_REPORT_URL], id="legacy-report"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT), "unknown", [_PLUGIN_REPORT_URL], id="legacy-report-error-prefix"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, {"resource_links": [{"uri": _PLUGIN_REPORT_URL}]}), "unknown", [_PLUGIN_REPORT_URL], id="legacy-resource-link-error-prefix"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT, status="success"), None, [_PLUGIN_REPORT_URL], id="explicit-report"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT | {"deerflow_http_response": {"status_code": 200}}, status="success"), None, [_PLUGIN_REPORT_URL], id="http-200"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT | {"deerflow_http_response": {"status_code": 404}}, status="success"), "not_found", [], id="http-404"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT | {"deerflow_http_response": {"status_code": 404}}), "not_found", [], id="legacy-http-404"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, _PLUGIN_REPORT_ARTIFACT | {"deerflow_http_response": {"status_code": 400}}), "unknown", [], id="legacy-http-400"),
        pytest.param(PluginToolResult(_PLUGIN_REPORT, status="success"), None, [], id="text-only-success"),
        pytest.param(PluginToolResult("Could not generate the report.", _PLUGIN_REPORT_ARTIFACT, status="error"), "unknown", [], id="explicit-error"),
        pytest.param(PluginToolResult(f"Error: Could not generate {_PLUGIN_REPORT_URL}"), "unknown", [], id="legacy-text-error"),
        pytest.param(PluginToolResult(f"Error: Could not generate {_PLUGIN_REPORT_URL}", {"structured_content": {"file": _PLUGIN_DIAGNOSTIC}}), "unknown", [_PLUGIN_DIAGNOSTIC], id="legacy-text-error-with-diagnostic-file"),
        pytest.param(PluginToolResult(json.dumps({"error": f"Could not generate {_PLUGIN_REPORT_URL}"})), "unknown", [], id="legacy-json-error"),
        pytest.param(PluginToolResult(json.dumps({"error": f"Could not generate {_PLUGIN_REPORT_URL}"}), {}), "unknown", [], id="legacy-json-error-empty-artifact"),
        pytest.param(PluginToolResult(json.dumps({"error": f"Could not generate {_PLUGIN_REPORT_URL}"}), {"request_id": "req-1"}), "unknown", [], id="legacy-json-error-diagnostic"),
        pytest.param(PluginToolResult(json.dumps({"error": "Report generation failed."}), _PLUGIN_REPORT_ARTIFACT), "unknown", [_PLUGIN_REPORT_URL], id="legacy-json-error-with-file-reference"),
        pytest.param(PluginToolResult("Error: Report generation failed.", {"structured_content": {"request_id": "req-1"}}), "unknown", [], id="legacy-text-error-with-diagnostic"),
        pytest.param(ToolException(f"Error: Could not generate {_PLUGIN_REPORT_URL}"), "unknown", [], id="tool-exception"),
    ],
)
async def test_plugin_report_artifacts_follow_invocation_status_through_compaction(outcome, expected_error, expected_refs):
    async def handler(payload, context):
        if isinstance(outcome, ToolException):
            raise outcome
        return outcome

    selected_tool = _report_plugin_tool(handler)
    model = _one_tool_model(selected_tool.name, {}, "call_plugin_report")
    agent = _compacting_agent(model, selected_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    await agent.ainvoke({"messages": [HumanMessage(content="Generate the report.")]}, config, context=context)
    before = (await agent.aget_state(config)).values
    message = next(message for message in before["messages"] if isinstance(message, ToolMessage))
    model_result = next(message for message in model.received[1] if isinstance(message, ToolMessage))
    success = expected_error is None
    expected_status = "success" if success else "error"
    meta = message.additional_kwargs[TOOL_META_KEY]
    assert meta["status"] == expected_status
    assert meta.get("error_type") == expected_error
    assert json.loads(model_result.content) == {TOOL_META_KEY: {"status": expected_status, "source": "tool_return"}, "content": message.content}
    if isinstance(outcome, ToolException):
        assert message.status == "error"
        assert message.artifact is None
    else:
        assert message.content == outcome.content
        assert message.artifact == outcome.artifact
        assert message.status == (outcome.status or "success")
    compacted_request = await _compact_and_check_artifacts(agent, model, config, context, expected_refs)
    if _PLUGIN_REPORT_URL not in expected_refs:
        assert not any("report.pdf [available]" in item.content for item in compacted_request)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_first", [False, True], ids=["duplicate-success", "recovery-after-errors"])
async def test_plugin_success_participates_in_tool_progress(failed_first):
    report = PluginToolResult("The completed report contains verified financial projections for each region and department.", status="success")
    failure = PluginToolResult("Could not generate the report.", status="error")
    outcomes = iter([failure] * 3 + [report] if failed_first else [report] * 4)

    async def handler(payload, context):
        return next(outcomes)

    selected_tool = _report_plugin_tool(handler)
    model = RecordingToolCallingModel(
        responses=[
            *(AIMessage(content="", tool_calls=[{"name": selected_tool.name, "args": {}, "id": f"call_{index}", "type": "tool_call"}]) for index in range(4)),
            AIMessage(content="Done."),
        ]
    )
    progress = ToolProgressMiddleware()
    agent = create_agent(model=model, tools=[selected_tool], middleware=[progress, ToolErrorHandlingMiddleware()], state_schema=ThreadState)
    await agent.ainvoke({"messages": [HumanMessage(content="Generate the report.")]}, context={"thread_id": THREAD_ID})

    phase = progress._phase_states.get(THREAD_ID, {}).get(selected_tool.name)
    if failed_first:
        assert any("[PROGRESS HINT]" in str(message.content) for message in model.received[3])
        assert phase is not None and phase.phase == "active" and phase.consecutive_problems == 0
    else:
        assert any("The tool is returning duplicate results." in str(message.content) for message in model.received[-1])
        assert phase is not None and phase.phase == "warned"


_ACP_REPORT_AGENT = """\
import asyncio
import sys

import acp
from acp.schema import InitializeResponse, NewSessionResponse, PromptResponse


class ReportAgent:
    def on_connect(self, conn):
        self.conn = conn

    async def initialize(self, protocol_version, **kwargs):
        return InitializeResponse(protocol_version=protocol_version)

    async def new_session(self, **kwargs):
        return NewSessionResponse(session_id="session-1")

    async def prompt(self, session_id, **kwargs):
        stop_reason, report = sys.argv[1:]
        await self.conn.session_update(session_id=session_id, update=acp.update_agent_message_text(report))
        if stop_reason == "request_error":
            raise RuntimeError("The ACP prompt failed.")
        return PromptResponse(stop_reason=stop_reason)


asyncio.run(acp.run_agent(ReportAgent()))
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_reason", ["end_turn", "refusal", "cancelled", "max_tokens", "max_turn_requests", "request_error"])
async def test_acp_report_artifacts_follow_invocation_status_through_compaction(tmp_path, monkeypatch, stop_reason):
    report_url = "https://files.example/report.pdf"
    report = f"Error: the report describes past failures. Download [{report_url}]"
    monkeypatch.setattr(paths_module, "get_paths", lambda: paths_module.Paths(base_dir=tmp_path))
    monkeypatch.setattr(ExtensionsConfig, "from_file", classmethod(lambda cls: ExtensionsConfig(mcp_servers={}, skills={})))

    agent_config = ACPAgentConfig(
        command=sys.executable,
        args=["-c", _ACP_REPORT_AGENT, stop_reason, report],
        description="Test ACP agent",
        timeout_seconds=15,
    )
    selected_tool = build_invoke_acp_agent_tool({"test": agent_config})
    model = _one_tool_model("invoke_acp_agent", {"agent": "test", "prompt": "Generate a report."}, "call_acp")
    agent = _compacting_agent(model, selected_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}

    result = await agent.ainvoke({"messages": [HumanMessage(content="Generate the report.")]}, config, context=context)
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    success = stop_reason == "end_turn"
    compacted_request = await _compact_and_check_artifacts(agent, model, config, context, [report_url] if success else [])
    if success:
        assert message.content == report
        assert message.additional_kwargs[TOOL_META_KEY] == _SUCCESS_META
    else:
        assert not any("report.pdf [available]" in item.content for item in compacted_request)
        if stop_reason != "request_error":
            assert stop_reason in message.content
            assert report in message.content
    expected_status = "success" if success else "error"
    assert message.status == expected_status
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
    if success:
        assert message.additional_kwargs[TOOL_META_KEY] == _SUCCESS_META


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["opensandbox", "e2b", "aio", "tenki", "boxlite", "boxd"])
async def test_sandbox_success_keeps_report_artifact_through_compaction(tmp_path, monkeypatch, provider_name):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    stdout = f"Error: the report lists historical failures. Saved to {REAL_REF}"

    def run(command, **kwargs):
        (outputs / "report.md").write_text("Historical failures", encoding="utf-8")
        if provider_name == "e2b":
            return e2b.CommandResult(stdout=stdout, stderr="", exit_code=0, error=None)
        if provider_name == "aio":
            return SimpleNamespace(data=SimpleNamespace(output=stdout, exit_code=0, status="completed"))
        if provider_name == "tenki":
            return SimpleNamespace(stdout_text=stdout, stderr_text="", exit_code=0, timed_out=False)
        if provider_name in {"boxlite", "boxd"}:
            return SimpleNamespace(stdout=stdout, stderr="", exit_code=0)
        return SimpleNamespace(exit_code=0, logs=SimpleNamespace(stdout=[SimpleNamespace(text=stdout)], stderr=[]))

    def read_mounted_report(path):
        sdk_paths = {"e2b": "/home/user/outputs/report.md", "tenki": "/home/tenki/outputs/report.md"}
        assert path == sdk_paths.get(provider_name, REAL_REF)
        return (outputs / "report.md").read_text(encoding="utf-8")

    commands = SimpleNamespace(run=run)
    if provider_name == "e2b":
        e2b = pytest.importorskip("e2b")
        from deerflow.community.e2b_sandbox.e2b_sandbox import E2BSandbox

        sandbox = E2BSandbox("e2b:report", SimpleNamespace(commands=commands, files=SimpleNamespace(read=read_mounted_report)))
    elif provider_name == "aio":
        from deerflow.community.aio_sandbox import aio_sandbox

        def read_aio_report(*, file):
            return SimpleNamespace(data=SimpleNamespace(content=read_mounted_report(file)))

        sdk = SimpleNamespace(shell=SimpleNamespace(exec_command=run), file=SimpleNamespace(read_file=read_aio_report))
        monkeypatch.setattr(aio_sandbox, "AioSandboxClient", lambda **kwargs: sdk)
        sandbox = aio_sandbox.AioSandbox("aio:report", "http://localhost:8080", home_dir="/home/user")
    elif provider_name == "tenki":
        from deerflow.community.tenki.sandbox import TenkiSandbox

        def tenki_exec(*argv, **kwargs):
            assert argv[:2] == ("sh", "-lc")
            return run(argv[-1], **kwargs)

        sdk = SimpleNamespace(exec=tenki_exec, fs=SimpleNamespace(read_text=read_mounted_report))
        sandbox = TenkiSandbox("tenki:report", sdk)
    elif provider_name == "boxlite":
        from deerflow.community.boxlite.box import BoxliteBox

        def boxlite_exec(*argv, **kwargs):
            if argv[0] == "cat":
                return SimpleNamespace(stdout=read_mounted_report(argv[-1]), stderr="", exit_code=0)
            assert argv[:2] == ("sh", "-lc")
            return run(argv[-1], **kwargs)

        sandbox = BoxliteBox("boxlite:report", SimpleNamespace(exec=boxlite_exec), run=lambda result, **kwargs: result)
    elif provider_name == "boxd":
        from deerflow.community.boxd_sandbox.boxd_sandbox import BoxdSandbox

        def boxd_exec(machine_id, argv, **kwargs):
            assert machine_id == "report-machine"
            if argv[0] == "head":
                assert kwargs["encoding"] == "buffer"
                return SimpleNamespace(stdout=read_mounted_report(argv[-1]).encode("utf-8"), stderr=b"", exit_code=0)
            assert argv[0] == "timeout"
            return run(argv[-1], **kwargs)

        sandbox = BoxdSandbox("boxd:report", SimpleNamespace(machines=SimpleNamespace(exec=boxd_exec)), "report-machine")
    else:
        sdk = SimpleNamespace(commands=commands, files=SimpleNamespace(read_file=read_mounted_report))
        sandbox = OpenSandboxSandbox("opensandbox:report", sdk, run_command_opts_cls=SimpleNamespace)
    provider = Mock(spec=sandbox_provider.SandboxProvider, uses_thread_data_mounts=provider_name in {"aio", "opensandbox"})
    provider.get.return_value = sandbox
    provider.get_scoped.return_value = sandbox
    monkeypatch.setattr(sandbox_provider, "_default_sandbox_provider", provider)
    model = _one_tool_model("bash", {"command": "run-report"}, "call_bash")
    read_call = AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": ""}, "id": "call_read", "type": "tool_call"}])
    model.responses.extend([read_call, AIMessage(content="Done.")])
    agent = _compacting_agent(model, bash_tool, read_file_tool)
    config = {"configurable": {"thread_id": THREAD_ID}}
    context = {"thread_id": THREAD_ID}
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content="Run the report command.")], "thread_data": {"outputs_path": str(outputs)}, "sandbox": {"sandbox_id": sandbox.id}},
        config,
        context=context,
    )

    assert (outputs / "report.md").read_text(encoding="utf-8") == "Historical failures"
    await _compact_and_check_artifacts(agent, model, config, context, [REAL_REF])
    message = next(message for message in result["messages"] if isinstance(message, ToolMessage))
    assert message.content == stdout
    assert message.additional_kwargs[TOOL_META_KEY]["status"] == "success"
    assert message.additional_kwargs[TOOL_META_KEY]["exit_code"] == 0
    (entry,) = (await agent.aget_state(config)).values["tool_artifacts"]
    read_call.tool_calls[0]["args"]["path"] = entry["handle"]
    result = await agent.ainvoke({"messages": [HumanMessage(content="Read the report.")]}, config, context=context)
    read_result = next(item for item in result["messages"] if isinstance(item, ToolMessage) and item.tool_call_id == "call_read")
    assert read_result.status == "success"
    assert read_result.content == "Historical failures"


@pytest.mark.asyncio
@pytest.mark.parametrize("shared_blob", [False, True], ids=["local-output", "shared-blob"])
async def test_failed_bash_diagnostic_artifact_survives_compaction(tmp_path, monkeypatch, shared_blob):
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    store = LocalFsBlobStore(tmp_path / "blobs") if shared_blob else None
    monkeypatch.setattr("deerflow.agents.middlewares.tool_output_budget_middleware.get_blob_store_if_enabled", lambda: store)
    missing_path = "/mnt/user-data/outputs/missing.pdf"
    stdout = f"Could not produce {missing_path}\n" + "diagnostic line\n" * 850 + "Exit Code: 2"
    sandbox = Mock(spec=Sandbox, id="fixture:diagnostics", execute_command=Mock(return_value=CommandOutput(stdout, 2)), supports_command_cancellation=False)
    provider = Mock(spec=sandbox_provider.SandboxProvider, uses_thread_data_mounts=True)
    provider.get.return_value = sandbox
    provider.get_scoped.return_value = sandbox
    monkeypatch.setattr(sandbox_provider, "_default_sandbox_provider", provider)
    model = _one_tool_model("bash", {"command": "run-report"}, "call_bash")
    checkpointer = InMemorySaver()
    agent = _compacting_agent(model, bash_tool, checkpointer=checkpointer)
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
    if shared_blob:
        compacted = (await agent.aget_state(config)).values
        (entry,) = compacted["tool_artifacts"]
        other_outputs = tmp_path / "other-outputs"
        other_outputs.mkdir()

        def read_mounted_file(path):
            return (other_outputs / path.removeprefix("/mnt/user-data/outputs/")).read_text(encoding="utf-8")

        files = SimpleNamespace(read_file=read_mounted_file)
        resumed_sandbox = OpenSandboxSandbox(sandbox.id, SimpleNamespace(files=files), run_command_opts_cls=SimpleNamespace)
        resumed_provider = Mock(spec=sandbox_provider.SandboxProvider, uses_thread_data_mounts=True)
        resumed_provider.get.return_value = resumed_sandbox
        resumed_provider.get_scoped.return_value = resumed_sandbox
        monkeypatch.setattr(sandbox_provider, "_default_sandbox_provider", resumed_provider)
        read_model = _one_tool_model("read_file", {"path": entry["handle"]}, "call_read")
        # The read can return all the original bytes to the model in this run.
        reader = _compacting_agent(read_model, read_file_tool, checkpointer=checkpointer, output_budget=ToolOutputBudgetMiddleware(config=ToolOutputConfig(enabled=False)))
        restored = await reader.ainvoke(
            {"messages": [HumanMessage(content="Read the diagnostic.")], "thread_data": {"outputs_path": str(other_outputs)}},
            config,
            context=context,
        )
        read_result = next(item for item in restored["messages"] if isinstance(item, ToolMessage) and item.tool_call_id == "call_read")
        assert read_result.status == "success", read_result.content
        assert read_result.content == stdout
        assert (other_outputs / log.relative_to(outputs)).read_bytes() == stdout.encode("utf-8")
        assert entry[TOOL_OUTPUT_BLOB_KEY] == message.additional_kwargs[TOOL_OUTPUT_BLOB_KEY]


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
