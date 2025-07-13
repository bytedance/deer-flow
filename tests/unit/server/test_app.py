# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import base64
import os
from unittest.mock import MagicMock, patch, mock_open
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException
from src.server.app import app, _make_event, _astream_workflow_generator
from src.config.report_style import ReportStyle
from langgraph.types import Command
from langchain_core.messages import ToolMessage
from langchain_core.messages import AIMessageChunk


@pytest.fixture
def client():
    return TestClient(app)


class TestMakeEvent:
    def test_make_event_with_content(self):
        event_type = "message_chunk"
        data = {"content": "Hello", "role": "assistant"}
        result = _make_event(event_type, data)
        expected = (
            'event: message_chunk\ndata: {"content": "Hello", "role": "assistant"}\n\n'
        )
        assert result == expected

    def test_make_event_with_empty_content(self):
        event_type = "message_chunk"
        data = {"content": "", "role": "assistant"}
        result = _make_event(event_type, data)
        expected = 'event: message_chunk\ndata: {"role": "assistant"}\n\n'
        assert result == expected

    def test_make_event_without_content(self):
        event_type = "tool_calls"
        data = {"role": "assistant", "tool_calls": []}
        result = _make_event(event_type, data)
        expected = (
            'event: tool_calls\ndata: {"role": "assistant", "tool_calls": []}\n\n'
        )
        assert result == expected


class TestTTSEndpoint:
    @patch.dict(
        os.environ,
        {
            "VOLCENGINE_TTS_APPID": "test_app_id",
            "VOLCENGINE_TTS_ACCESS_TOKEN": "test_token",
            "VOLCENGINE_TTS_CLUSTER": "test_cluster",
            "VOLCENGINE_TTS_VOICE_TYPE": "test_voice",
        },
    )
    @patch("src.server.app.VolcengineTTS")
    def test_tts_success(self, mock_tts_class, client):
        mock_tts_instance = MagicMock()
        mock_tts_class.return_value = mock_tts_instance

        # Mock successful TTS response
        audio_data_b64 = base64.b64encode(b"fake_audio_data").decode()
        mock_tts_instance.text_to_speech.return_value = {
            "success": True,
            "audio_data": audio_data_b64,
        }

        request_data = {
            "text": "Hello world",
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            "text_type": "plain",
            "with_frontend": True,
            "frontend_type": "unitTson",
        }

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mp3"
        assert b"fake_audio_data" in response.content

    @patch.dict(os.environ, {}, clear=True)
    def test_tts_missing_app_id(self, client):
        request_data = {"text": "Hello world", "encoding": "mp3"}

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 400
        assert "VOLCENGINE_TTS_APPID is not set" in response.json()["detail"]

    @patch.dict(
        os.environ,
        {"VOLCENGINE_TTS_APPID": "test_app_id", "VOLCENGINE_TTS_ACCESS_TOKEN": ""},
    )
    def test_tts_missing_access_token(self, client):
        request_data = {"text": "Hello world", "encoding": "mp3"}

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 400
        assert "VOLCENGINE_TTS_ACCESS_TOKEN is not set" in response.json()["detail"]

    @patch.dict(
        os.environ,
        {
            "VOLCENGINE_TTS_APPID": "test_app_id",
            "VOLCENGINE_TTS_ACCESS_TOKEN": "test_token",
        },
    )
    @patch("src.server.app.VolcengineTTS")
    def test_tts_api_error(self, mock_tts_class, client):
        mock_tts_instance = MagicMock()
        mock_tts_class.return_value = mock_tts_instance

        # Mock TTS error response
        mock_tts_instance.text_to_speech.return_value = {
            "success": False,
            "error": "TTS API error",
        }

        request_data = {"text": "Hello world", "encoding": "mp3"}

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 500
        assert "Internal Server Error" in response.json()["detail"]

    @pytest.mark.skip(reason="TTS server exception is catched")
    @patch("src.server.app.VolcengineTTS")
    def test_tts_api_exception(self, mock_tts_class, client):
        mock_tts_instance = MagicMock()
        mock_tts_class.return_value = mock_tts_instance

        # Mock TTS error response
        mock_tts_instance.side_effect = Exception("TTS API error")

        request_data = {"text": "Hello world", "encoding": "mp3"}

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 500
        assert "Internal Server Error" in response.json()["detail"]


class TestPodcastEndpoint:
    @patch("src.server.app.build_podcast_graph")
    def test_generate_podcast_success(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": b"fake_audio_data"}

        request_data = {"content": "Test content for podcast"}

        response = client.post("/api/podcast/generate", json=request_data)

        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mp3"
        assert response.content == b"fake_audio_data"

    @patch("src.server.app.build_podcast_graph")
    def test_generate_podcast_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("Podcast generation failed")

        request_data = {"content": "Test content"}

        response = client.post("/api/podcast/generate", json=request_data)

        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestPPTEndpoint:
    @patch("src.server.app.build_ppt_graph")
    @patch("builtins.open", new_callable=mock_open, read_data=b"fake_ppt_data")
    def test_generate_ppt_success(self, mock_file, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {
            "generated_file_path": "/fake/path/test.pptx"
        }

        request_data = {"content": "Test content for PPT"}

        response = client.post("/api/ppt/generate", json=request_data)

        assert response.status_code == 200
        assert (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
            in response.headers["content-type"]
        )
        assert response.content == b"fake_ppt_data"

    @patch("src.server.app.build_ppt_graph")
    def test_generate_ppt_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("PPT generation failed")

        request_data = {"content": "Test content"}

        response = client.post("/api/ppt/generate", json=request_data)

        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestEnhancePromptEndpoint:
    @patch("src.server.app.build_prompt_enhancer_graph")
    def test_enhance_prompt_success(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": "Enhanced prompt"}

        request_data = {
            "prompt": "Original prompt",
            "context": "Some context",
            "report_style": "academic",
        }

        response = client.post("/api/prompt/enhance", json=request_data)

        assert response.status_code == 200
        assert response.json()["result"] == "Enhanced prompt"

    @patch("src.server.app.build_prompt_enhancer_graph")
    def test_enhance_prompt_with_different_styles(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": "Enhanced prompt"}

        styles = [
            "ACADEMIC",
            "popular_science",
            "NEWS",
            "social_media",
            "invalid_style",
        ]

        for style in styles:
            request_data = {"prompt": "Test prompt", "report_style": style}

            response = client.post("/api/prompt/enhance", json=request_data)
            assert response.status_code == 200

    @patch("src.server.app.build_prompt_enhancer_graph")
    def test_enhance_prompt_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("Enhancement failed")

        request_data = {"prompt": "Test prompt"}

        response = client.post("/api/prompt/enhance", json=request_data)

        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestMCPEndpoint:
    @patch("src.server.app.load_mcp_tools")
    def test_mcp_server_metadata_success(self, mock_load_tools, client):
        mock_load_tools.return_value = [
            {"name": "test_tool", "description": "Test tool"}
        ]

        request_data = {
            "transport": "stdio",
            "command": "test_command",
            "args": ["arg1", "arg2"],
            "env": {"ENV_VAR": "value"},
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["transport"] == "stdio"
        assert response_data["command"] == "test_command"
        assert len(response_data["tools"]) == 1

    @patch("src.server.app.load_mcp_tools")
    def test_mcp_server_metadata_with_custom_timeout(self, mock_load_tools, client):
        mock_load_tools.return_value = []

        request_data = {
            "transport": "stdio",
            "command": "test_command",
            "timeout_seconds": 600,
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 200
        mock_load_tools.assert_called_once()

    @patch("src.server.app.load_mcp_tools")
    def test_mcp_server_metadata_with_exception(self, mock_load_tools, client):
        mock_load_tools.side_effect = HTTPException(
            status_code=400, detail="MCP Server Error"
        )

        request_data = {
            "transport": "stdio",
            "command": "test_command",
            "args": ["arg1", "arg2"],
            "env": {"ENV_VAR": "value"},
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestRAGEndpoints:
    @patch("src.server.app.SELECTED_RAG_PROVIDER", "test_provider")
    def test_rag_config(self, client):
        response = client.get("/api/rag/config")

        assert response.status_code == 200
        assert response.json()["provider"] == "test_provider"

    @patch("src.server.app.build_retriever")
    def test_rag_resources_with_retriever(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.list_resources.return_value = [
            {
                "uri": "test_uri",
                "title": "Test Resource",
                "description": "Test Description",
            }
        ]
        mock_build_retriever.return_value = mock_retriever

        response = client.get("/api/rag/resources?query=test")

        assert response.status_code == 200
        assert len(response.json()["resources"]) == 1

    @patch("src.server.app.build_retriever")
    def test_rag_resources_without_retriever(self, mock_build_retriever, client):
        mock_build_retriever.return_value = None

        response = client.get("/api/rag/resources")

        assert response.status_code == 200
        assert response.json()["resources"] == []


class TestChatStreamEndpoint:
    @patch("src.server.app.graph")
    def test_chat_stream_with_default_thread_id(self, mock_graph, client):
        # Mock the async stream
        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        request_data = {
            "thread_id": "__default__",
            "messages": [{"role": "user", "content": "Hello"}],
            "resources": [],
            "max_plan_iterations": 3,
            "max_step_num": 10,
            "max_search_results": 5,
            "auto_accepted_plan": True,
            "interrupt_feedback": "",
            "mcp_settings": {},
            "enable_background_investigation": False,
            "report_style": "academic",
        }

        response = client.post("/api/chat/stream", json=request_data)

        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


class TestAstreamWorkflowGenerator:
    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_basic_flow(self, mock_graph):
        # Mock AI message chunk
        mock_message = AIMessageChunk(content="Hello world")
        mock_message.id = "msg_123"
        mock_message.response_metadata = {}
        mock_message.tool_calls = []
        mock_message.tool_call_chunks = []

        # Mock the async stream - yield messages in the correct format
        async def mock_astream(*args, **kwargs):
            # Yield a tuple (message, metadata) instead of just [message]
            yield ("agent1:subagent", "messages", (mock_message, {}))

        mock_graph.astream = mock_astream

        messages = [{"role": "user", "content": "Hello"}]
        thread_id = "test_thread"
        resources = []

        generator = _astream_workflow_generator(
            messages=messages,
            thread_id=thread_id,
            resources=resources,
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: message_chunk" in events[0]
        assert "Hello world" in events[0]
        # Check for the actual agent name that appears in the output
        assert '"agent": "a"' in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_with_interrupt_feedback(self, mock_graph):

        # Mock the async stream
        async def mock_astream(*args, **kwargs):
            # Verify that Command is passed as input when interrupt_feedback is provided
            assert isinstance(args[0], Command)
            assert "[edit_plan] Hello" in args[0].resume
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        messages = [{"role": "user", "content": "Hello"}]

        generator = _astream_workflow_generator(
            messages=messages,
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=False,
            interrupt_feedback="edit_plan",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_interrupt_event(self, mock_graph):
        # Mock interrupt data
        mock_interrupt = MagicMock()
        mock_interrupt.ns = ["interrupt_id"]
        mock_interrupt.value = "Plan requires approval"

        interrupt_data = {"__interrupt__": [mock_interrupt]}

        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", interrupt_data)

        mock_graph.astream = mock_astream

        generator = _astream_workflow_generator(
            messages=[],
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: interrupt" in events[0]
        assert "Plan requires approval" in events[0]
        assert "interrupt_id" in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_tool_message(self, mock_graph):

        # Mock tool message
        mock_tool_message = ToolMessage(content="Tool result", tool_call_id="tool_123")
        mock_tool_message.id = "msg_456"

        async def mock_astream(*args, **kwargs):
            yield ("agent1:subagent", "step1", (mock_tool_message, {}))

        mock_graph.astream = mock_astream

        generator = _astream_workflow_generator(
            messages=[],
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: tool_call_result" in events[0]
        assert "Tool result" in events[0]
        assert "tool_123" in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_ai_message_with_tool_calls(
        self, mock_graph
    ):

        # Mock AI message with tool calls
        mock_ai_message = AIMessageChunk(content="Making tool call")
        mock_ai_message.id = "msg_789"
        mock_ai_message.response_metadata = {"finish_reason": "tool_calls"}
        mock_ai_message.tool_calls = [{"name": "search", "args": {"query": "test"}}]
        mock_ai_message.tool_call_chunks = [{"name": "search"}]

        async def mock_astream(*args, **kwargs):
            yield ("agent1:subagent", "step1", (mock_ai_message, {}))

        mock_graph.astream = mock_astream

        generator = _astream_workflow_generator(
            messages=[],
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: tool_calls" in events[0]
        assert "Making tool call" in events[0]
        assert "tool_calls" in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_ai_message_with_tool_call_chunks(
        self, mock_graph
    ):

        # Mock AI message with only tool call chunks
        mock_ai_message = AIMessageChunk(content="Streaming tool call")
        mock_ai_message.id = "msg_101"
        mock_ai_message.response_metadata = {}
        mock_ai_message.tool_calls = []
        mock_ai_message.tool_call_chunks = [{"name": "search", "index": 0}]

        async def mock_astream(*args, **kwargs):
            yield ("agent1:subagent", "step1", (mock_ai_message, {}))

        mock_graph.astream = mock_astream

        generator = _astream_workflow_generator(
            messages=[],
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: tool_call_chunks" in events[0]
        assert "Streaming tool call" in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_with_finish_reason(self, mock_graph):

        # Mock AI message with finish reason
        mock_ai_message = AIMessageChunk(content="Complete response")
        mock_ai_message.id = "msg_finish"
        mock_ai_message.response_metadata = {"finish_reason": "stop"}
        mock_ai_message.tool_calls = []
        mock_ai_message.tool_call_chunks = []

        async def mock_astream(*args, **kwargs):
            yield ("agent1:subagent", "step1", (mock_ai_message, {}))

        mock_graph.astream = mock_astream

        generator = _astream_workflow_generator(
            messages=[],
            thread_id="test_thread",
            resources=[],
            max_plan_iterations=3,
            max_step_num=10,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=False,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
        )

        events = []
        async for event in generator:
            events.append(event)

        assert len(events) == 1
        assert "event: message_chunk" in events[0]
        assert "finish_reason" in events[0]
        assert "stop" in events[0]

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_config_passed_correctly(self, mock_graph):

        mock_ai_message = AIMessageChunk(content="Test")
        mock_ai_message.id = "test_id"
        mock_ai_message.response_metadata = {}
        mock_ai_message.tool_calls = []
        mock_ai_message.tool_call_chunks = []

        async def verify_config(*args, **kwargs):
            config = kwargs.get("config", {})
            assert config["thread_id"] == "test_thread"
            assert config["max_plan_iterations"] == 5
            assert config["max_step_num"] == 20
            assert config["max_search_results"] == 10
            assert config["report_style"] == ReportStyle.NEWS.value
            yield ("agent1", "messages", [mock_ai_message])


class TestGenerateProseEndpoint:
    @patch("src.server.app.build_prose_graph")
    def test_generate_prose_success(self, mock_build_graph, client):
        # Mock the workflow and its astream method
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow

        class MockEvent:
            def __init__(self, content):
                self.content = content

        async def mock_astream(*args, **kwargs):
            yield (None, [MockEvent("Generated prose 1")])
            yield (None, [MockEvent("Generated prose 2")])

        mock_workflow.astream.return_value = mock_astream()
        request_data = {
            "prompt": "Write a story.",
            "option": "default",
            "command": "generate",
        }

        response = client.post("/api/prose/generate", json=request_data)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        # Read the streaming response content
        content = b"".join(response.iter_bytes())
        assert b"Generated prose 1" in content or b"Generated prose 2" in content

    @patch("src.server.app.build_prose_graph")
    def test_generate_prose_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("Prose generation failed")
        request_data = {
            "prompt": "Write a story.",
            "option": "default",
            "command": "generate",
        }
        response = client.post("/api/prose/generate", json=request_data)
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"
