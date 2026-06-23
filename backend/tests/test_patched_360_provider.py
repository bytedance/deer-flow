from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from deerflow.models import patched_360
from deerflow.models.patched_360 import PatchedChat360


class _FakeSkill:
    def __init__(self, name: str, path: str):
        self.name = name
        self._path = path

    def get_container_file_path(self, _base: str) -> str:
        return self._path


def _make_chat_result(content: str, tool_calls=None) -> ChatResult:
    message = AIMessage(content=content)
    if tool_calls:
        message.tool_calls = tool_calls
    generation = ChatGeneration(message=message)
    return ChatResult(generations=[generation])


async def _collect(async_iterable):
    return [chunk async for chunk in async_iterable]


def test_extract_tool_call_rewrites_skill_name_to_read_file(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("frontend-design", "/mnt/skills/public/frontend-design/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    content = """
<tool_call>
{"name": "frontend-design", "arguments": {"description": "Create a landing page", "parameters": {"layout": "Wide"}}}
</tool_call>
"""

    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(content)

    assert cleaned == ""
    assert tool_calls == [
        {
            "name": "read_file",
            "args": {
                "description": "Create a landing page",
                "path": "/mnt/skills/public/frontend-design/SKILL.md",
            },
            "id": tool_calls[0]["id"],
        }
    ]


def test_extract_tool_call_accepts_skill_alias_suffix(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("ppt-generation", "/mnt/skills/public/ppt-generation/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(
        '<tool_call>{"name":"_ppt-generation_skill","arguments":{"description":"Make slides"}}</tool_call>'
    )

    assert cleaned == ""
    assert tool_calls[0]["name"] == "read_file"
    assert tool_calls[0]["args"]["path"] == "/mnt/skills/public/ppt-generation/SKILL.md"


def test_extract_tool_call_keeps_real_tool_name():
    cleaned, tool_calls = patched_360._extract_tool_calls_from_content(
        '<tool_call>{"name":"web_search","arguments":{"query":"caren skincare brand"}}</tool_call>'
    )

    assert cleaned == ""
    assert tool_calls[0]["name"] == "web_search"
    assert tool_calls[0]["args"] == {"query": "caren skincare brand"}


def test_normalize_structured_skill_tool_call(monkeypatch):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [_FakeSkill("frontend-design", "/mnt/skills/public/frontend-design/SKILL.md")],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(skills=SimpleNamespace(container_path="/mnt/skills")),
    )

    normalized = patched_360._normalize_tool_calls(
        [
            {
                "name": "frontend-design",
                "args": {
                    "description": "Create a landing page",
                    "parameters": {"layout": "Wide"},
                },
                "id": "call_1",
            }
        ]
    )

    assert normalized == [
        {
            "name": "read_file",
            "args": {
                "description": "Create a landing page",
                "path": "/mnt/skills/public/frontend-design/SKILL.md",
            },
            "id": "call_1",
        }
    ]


@pytest.mark.asyncio
async def test_no_tools_uses_native_stream():
    async def fake_stream(*args, **kwargs):
        for text in ["hel", "lo"]:
            yield ChatGenerationChunk(message=AIMessageChunk(content=text, id="msg-1"))

    with patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=fake_stream):
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(model._astream([HumanMessage(content="hi")]))

    assert "".join(chunk.message.content for chunk in chunks) == "hello"


@pytest.mark.asyncio
async def test_no_tools_preserves_reasoning_content():
    """Reasoning_content deltas must land in additional_kwargs, not be dropped."""
    async def fake_stream(*args, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                additional_kwargs={"reasoning_content": "Thinking "},
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                additional_kwargs={"reasoning_content": "hard."},
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(content="Answer", id="msg-1")
        )

    with patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=fake_stream):
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(model._astream([HumanMessage(content="hi")]))

    reasoning = "".join(
        chunk.message.additional_kwargs.get("reasoning_content", "")
        for chunk in chunks
    )
    assert reasoning == "Thinking hard."
    assert "".join(chunk.message.content for chunk in chunks) == "Answer"


@pytest.mark.asyncio
async def test_with_tools_preserves_reasoning_content_through_repair():
    """Reasoning deltas survive the tool-call repair path (with tools bound)."""
    async def fake_stream(*args, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                additional_kwargs={"reasoning_content": "plan "},
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                additional_kwargs={"reasoning_content": "done"},
            )
        )
        yield ChatGenerationChunk(message=AIMessageChunk(content="Result", id="msg-1"))

    with patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=fake_stream):
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(
            model._astream(
                [HumanMessage(content="hi")],
                tools=[{"type": "function", "function": {"name": "noop"}}],
            )
        )

    reasoning = "".join(
        chunk.message.additional_kwargs.get("reasoning_content", "")
        for chunk in chunks
    )
    assert reasoning == "plan done"
    assert "Result" in "".join(chunk.message.content for chunk in chunks)


@pytest.mark.asyncio
async def test_convert_chunk_captures_reasoning_from_delta():
    """_convert_chunk_to_generation_chunk must lift reasoning_content out of delta."""
    model = PatchedChat360.__new__(PatchedChat360)
    chunk_dict = {
        "choices": [
            {"delta": {"reasoning_content": "thinking"}, "index": 0}
        ]
    }
    gen = model._convert_chunk_to_generation_chunk(chunk_dict, AIMessageChunk, {})
    assert gen is not None
    assert gen.message.additional_kwargs.get("reasoning_content") == "thinking"
    assert gen.message.content == ""


@pytest.mark.asyncio
async def test_create_chat_result_captures_reasoning():
    """Non-streaming responses must keep reasoning_content on the message."""
    model = PatchedChat360(
        model="qwen-test",
        api_key="sk-test",
        base_url="http://localhost:9999/v1",
    )
    response = {
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Answer",
                    "reasoning_content": "thought process",
                },
                "finish_reason": "stop",
            }
        ]
    }
    result = model._create_chat_result(response)
    assert len(result.generations) == 1
    msg = result.generations[0].message
    assert msg.content == "Answer"
    assert msg.additional_kwargs.get("reasoning_content") == "thought process"


@pytest.mark.asyncio
async def test_with_tools_native_stream_recovers_pseudo_tool_calls():
    async def fake_stream(*args, **kwargs):
        yield ChatGenerationChunk(message=AIMessageChunk(content="Before ", id="msg-1"))
        yield ChatGenerationChunk(message=AIMessageChunk(content='<tool_call>{"name":"web_search",', id="msg-1"))
        yield ChatGenerationChunk(message=AIMessageChunk(content='"arguments":{"query":"caren"}}</tool_call>', id="msg-1"))

    with patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=fake_stream):
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(
            model._astream(
                [HumanMessage(content="hi")],
                tools=[{"type": "function", "function": {"name": "web_search"}}],
            )
        )

    rendered = "".join(
        chunk.message.content for chunk in chunks if isinstance(chunk.message.content, str)
    )
    assert rendered == "Before "
    assert "<tool_call>" not in rendered

    tool_chunks = [chunk for chunk in chunks if getattr(chunk.message, "tool_calls", [])]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].message.tool_calls[0]["name"] == "web_search"
    assert tool_chunks[0].message.tool_calls[0]["args"] == {"query": "caren"}


@pytest.mark.asyncio
async def test_with_tools_native_stream_normalizes_structured_skill_tool_call(
    monkeypatch,
):
    monkeypatch.setattr(
        patched_360,
        "get_enabled_skills_for_config",
        lambda _config=None: [
            _FakeSkill(
                "frontend-design",
                "/mnt/skills/public/frontend-design/SKILL.md",
            )
        ],
    )
    monkeypatch.setattr(
        patched_360,
        "get_app_config",
        lambda: SimpleNamespace(
            skills=SimpleNamespace(container_path="/mnt/skills"),
        ),
    )

    async def fake_stream(*args, **kwargs):
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                tool_call_chunks=[
                    {
                        "name": "frontend-design",
                        "args": '{"description":"Create ',
                        "id": "call_1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            )
        )
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id="msg-1",
                tool_call_chunks=[
                    {
                        "name": "",
                        "args": 'a landing page"}',
                        "id": "call_1",
                        "index": 0,
                        "type": "tool_call_chunk",
                    }
                ],
            )
        )

    with patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=fake_stream):
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(
            model._astream(
                [HumanMessage(content="hi")],
                tools=[{"type": "function", "function": {"name": "frontend-design"}}],
            )
        )

    tool_chunks = [chunk for chunk in chunks if getattr(chunk.message, "tool_calls", [])]
    assert len(tool_chunks) == 1
    assert tool_chunks[0].message.tool_calls == [
        {
            "name": "read_file",
            "args": {
                "description": "Create a landing page",
                "path": "/mnt/skills/public/frontend-design/SKILL.md",
            },
            "id": "call_1",
            "type": "tool_call",
        }
    ]


@pytest.mark.asyncio
async def test_with_tools_falls_back_to_simulated_chunks_when_native_stream_errors():
    async def failing_stream(*args, **kwargs):
        raise RuntimeError("stream failed")
        yield  # pragma: no cover

    with (
        patch("deerflow.models.patched_360.ChatOpenAI._astream", side_effect=failing_stream),
        patch.object(PatchedChat360, "_agenerate", new_callable=AsyncMock) as mock_agenerate,
    ):
        mock_agenerate.return_value = _make_chat_result(
            "A" * 40,
            tool_calls=[{"name": "web_search", "args": {"query": "caren"}, "id": "call_1"}],
        )
        model = PatchedChat360.__new__(PatchedChat360)
        chunks = await _collect(
            model._astream(
                [HumanMessage(content="hi")],
                tools=[{"type": "function", "function": {"name": "web_search"}}],
            )
        )

    text_chunks = [
        chunk for chunk in chunks if isinstance(chunk.message.content, str) and chunk.message.content
    ]
    assert "".join(chunk.message.content for chunk in text_chunks) == "A" * 40
    assert len(text_chunks) > 1
    assert any(getattr(chunk.message, "tool_calls", []) for chunk in chunks)
