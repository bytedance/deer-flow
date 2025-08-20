# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest

from langchain_core.messages import (
    AIMessageChunk,
    HumanMessageChunk,
    SystemMessageChunk,
    FunctionMessageChunk,
    ToolMessageChunk,
)

from src.llms import llm as llm_module
from langchain_core.messages import ChatMessageChunk
from src.llms.providers import dashscope as dashscope_module

from src.llms.providers.dashscope import (
    ChatDashscope,
    _convert_delta_to_message_chunk,
    _convert_chunk_to_generation_chunk,
)


class DummyChatDashscope:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture
def dashscope_conf():
    return {
        "BASIC_MODEL": {
            "api_key": "k",
            "base_url": "https://dashscope.aliyuncs.com/v1",
            "model": "qwen3-235b-a22b-instruct-2507",
        },
        "REASONING_MODEL": {
            "api_key": "rk",
            "base_url": "https://dashscope.aliyuncs.com/v1",
            "model": "qwen3-235b-a22b-thinking-2507",
        },
    }


def test_convert_delta_to_message_chunk_roles_and_extras():
    # Assistant with reasoning + tool calls
    delta = {
        "role": "assistant",
        "content": "Hello",
        "reasoning_content": "Think...",
        "tool_calls": [
            {
                "id": "call_1",
                "index": 0,
                "function": {"name": "lookup", "arguments": '{\\"q\\":\\"x\\"}'},
            }
        ],
    }
    msg = _convert_delta_to_message_chunk(delta, AIMessageChunk)
    assert isinstance(msg, AIMessageChunk)
    assert msg.content == "Hello"
    assert msg.additional_kwargs.get("reasoning_content") == "Think..."
    # tool_call_chunks should be present
    assert getattr(msg, "tool_call_chunks", None)

    # Human
    delta = {"role": "user", "content": "Hi"}
    msg = _convert_delta_to_message_chunk(delta, HumanMessageChunk)
    assert isinstance(msg, HumanMessageChunk)

    # System
    delta = {"role": "system", "content": "Rules"}
    msg = _convert_delta_to_message_chunk(delta, SystemMessageChunk)
    assert isinstance(msg, SystemMessageChunk)

    # Function
    delta = {"role": "function", "name": "f", "content": "{}"}
    msg = _convert_delta_to_message_chunk(delta, FunctionMessageChunk)
    assert isinstance(msg, FunctionMessageChunk)

    # Tool
    delta = {"role": "tool", "tool_call_id": "t1", "content": "ok"}
    msg = _convert_delta_to_message_chunk(delta, ToolMessageChunk)
    assert isinstance(msg, ToolMessageChunk)


def test_convert_chunk_to_generation_chunk_skip_and_usage():
    # Skips content.delta type
    assert (
        _convert_chunk_to_generation_chunk(
            {"type": "content.delta"}, AIMessageChunk, None
        )
        is None
    )

    # Proper chunk with usage and finish info
    chunk = {
        "choices": [
            {
                "delta": {"role": "assistant", "content": "Hi"},
                "finish_reason": "stop",
            }
        ],
        "model": "qwen3-235b-a22b-instruct-2507",
        "system_fingerprint": "fp",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    gen = _convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert gen is not None
    assert isinstance(gen.message, AIMessageChunk)
    assert gen.message.content == "Hi"
    # usage metadata should attach to AI message
    assert getattr(gen.message, "usage_metadata", None) is not None
    assert gen.generation_info.get("finish_reason") == "stop"
    assert gen.generation_info.get("model_name") == "qwen3-235b-a22b-instruct-2507"
    assert gen.generation_info.get("system_fingerprint") == "fp"


def test_llm_selects_dashscope_and_sets_enable_thinking(monkeypatch, dashscope_conf):
    # Use dummy class to capture kwargs on construction
    monkeypatch.setattr(llm_module, "ChatDashscope", DummyChatDashscope)

    # basic -> enable_thinking False
    inst = llm_module._create_llm_use_conf("basic", dashscope_conf)
    assert isinstance(inst, DummyChatDashscope)
    assert inst.kwargs["extra_body"]["enable_thinking"] is False
    assert inst.kwargs["base_url"].find("dashscope.") > 0

    # reasoning -> enable_thinking True
    inst2 = llm_module._create_llm_use_conf("reasoning", dashscope_conf)
    assert isinstance(inst2, DummyChatDashscope)
    assert inst2.kwargs["extra_body"]["enable_thinking"] is True


def test_llm_verify_ssl_false_adds_http_clients(monkeypatch, dashscope_conf):
    monkeypatch.setattr(llm_module, "ChatDashscope", DummyChatDashscope)
    # turn off ssl
    dashscope_conf = {**dashscope_conf}
    dashscope_conf["BASIC_MODEL"] = {
        **dashscope_conf["BASIC_MODEL"],
        "verify_ssl": False,
    }

    inst = llm_module._create_llm_use_conf("basic", dashscope_conf)
    assert "http_client" in inst.kwargs
    assert "http_async_client" in inst.kwargs


def test_convert_delta_to_message_chunk_developer_and_function_call_and_tool_calls():
    # developer role -> SystemMessageChunk with __openai_role__
    delta = {"role": "developer", "content": "dev rules"}
    msg = _convert_delta_to_message_chunk(delta, SystemMessageChunk)
    assert isinstance(msg, SystemMessageChunk)
    assert msg.additional_kwargs.get("__openai_role__") == "developer"

    # function_call name None -> empty string
    delta = {"role": "assistant", "function_call": {"name": None, "arguments": "{}"}}
    msg = _convert_delta_to_message_chunk(delta, AIMessageChunk)
    assert isinstance(msg, AIMessageChunk)
    assert msg.additional_kwargs["function_call"]["name"] == ""

    # tool_calls: one valid, one missing function -> should not crash and create one chunk
    delta = {
        "role": "assistant",
        "tool_calls": [
            {"id": "t1", "index": 0, "function": {"name": "f", "arguments": "{}"}},
            {"id": "t2", "index": 1},  # missing function key
        ],
    }
    msg = _convert_delta_to_message_chunk(delta, AIMessageChunk)
    assert isinstance(msg, AIMessageChunk)
    # tool_calls copied as-is
    assert msg.additional_kwargs["tool_calls"][0]["id"] == "t1"
    # tool_call_chunks only for valid one
    assert getattr(msg, "tool_call_chunks") and len(msg.tool_call_chunks) == 1


def test_convert_delta_to_message_chunk_default_class_and_unknown_role():
    # No role, default human -> HumanMessageChunk
    delta = {"content": "hey"}
    msg = _convert_delta_to_message_chunk(delta, HumanMessageChunk)
    assert isinstance(msg, HumanMessageChunk)

    # Unknown role -> ChatMessageChunk with that role
    delta = {"role": "observer", "content": "hmm"}
    msg = _convert_delta_to_message_chunk(delta, ChatMessageChunk)
    assert isinstance(msg, ChatMessageChunk)
    assert msg.role == "observer"


def test_convert_chunk_to_generation_chunk_empty_choices_and_usage():
    chunk = {
        "choices": [],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    gen = _convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert gen is not None
    assert isinstance(gen.message, AIMessageChunk)
    assert gen.message.content == ""
    assert getattr(gen.message, "usage_metadata", None) is not None
    assert gen.generation_info is None


def test_convert_chunk_to_generation_chunk_includes_base_info_and_logprobs():
    chunk = {
        "choices": [
            {
                "delta": {"role": "assistant", "content": "T"},
                "logprobs": {"content": [{"token": "T", "logprob": -0.1}]},
            }
        ]
    }
    base_info = {"headers": {"a": "b"}}
    gen = _convert_chunk_to_generation_chunk(chunk, AIMessageChunk, base_info)
    assert gen is not None
    assert gen.message.content == "T"
    assert gen.generation_info.get("headers") == {"a": "b"}
    assert "logprobs" in gen.generation_info


def test_convert_chunk_to_generation_chunk_beta_stream_format():
    chunk = {
        "chunk": {
            "choices": [
                {"delta": {"role": "assistant", "content": "From beta stream format"}}
            ]
        }
    }
    gen = _convert_chunk_to_generation_chunk(chunk, AIMessageChunk, None)
    assert gen is not None
    assert gen.message.content == "From beta stream format"


def test_chatdashscope_create_chat_result_adds_reasoning_content(monkeypatch):
    # Dummy objects for the super() return
    class DummyMsg:
        def __init__(self):
            self.additional_kwargs = {}

    class DummyGen:
        def __init__(self):
            self.message = DummyMsg()

    class DummyChatResult:
        def __init__(self):
            self.generations = [DummyGen()]

    # Patch super()._create_chat_result to return our dummy structure
    def fake_super_create(self, response, generation_info=None):
        return DummyChatResult()

    monkeypatch.setattr(
        dashscope_module.ChatOpenAI, "_create_chat_result", fake_super_create
    )

    # Patch openai.BaseModel in the module under test
    class DummyBaseModel:
        pass

    monkeypatch.setattr(dashscope_module.openai, "BaseModel", DummyBaseModel)

    # Build a fake OpenAI-like response with reasoning_content
    class RMsg:
        def __init__(self, rc):
            self.reasoning_content = rc

    class Choice:
        def __init__(self, rc):
            self.message = RMsg(rc)

    class FakeResponse(DummyBaseModel):
        def __init__(self):
            self.choices = [Choice("Reasoning...")]

    llm = ChatDashscope(model="dummy", api_key="k")
    result = llm._create_chat_result(FakeResponse())
    assert (
        result.generations[0].message.additional_kwargs.get("reasoning_content")
        == "Reasoning..."
    )


def test_chatdashscope_create_chat_result_dict_passthrough(monkeypatch):
    class DummyMsg:
        def __init__(self):
            self.additional_kwargs = {}

    class DummyGen:
        def __init__(self):
            self.message = DummyMsg()

    class DummyChatResult:
        def __init__(self):
            self.generations = [DummyGen()]

    def fake_super_create(self, response, generation_info=None):
        return DummyChatResult()

    monkeypatch.setattr(
        dashscope_module.ChatOpenAI, "_create_chat_result", fake_super_create
    )

    llm = ChatDashscope(model="dummy", api_key="k")
    result = llm._create_chat_result({"raw": "dict"})
    # Should not inject reasoning_content for dict responses
    assert "reasoning_content" not in result.generations[0].message.additional_kwargs
