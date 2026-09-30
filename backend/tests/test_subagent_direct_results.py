"""Direct-return tools must reach the caller through the real subagent graph."""

import importlib.util
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool

from deerflow.config.app_config import AppConfig
from deerflow.subagents.config import SubagentConfig


@pytest.fixture
def executor_module(monkeypatch, tmp_path):
    # conftest installs an executor stub. Load the production module separately
    # without replacing its real graph, middleware, tool or state dependencies.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_direct_result_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    yield module
    module._shutdown_isolated_subagent_loop()


class RecordingModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "preamble, outputs, direct, expected",
    [
        ("", ["report ready"], [True], "report ready"),
        ("I will fetch it", ["report ready"], [True], "report ready"),
        ("", ["first report", "second report"], [True, True], "first report\n\nsecond report"),
        ("", [[{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]], [True], "first\nsecond"),
        ("I will fetch it", [""], [True], "No response generated"),
        ("", ["raw result"], [False], "Synthesized answer"),
        ("", ["direct result", "raw result"], [True, False], "Synthesized answer"),
    ],
    ids=["empty-assistant", "assistant-preamble", "parallel-direct", "content-blocks", "empty-result", "ordinary-tool", "mixed-tools"],
)
async def test_subagent_returns_terminal_output(executor_module, monkeypatch, preamble, outputs, direct, expected):
    executed = []

    def make_tool(index):
        def report() -> str | list:
            """Return one deterministic report."""
            executed.append(index)
            return outputs[index]

        return StructuredTool.from_function(report, name=f"report_{index}", return_direct=direct[index])

    tools = [make_tool(index) for index in range(len(outputs))]
    calls = [{"name": tool.name, "args": {}, "id": f"call-{index}"} for index, tool in enumerate(tools)]
    responses = [AIMessage(content=preamble, tool_calls=calls)]
    if not all(direct):
        responses.append(AIMessage(content="Synthesized answer"))
    model = RecordingModel(messages=iter(responses))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    app_config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "summarization": {"enabled": False},
        }
    )
    executor = executor_module.SubagentExecutor(
        config=SubagentConfig(name="reporter", description="Offline reports", skills=[]),
        tools=tools,
        parent_model="offline",
        app_config=app_config,
        thread_id="report-thread",
        user_id="report-user",
    )

    result = await executor._aexecute("Return the reports")

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert result.result == expected
    assert sorted(executed) == list(range(len(outputs)))
    tool_steps = [step for step in result.ai_messages if step["type"] == "tool"]
    assert [step["content"] for step in tool_steps] == outputs
    assert result.stop_reason is None


@pytest.mark.parametrize("tail", [[], [ToolMessage(content="unrelated result", tool_call_id="old-call", name="report")]])
def test_direct_result_requires_the_current_calls_result(executor_module, tail):
    message = AIMessage(content="Current assistant text", tool_calls=[{"name": "report", "args": {}, "id": "current-call"}])
    state = {"messages": [message, *tail]}

    assert executor_module._extract_final_result(state, trace_id="test", name="reporter", return_direct_tools={"report"}) == "Current assistant text"
    assert state["messages"] == [message, *tail]


def test_direct_results_follow_call_order_not_message_order(executor_module):
    state = {
        "messages": [
            AIMessage(content="", tool_calls=[{"name": "report", "args": {}, "id": "first"}, {"name": "report", "args": {}, "id": "second"}]),
            ToolMessage(content="second result", tool_call_id="second", name="report"),
            ToolMessage(content="first result", tool_call_id="first", name="report"),
        ]
    }

    assert executor_module._extract_final_result(state, trace_id="test", name="reporter", return_direct_tools={"report"}) == "first result\n\nsecond result"
