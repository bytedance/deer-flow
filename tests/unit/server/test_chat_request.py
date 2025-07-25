# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from pydantic import ValidationError
from src.config.report_style import ReportStyle
from src.rag.retriever import Resource
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException

from src.server.chat_request import (
    ContentItem,
    ChatMessage,
    ChatRequest,
    TTSRequest,
    GeneratePodcastRequest,
    GeneratePPTRequest,
    GenerateProseRequest,
    EnhancePromptRequest,
)
import src.server.mcp_utils as mcp_utils  # Assuming mcp_utils is the module to test


def test_content_item_text_and_image():
    item_text = ContentItem(type="text", text="hello")
    assert item_text.type == "text"
    assert item_text.text == "hello"
    assert item_text.image_url is None

    item_image = ContentItem(type="image", image_url="http://img.com/1.png")
    assert item_image.type == "image"
    assert item_image.text is None
    assert item_image.image_url == "http://img.com/1.png"


def test_chat_message_with_string_content():
    msg = ChatMessage(role="user", content="Hello!")
    assert msg.role == "user"
    assert msg.content == "Hello!"


def test_chat_message_with_content_items():
    items = [ContentItem(type="text", text="hi")]
    msg = ChatMessage(role="assistant", content=items)
    assert msg.role == "assistant"
    assert isinstance(msg.content, list)
    assert msg.content[0].type == "text"


def test_chat_request_defaults():
    req = ChatRequest()
    assert req.messages == []
    assert req.resources == []
    assert req.debug is False
    assert req.thread_id == "__default__"
    assert req.max_plan_iterations == 1
    assert req.max_step_num == 3
    assert req.max_search_results == 3
    assert req.auto_accepted_plan is False
    assert req.interrupt_feedback is None
    assert req.mcp_settings is None
    assert req.enable_background_investigation is True
    assert req.report_style == ReportStyle.ACADEMIC


def test_chat_request_with_values():
    resource = Resource(
        name="test", type="doc", uri="some-uri-value", title="some-title-value"
    )
    msg = ChatMessage(role="user", content="hi")
    req = ChatRequest(
        messages=[msg],
        resources=[resource],
        debug=True,
        thread_id="tid",
        max_plan_iterations=2,
        max_step_num=5,
        max_search_results=10,
        auto_accepted_plan=True,
        interrupt_feedback="stop",
        mcp_settings={"foo": "bar"},
        enable_background_investigation=False,
        report_style="academic",
    )
    assert req.messages[0].role == "user"
    assert req.debug is True
    assert req.thread_id == "tid"
    assert req.max_plan_iterations == 2
    assert req.max_step_num == 5
    assert req.max_search_results == 10
    assert req.auto_accepted_plan is True
    assert req.interrupt_feedback == "stop"
    assert req.mcp_settings == {"foo": "bar"}
    assert req.enable_background_investigation is False
    assert req.report_style == ReportStyle.ACADEMIC


def test_tts_request_defaults():
    req = TTSRequest(text="hello")
    assert req.text == "hello"
    assert req.voice_type == "BV700_V2_streaming"
    assert req.encoding == "mp3"
    assert req.speed_ratio == 1.0
    assert req.volume_ratio == 1.0
    assert req.pitch_ratio == 1.0
    assert req.text_type == "plain"
    assert req.with_frontend == 1
    assert req.frontend_type == "unitTson"


def test_generate_podcast_request():
    req = GeneratePodcastRequest(content="Podcast content")
    assert req.content == "Podcast content"


def test_generate_ppt_request():
    req = GeneratePPTRequest(content="PPT content")
    assert req.content == "PPT content"


def test_generate_prose_request():
    req = GenerateProseRequest(prompt="Write a poem", option="poet", command="rhyme")
    assert req.prompt == "Write a poem"
    assert req.option == "poet"
    assert req.command == "rhyme"

    req2 = GenerateProseRequest(prompt="Write", option="short")
    assert req2.command == ""


def test_enhance_prompt_request_defaults():
    req = EnhancePromptRequest(prompt="Improve this")
    assert req.prompt == "Improve this"
    assert req.context == ""
    assert req.report_style == "academic"


def test_content_item_validation_error():
    with pytest.raises(ValidationError):
        ContentItem()  # missing required 'type'


def test_chat_message_validation_error():
    with pytest.raises(ValidationError):
        ChatMessage(role="user")  # missing content


def test_tts_request_validation_error():
    with pytest.raises(ValidationError):
        TTSRequest()  # missing required 'text'


@pytest.mark.asyncio
@patch("src.server.mcp_utils._get_tools_from_client_session", new_callable=AsyncMock)
@patch("src.server.mcp_utils.StdioServerParameters")
@patch("src.server.mcp_utils.stdio_client")
async def test_load_mcp_tools_exception_handling(
    mock_stdio_client, mock_StdioServerParameters, mock_get_tools
):  # Changed to async def
    mock_get_tools.side_effect = Exception("unexpected error")
    mock_StdioServerParameters.return_value = MagicMock()
    mock_stdio_client.return_value = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await mcp_utils.load_mcp_tools(server_type="stdio", command="foo")  # Use await
    assert exc.value.status_code == 500
    assert "unexpected error" in exc.value.detail
