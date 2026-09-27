"""Offline image-model chat choice regression with synthetic profiles only."""

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.runtime import Runtime

from deerflow.agents.image_generation_choice import selected_image_source_from_reply
from deerflow.agents.middlewares.clarification_middleware import ClarificationMiddleware
from deerflow.config.app_config import AppConfig
from deerflow.config.image_generation import ManagedImageGenerationProfile, ManagedImageGenerationProfileStore, bind_image_generation_source, legacy_image_storage_identity
from deerflow.sandbox.lease import SandboxLeaseManager
from deerflow.tools.builtins.clarification_tool import ask_clarification_tool


@pytest.fixture
def image_choice(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    store = ManagedImageGenerationProfileStore()
    saved = store.save(
        ManagedImageGenerationProfile(
            name="web-image",
            provider="openai",
            model="web-model",
            base_url="https://images.example/v1",
            api_key="synthetic-web-key",
            server_model_at_enable="gemini:old-server-model",
        ),
        expected_revision=None,
    )
    environment = {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "new-server-model"}
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr("deerflow.agents.middlewares.clarification_middleware.get_app_config", lambda: config)
    return store, saved, environment


def _choice_card():
    middleware = ClarificationMiddleware()
    proposed = AIMessage(content="", tool_calls=[{"name": "generate_image", "args": {"prompt_file": "/mnt/user-data/prompt.txt"}, "id": "call-image"}])
    patched = middleware.after_model({"messages": [proposed]}, Runtime(context={}))
    assert patched is not None
    call = patched["messages"][0].tool_calls[0]
    assert call["name"] == "ask_clarification"
    assert "generate_image" not in str(patched["messages"][0].tool_calls)
    result = middleware._handle_clarification(SimpleNamespace(tool_call=call))
    return result.update["messages"][0]


def test_image_choice_card_uses_chinese_for_chinese_chat(image_choice):
    middleware = ClarificationMiddleware()
    proposed = AIMessage(content="", tool_calls=[{"name": "generate_image", "args": {}, "id": "call-image"}])
    patched = middleware.after_model({"messages": [HumanMessage(content="请生成一张图片"), proposed]}, Runtime(context={}))
    assert patched is not None
    args = patched["messages"][0].tool_calls[0]["args"]
    assert args["question"] == "这张图片要使用哪个图片模型？"
    assert args["options"][0].startswith("网页:")


def test_server_first_web_profile_still_prompts_before_image_execution(image_choice, monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins.image_generation_tool import generate_image_tool

    store, saved, environment = image_choice
    store.save(
        saved.model_copy(update={"server_model_at_enable": "gemini:new-server-model"}),
        expected_revision=saved.revision,
    )
    card = _choice_card()
    assert card.artifact["human_input"]["clarification_type"] == "image_model_choice"

    monkeypatch.setattr("deerflow.tools.builtins.image_generation_tool.get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}}))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = generate_image_tool.func(SimpleNamespace(context={}, state={}), "/mnt/user-data/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result.startswith("Error: IMAGE_PROFILE_CHOICE_REQUIRED")


@pytest.mark.parametrize("context", [{"non_interactive": True}, {"channel_name": "github"}, {"is_subagent": True}])
def test_unattended_image_call_uses_server_before_sandbox_acquisition(image_choice, monkeypatch, context):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_module
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
    from deerflow.config.image_generation import legacy_image_storage_identity, selected_image_generation_source
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    _, _, environment = image_choice
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(image_tool, "get_app_config", lambda: config)
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    provider = object.__new__(AioSandboxProvider)
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_base_sandbox_id_for_thread", lambda *_args: "base-thread")
    selected = []

    def acquire(_runtime):
        selected.append((selected_image_generation_source(), provider._sandbox_id_for_thread("thread-a", "user-a")))
        return object()

    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", acquire)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", lambda _sandbox, command, **_kwargs: re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group())

    runtime = SimpleNamespace(context=context, state={})
    result = image_tool.generate_image_tool.func(runtime, "/mnt/user-data/workspace/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result.startswith("Successfully generated")
    assert selected == [("sandbox_environment", provider._image_config_sandbox_id("base-thread", legacy_image_storage_identity(environment)))]
    assert selected_image_generation_source() is None


@pytest.mark.parametrize("context", [{"non_interactive": True}, {"channel_name": "github"}])
def test_unattended_runs_skip_chat_card_and_report_server_source(image_choice, monkeypatch, context):
    from deerflow.tools.builtins import image_generation_tool as image_tool

    _, _, environment = image_choice
    proposed = AIMessage(content="", tool_calls=[{"name": "generate_image", "args": {}, "id": "call-image"}])
    assert ClarificationMiddleware().after_model({"messages": [proposed]}, Runtime(context=context)) is None

    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(image_tool, "get_app_config", lambda: config)
    assert image_tool.check_image_generation_tool.args == {}
    status = image_tool.check_image_generation_tool.func(SimpleNamespace(context=context))
    assert "gemini/new-server-model" in status
    assert "choose one in chat" not in status


def test_graph_injects_runtime_into_unattended_image_status_tool(image_choice, monkeypatch):
    from deerflow.tools.builtins import image_generation_tool as image_tool

    _, _, environment = image_choice
    monkeypatch.setattr(image_tool, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}}))

    class Model(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self):
            return "synthetic-image-status"

        def bind_tools(self, _tools, **_kwargs):
            return self

        def _generate(self, _messages, stop=None, run_manager=None, **_kwargs):
            self.calls += 1
            message = AIMessage(content="", tool_calls=[{"name": "check_image_generation", "args": {}, "id": "check-image"}]) if self.calls == 1 else AIMessage(content="Done")
            return ChatResult(generations=[ChatGeneration(message=message)])

    agent = create_agent(model=Model(), tools=[image_tool.check_image_generation_tool])
    result = agent.invoke({"messages": [HumanMessage(content="Create an image")]}, context={"non_interactive": True})
    status = next(item for item in result["messages"] if isinstance(item, ToolMessage))
    assert "gemini/new-server-model" in str(status.content)
    assert "choose one in chat" not in str(status.content)


@pytest.mark.asyncio
async def test_unattended_async_image_call_binds_server_before_sandbox_helper(image_choice, monkeypatch):
    from deerflow.config.image_generation import selected_image_generation_source
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins import image_generation_tool as image_tool

    _, _, environment = image_choice
    monkeypatch.setattr(image_tool, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}}))

    async def acquire_then_run(*_args):
        assert selected_image_generation_source() == "sandbox_environment"
        return "synthetic-success"

    monkeypatch.setattr(sandbox_tools, "_run_sync_tool_after_async_sandbox_init", acquire_then_run)
    result = await image_tool.generate_image_tool.coroutine(SimpleNamespace(context={"non_interactive": True}, state={}), "/mnt/user-data/workspace/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result == "synthetic-success"
    assert selected_image_generation_source() is None


@pytest.mark.asyncio
async def test_scheduled_run_binds_server_image_source_before_agent_stream(image_choice, monkeypatch):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as provider_module
    from deerflow.community.aio_sandbox.aio_sandbox_provider import AioSandboxProvider
    from deerflow.community.aio_sandbox.local_backend import LocalContainerBackend
    from deerflow.config.image_generation import legacy_image_storage_identity, selected_image_generation_source
    from deerflow.runtime.runs.manager import RunManager
    from deerflow.runtime.runs.worker import RunContext, run_agent

    _, _, environment = image_choice
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(provider_module, "get_app_config", lambda: config)
    provider = object.__new__(AioSandboxProvider)
    provider._backend = object.__new__(LocalContainerBackend)
    monkeypatch.setattr(provider, "_base_sandbox_id_for_thread", lambda *_args: "base-thread")
    captured = []

    class Agent:
        async def astream(self, _input, **_kwargs):
            captured.append((selected_image_generation_source(), provider._sandbox_id_for_thread("thread-a", "user-a")))
            yield {"messages": []}

    manager = RunManager()
    record = await manager.create("thread-a")
    bridge = SimpleNamespace(publish=AsyncMock(), publish_end=AsyncMock(), cleanup=AsyncMock())
    await run_agent(
        bridge,
        manager,
        record,
        ctx=RunContext(checkpointer=None, app_config=config),
        agent_factory=lambda *, config: Agent(),
        graph_input={},
        config={"context": {"non_interactive": True}},
    )
    assert captured == [("sandbox_environment", provider._image_config_sandbox_id("base-thread", legacy_image_storage_identity(environment)))]
    assert selected_image_generation_source() is None


@pytest.mark.parametrize("option_id,expected", [("option-1", "managed"), ("option-2", "sandbox_environment")])
def test_chat_card_selects_live_profile_without_running_image_tool(image_choice, option_id, expected):
    _, _, environment = image_choice
    card = _choice_card()
    payload = card.artifact["human_input"]
    assert payload["input_mode"] == "single_choice"
    option = next(item for item in payload["options"] if item["id"] == option_id)
    reply = HumanMessage(
        content=option["value"],
        additional_kwargs={
            "human_input_response": {
                "version": 1,
                "kind": "human_input_response",
                "source": "ask_clarification",
                "request_id": card.id,
                "response_kind": "option",
                "option_id": option_id,
                "value": option["value"],
            }
        },
    )
    assert selected_image_source_from_reply({"messages": [reply]}, (card,), environment) == expected
    assert selected_image_source_from_reply({"messages": [reply]}, (), environment) is None
    assert selected_image_source_from_reply({"messages": [reply]}, (card,), {**environment, "GEMINI_IMAGE_MODEL": "changed-again"}) is None


def test_ambiguous_image_tool_fails_before_sandbox_acquisition(image_choice, monkeypatch):
    from deerflow.tools.builtins.image_generation_tool import generate_image_tool

    monkeypatch.setattr("deerflow.tools.builtins.image_generation_tool.get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test", "environment": image_choice[2]}}))
    result = generate_image_tool.func(SimpleNamespace(context={}, state={}), "/mnt/user-data/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result.startswith("Error: IMAGE_PROFILE_CHOICE_REQUIRED")


@pytest.mark.asyncio
async def test_ambiguous_async_image_tool_fails_before_sandbox_acquisition(image_choice, monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools
    from deerflow.tools.builtins.image_generation_tool import generate_image_tool

    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": image_choice[2]}})
    monkeypatch.setattr("deerflow.tools.builtins.image_generation_tool.get_app_config", lambda: config)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = await generate_image_tool.coroutine(SimpleNamespace(context={}, state={}), "/mnt/user-data/prompt.txt", "/mnt/user-data/outputs/image.png")
    assert result.startswith("Error: IMAGE_PROFILE_CHOICE_REQUIRED")


@pytest.mark.parametrize("async_mode", [False, True])
@pytest.mark.asyncio
async def test_real_agent_graph_replaces_image_tool_with_inline_choice(image_choice, async_mode):
    executions = []

    @tool("generate_image")
    def fake_generate_image(prompt_file: str) -> str:
        """Record a fake image tool call."""
        executions.append(prompt_file)
        return "unexpected"

    class FakeModel(BaseChatModel):
        call_count: int = 0

        @property
        def _llm_type(self):
            return "fake-image-choice"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.call_count += 1
            return ChatResult(
                generations=[
                    ChatGeneration(
                        message=AIMessage(
                            id="image-choice-request",
                            content="",
                            tool_calls=[{"name": "generate_image", "args": {"prompt_file": "/mnt/user-data/prompt.txt"}, "id": "call-image"}],
                        )
                    )
                ]
            )

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = FakeModel()
    agent = create_agent(model=model, tools=[ask_clarification_tool, fake_generate_image], middleware=[ClarificationMiddleware()], checkpointer=InMemorySaver())
    request = {"messages": [HumanMessage(content="Create an image")]}
    run_config = {"configurable": {"thread_id": "synthetic-image-choice-thread"}}
    result = await agent.ainvoke(request, config=run_config) if async_mode else agent.invoke(request, config=run_config)
    assert model.call_count == 1
    assert executions == []
    ai = next(item for item in result["messages"] if isinstance(item, AIMessage))
    assert [item["name"] for item in ai.tool_calls] == ["ask_clarification"]
    card = next(item for item in result["messages"] if isinstance(item, ToolMessage))
    assert card.artifact["human_input"]["clarification_type"] == "image_model_choice"
    checkpoint = await agent.aget_state(run_config) if async_mode else agent.get_state(run_config)
    assert any(isinstance(item, ToolMessage) and item.id == card.id for item in checkpoint.values["messages"])


def test_aio_image_choice_acquires_another_identity_without_destroying_old_container(image_choice, monkeypatch):
    from deerflow.community.aio_sandbox import aio_sandbox_provider as module

    _, saved, environment = image_choice
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(module, "get_app_config", lambda: config)

    class FakeLocalBackend:
        pass

    monkeypatch.setattr(module, "LocalContainerBackend", FakeLocalBackend)
    aio_provider = object.__new__(module.AioSandboxProvider)
    aio_provider._backend = FakeLocalBackend()
    monkeypatch.setattr(aio_provider, "_base_sandbox_id_for_thread", lambda _thread, _user: "base-thread")
    web_id = aio_provider._sandbox_id_for_thread("thread-a", "user-a")
    assert web_id == aio_provider._image_profile_sandbox_id("base-thread", saved.revision)
    server_id = aio_provider._image_config_sandbox_id("base-thread", legacy_image_storage_identity(environment))
    with bind_image_generation_source("sandbox_environment"):
        assert aio_provider._sandbox_id_for_thread("thread-a", "user-a") == server_id

    class FakeProvider:
        def __init__(self):
            self.active = {}
            self.warm = set()
            self.destroyed = []

        def get(self, sandbox_id):
            return self.active.get(sandbox_id)

        def get_scoped(self, sandbox_id, *, thread_id, user_id):
            return self.active.get(sandbox_id)

        def acquire(self, thread_id, *, user_id):
            sandbox_id = aio_provider._sandbox_id_for_thread(thread_id, user_id)
            self.active[sandbox_id] = SimpleNamespace(release_command_scope=lambda _owner_id: None)
            self.warm.discard(sandbox_id)
            return sandbox_id

        def release(self, sandbox_id):
            self.active.pop(sandbox_id)
            self.warm.add(sandbox_id)

        def destroy(self, sandbox_id):
            self.destroyed.append(sandbox_id)

    provider = FakeProvider()
    lease = SandboxLeaseManager(provider)
    try:
        assert lease.acquire("run-web", "thread-a", user_id="user-a") == web_id
        lease.release("run-web")  # The chat card ends this run and parks its container.
        assert web_id in provider.warm
        with bind_image_generation_source("sandbox_environment"):
            assert lease.reuse_or_acquire("run-server", web_id, thread_id="thread-a", user_id="user-a") == server_id
        assert web_id in provider.warm
        assert provider.destroyed == []
    finally:
        lease.close()
