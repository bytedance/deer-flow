"""Offline image-model chat choice regression with synthetic profiles only."""

from types import SimpleNamespace

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
