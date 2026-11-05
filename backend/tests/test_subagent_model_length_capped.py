"""A subagent response cut at the provider output limit must not look like a clean completion."""

import importlib.util
import sys
from pathlib import Path

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from deerflow.config.app_config import AppConfig
from deerflow.subagents.config import SubagentConfig
from deerflow.subagents.status_contract import format_subagent_result_message


@pytest.fixture
def executor_module(monkeypatch, tmp_path):
    # conftest installs an executor stub. Load the production module separately
    # so the real subagent middleware chain runs.
    path = Path(__file__).parents[1] / "packages/harness/deerflow/subagents/executor.py"
    spec = importlib.util.spec_from_file_location("_model_length_capped_executor", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    yield module
    module._shutdown_isolated_subagent_loop()


class RecordingModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _executor(executor_module, monkeypatch, responses, tools):
    model = RecordingModel(messages=iter(responses))
    monkeypatch.setattr(executor_module, "create_chat_model", lambda **kwargs: model)
    app_config = AppConfig.model_validate(
        {
            "models": [{"name": "offline", "use": "langchain_openai:ChatOpenAI", "model": "offline"}],
            "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
            "summarization": {"enabled": False},
        }
    )
    return executor_module.SubagentExecutor(
        config=SubagentConfig(name="writer", description="Offline writer", skills=[]),
        tools=tools,
        parent_model="offline",
        app_config=app_config,
        thread_id="length-thread",
        user_id="length-user",
    )


@pytest.mark.asyncio
async def test_length_capped_answer_completes_with_model_length_capped(executor_module, monkeypatch):
    responses = [AIMessage(content="## Draft\n\nSection 1 covers the", response_metadata={"finish_reason": "length"})]
    executor = _executor(executor_module, monkeypatch, responses, tools=[])

    result = await executor._aexecute("Write the long draft")

    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert result.stop_reason == "model_length_capped"
    assert "Section 1 covers the" in result.result
    content, _ = format_subagent_result_message(result.status.value, result=result.result, stop_reason=result.stop_reason)
    assert content.startswith("Task Succeeded (capped: model output length limit)")


@pytest.mark.asyncio
async def test_length_capped_tool_call_is_dropped_not_executed(executor_module, monkeypatch):
    executed = []

    def write_report(content: str) -> str:
        """Write the report."""
        executed.append(content)
        return "written"

    tool = StructuredTool.from_function(write_report, name="write_report")
    responses = [
        AIMessage(
            content="",
            tool_calls=[{"name": "write_report", "args": {"content": "# Report\n\nhalf a sent"}, "id": "call-1"}],
            response_metadata={"finish_reason": "length"},
        ),
        AIMessage(content="unreachable: the capped turn must end the run"),
    ]
    executor = _executor(executor_module, monkeypatch, responses, tools=[tool])

    result = await executor._aexecute("Write the report to a file")

    assert executed == []
    assert result.status == executor_module.SubagentStatus.COMPLETED, result.error
    assert result.stop_reason == "model_length_capped"
    assert "output limit" in result.result
