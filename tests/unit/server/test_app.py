# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT


import asyncio
import base64
import os
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Command

from src.config.report_style import ReportStyle
from src.server.app import (
    _astream_workflow_generator,
    _create_interrupt_event,
    _make_event,
    _stream_graph_events,
    app,
)


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


class TestStreamGraphEventsCancellation:
    """Tests for graceful handling of asyncio.CancelledError in _stream_graph_events."""

    @pytest.mark.asyncio
    async def test_cancelled_error_does_not_propagate(self):
        """When the stream is cancelled, the generator should end gracefully
        instead of re-raising CancelledError (fixes issue #847)."""

        async def _mock_astream(*args, **kwargs):
            yield ("agent", None, {"some": "data"})
            raise asyncio.CancelledError()

        graph = MagicMock()
        graph.astream = _mock_astream

        events = []
        # The generator must NOT raise CancelledError
        async for event in _stream_graph_events(
            graph, {"input": "test"}, {}, "test-thread-id"
        ):
            events.append(event)

        # It should have yielded a final error event with reason='cancelled'
        final_events_with_cancelled = [
            e for e in events if '"reason": "cancelled"' in e
        ]
        assert len(final_events_with_cancelled) == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_yields_cancelled_reason(self):
        """The final event should carry reason='cancelled' so the client
        can distinguish cancellation from real errors."""

        async def _mock_astream(*args, **kwargs):
            raise asyncio.CancelledError()
            yield  # make this an async generator  # noqa: E501

        graph = MagicMock()
        graph.astream = _mock_astream

        events = []
        async for event in _stream_graph_events(
            graph, {"input": "test"}, {}, "test-thread-id"
        ):
            events.append(event)

        assert len(events) == 1
        assert '"reason": "cancelled"' in events[0]
        assert '"error": "Stream cancelled"' in events[0]


@pytest.mark.asyncio
async def test_astream_workflow_generator_preserves_clarification_history():
    messages = [
        {"role": "user", "content": "Research on renewable energy"},
        {
            "role": "assistant",
            "content": "What type of renewable energy would you like to know about?",
        },
        {"role": "user", "content": "Solar and wind energy"},
        {
            "role": "assistant",
            "content": "Please tell me the research dimensions you focus on, such as technological development or market applications.",
        },
        {"role": "user", "content": "Technological development"},
        {
            "role": "assistant",
            "content": "Please specify the time range you want to focus on, such as current status or future trends.",
        },
        {"role": "user", "content": "Current status and future trends"},
    ]

    captured_data = {}

    def empty_async_iterator(*args, **kwargs):
        captured_data["workflow_input"] = args[1]
        captured_data["workflow_config"] = args[2]

        class IteratorObject:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        return IteratorObject()

    with (
        patch("src.server.app._process_initial_messages"),
        patch("src.server.app._stream_graph_events", side_effect=empty_async_iterator),
    ):
        generator = _astream_workflow_generator(
            messages=messages,
            thread_id="clarification-thread",
            resources=[],
            max_plan_iterations=1,
            max_step_num=1,
            max_search_results=5,
            auto_accepted_plan=True,
            interrupt_feedback="",
            mcp_settings={},
            enable_background_investigation=True,
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=True,
            max_clarification_rounds=3,
        )

        with pytest.raises(StopAsyncIteration):
            await generator.__anext__()

    workflow_input = captured_data["workflow_input"]
    assert workflow_input["clarification_history"] == [
        "Research on renewable energy",
        "Solar and wind energy",
        "Technological development",
        "Current status and future trends",
    ]
    assert (
        workflow_input["clarified_research_topic"]
        == "Research on renewable energy - Solar and wind energy, Technological development, Current status and future trends"
    )


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
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": "true"},
    )
    def test_mcp_server_metadata_success(self, mock_load_tools, client):
        mock_load_tools.return_value = [
            {"name": "test_tool", "description": "Test tool"}
        ]

        request_data = {
            "transport": "stdio",
            "command": "node",
            "args": ["server.js"],
            "env": {"API_KEY": "test123"},
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 200
        response_data = response.json()
        assert response_data["transport"] == "stdio"
        assert response_data["command"] == "node"
        assert len(response_data["tools"]) == 1

    @patch("src.server.app.load_mcp_tools")
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": "true"},
    )
    def test_mcp_server_metadata_with_custom_timeout(self, mock_load_tools, client):
        mock_load_tools.return_value = []

        request_data = {
            "transport": "stdio",
            "command": "node",
            "timeout_seconds": 60,
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 200
        mock_load_tools.assert_called_once()
        # Verify timeout_seconds is passed to load_mcp_tools
        call_kwargs = mock_load_tools.call_args[1]
        assert call_kwargs["timeout_seconds"] == 60

    @patch("src.server.app.load_mcp_tools")
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": "true"},
    )
    def test_mcp_server_metadata_with_sse_read_timeout(self, mock_load_tools, client):
        """Test that sse_read_timeout is passed to load_mcp_tools."""
        mock_load_tools.return_value = []

        request_data = {
            "transport": "sse",
            "url": "http://localhost:3000/sse",
            "timeout_seconds": 30,
            "sse_read_timeout": 15,
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 200
        mock_load_tools.assert_called_once()
        # Verify both timeout_seconds and sse_read_timeout are passed
        call_kwargs = mock_load_tools.call_args[1]
        assert call_kwargs["timeout_seconds"] == 30
        assert call_kwargs["sse_read_timeout"] == 15

    @patch("src.server.app.load_mcp_tools")
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": "true"},
    )
    def test_mcp_server_metadata_with_exception(self, mock_load_tools, client):
        mock_load_tools.side_effect = HTTPException(
            status_code=400, detail="MCP Server Error"
        )

        request_data = {
            "transport": "stdio",
            "command": "node",
            "args": ["server.js"],
            "env": {"API_KEY": "test123"},
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"

    @patch("src.server.app.load_mcp_tools")
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": ""},
    )
    def test_mcp_server_metadata_without_enable_configuration(
        self, mock_load_tools, client
    ):
        request_data = {
            "transport": "stdio",
            "command": "node",
            "args": ["server.js"],
            "env": {"API_KEY": "test123"},
        }

        response = client.post("/api/mcp/server/metadata", json=request_data)

        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features."
        )


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

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_success(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.ingest_file.return_value = {
            "uri": "milvus://test/file.md",
            "title": "Test File",
            "description": "Uploaded file",
        }
        mock_build_retriever.return_value = mock_retriever

        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 200
        assert response.json()["title"] == "Test File"
        assert response.json()["uri"] == "milvus://test/file.md"
        mock_retriever.ingest_file.assert_called_once()

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_no_retriever(self, mock_build_retriever, client):
        mock_build_retriever.return_value = None

        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 500
        assert "RAG provider not configured" in response.json()["detail"]

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_not_implemented(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.ingest_file.side_effect = NotImplementedError
        mock_build_retriever.return_value = mock_retriever

        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 501
        assert "Upload not supported" in response.json()["detail"]

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_value_error(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.ingest_file.side_effect = ValueError("File is not valid UTF-8")
        mock_build_retriever.return_value = mock_retriever

        files = {"file": ("test.txt", b"\x80\x81\x82", "text/plain")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 400
        assert "Invalid RAG resource" in response.json()["detail"]

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_runtime_error(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.ingest_file.side_effect = RuntimeError("Failed to insert into Milvus")
        mock_build_retriever.return_value = mock_retriever

        files = {"file": ("test.md", b"# Test content", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 500
        assert "Failed to ingest RAG resource" in response.json()["detail"]

    def test_upload_rag_resource_invalid_file_type(self, client):
        files = {"file": ("test.exe", b"binary content", "application/octet-stream")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 400
        assert "Invalid file type" in response.json()["detail"]

    def test_upload_rag_resource_empty_file(self, client):
        files = {"file": ("test.md", b"", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 400
        assert "empty file" in response.json()["detail"]

    @patch("src.server.app.MAX_UPLOAD_SIZE_BYTES", 10)
    def test_upload_rag_resource_file_too_large(self, client):
        files = {"file": ("test.md", b"x" * 100, "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 413
        assert "File too large" in response.json()["detail"]

    @patch("src.server.app.build_retriever")
    def test_upload_rag_resource_path_traversal_sanitized(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.ingest_file.return_value = {
            "uri": "milvus://test/file.md",
            "title": "Test File",
            "description": "Uploaded file",
        }
        mock_build_retriever.return_value = mock_retriever

        files = {"file": ("../../../etc/passwd.md", b"# Test", "text/markdown")}
        response = client.post("/api/rag/upload", files=files)

        assert response.status_code == 200
        # Verify the filename was sanitized (only basename used)
        mock_retriever.ingest_file.assert_called_once()
        call_args = mock_retriever.ingest_file.call_args
        assert call_args[0][1] == "passwd.md"


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

    @patch("src.server.app.graph")
    def test_chat_stream_with_mcp_settings(self, mock_graph, client):
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
            "mcp_settings": {
                "servers": {
                    "mcp-github-trending": {
                        "transport": "stdio",
                        "command": "uvx",
                        "args": ["mcp-github-trending"],
                        "env": {"MCP_SERVER_ID": "mcp-github-trending"},
                        "enabled_tools": ["get_github_trending_repositories"],
                        "add_to_agents": ["researcher"],
                    }
                }
            },
            "enable_background_investigation": False,
            "report_style": "academic",
        }

        response = client.post("/api/chat/stream", json=request_data)

        assert response.status_code == 403
        assert (
            response.json()["detail"]
            == "MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features."
        )

    @patch("src.server.app.graph")
    @patch.dict(
        os.environ,
        {"ENABLE_MCP_SERVER_CONFIGURATION": "true"},
    )
    def test_chat_stream_with_mcp_settings_enabled(self, mock_graph, client):
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
            "mcp_settings": {
                "servers": {
                    "mcp-github-trending": {
                        "transport": "stdio",
                        "command": "uvx",
                        "args": ["mcp-github-trending"],
                        "env": {"MCP_SERVER_ID": "mcp-github-trending"},
                        "enabled_tools": ["get_github_trending_repositories"],
                        "add_to_agents": ["researcher"],
                    }
                }
            },
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
        )

        events = []
        async for event in generator:
            events.append(event)

    @pytest.mark.asyncio
    @patch("src.server.app.graph")
    async def test_astream_workflow_generator_interrupt_event(self, mock_graph):
        # Mock interrupt data with the new 'id' attribute (LangGraph 1.0+)
        mock_interrupt = MagicMock()
        mock_interrupt.id = "interrupt_id"
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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
            enable_web_search=True,
            report_style=ReportStyle.ACADEMIC,
            enable_deep_thinking=False,
            enable_clarification=False,
            max_clarification_rounds=3,
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


class TestCreateInterruptEvent:
    """Tests for _create_interrupt_event function (Issue #730 fix)."""

    def test_create_interrupt_event_with_id_attribute(self):
        """Test that _create_interrupt_event works with LangGraph 1.0+ Interrupt objects that have 'id' attribute."""
        # Create a mock Interrupt object with the new 'id' attribute (LangGraph 1.0+)
        mock_interrupt = MagicMock()
        mock_interrupt.id = "interrupt-123"
        mock_interrupt.value = "Please review the research plan"

        event_data = {"__interrupt__": [mock_interrupt]}
        thread_id = "thread-456"

        result = _create_interrupt_event(thread_id, event_data)

        # Verify the result is a properly formatted SSE event
        assert "event: interrupt\n" in result
        assert '"thread_id": "thread-456"' in result
        assert '"id": "interrupt-123"' in result
        assert '"content": "Please review the research plan"' in result
        assert '"finish_reason": "interrupt"' in result
        assert '"role": "assistant"' in result

    def test_create_interrupt_event_fallback_to_thread_id(self):
        """Test that _create_interrupt_event falls back to thread_id when 'id' attribute is None."""
        # Create a mock Interrupt object where id is None
        mock_interrupt = MagicMock()
        mock_interrupt.id = None
        mock_interrupt.value = "Plan review needed"

        event_data = {"__interrupt__": [mock_interrupt]}
        thread_id = "thread-789"

        result = _create_interrupt_event(thread_id, event_data)

        # Verify it falls back to thread_id
        assert '"id": "thread-789"' in result
        assert '"thread_id": "thread-789"' in result
        assert '"content": "Plan review needed"' in result

    def test_create_interrupt_event_without_id_attribute(self):
        """Test that _create_interrupt_event handles objects without 'id' attribute (backward compatibility)."""
        # Create a mock object that doesn't have 'id' attribute at all
        class MockInterrupt:
            pass
        mock_interrupt = MockInterrupt()
        mock_interrupt.value = "Waiting for approval"

        event_data = {"__interrupt__": [mock_interrupt]}
        thread_id = "thread-abc"

        result = _create_interrupt_event(thread_id, event_data)

        # Verify it falls back to thread_id when id attribute doesn't exist
        assert '"id": "thread-abc"' in result
        assert '"content": "Waiting for approval"' in result

    def test_create_interrupt_event_options(self):
        """Test that _create_interrupt_event includes correct options."""
        mock_interrupt = MagicMock()
        mock_interrupt.id = "int-001"
        mock_interrupt.value = "Review plan"

        event_data = {"__interrupt__": [mock_interrupt]}
        thread_id = "thread-xyz"

        result = _create_interrupt_event(thread_id, event_data)

        # Verify options are included
        assert '"options":' in result
        assert '"text": "Edit plan"' in result
        assert '"value": "edit_plan"' in result
        assert '"text": "Start research"' in result
        assert '"value": "accepted"' in result

    def test_create_interrupt_event_with_complex_value(self):
        """Test that _create_interrupt_event handles complex content values."""
        mock_interrupt = MagicMock()
        mock_interrupt.id = "int-complex"
        mock_interrupt.value = {"plan": "Research AI", "steps": ["step1", "step2"]}

        event_data = {"__interrupt__": [mock_interrupt]}
        thread_id = "thread-complex"

        result = _create_interrupt_event(thread_id, event_data)

        # Verify complex value is included (will be serialized as JSON)
        assert '"id": "int-complex"' in result
        assert "Research AI" in result or "plan" in result


class TestLifespanFunction:
    """Tests for the lifespan function and global connection pool management (Issue #778).
    
    These tests verify correct initialization, error handling, and cleanup behavior
    for PostgreSQL and MongoDB global connection pools.
    """

    @pytest.mark.asyncio
    @patch.dict(os.environ, {"LANGGRAPH_CHECKPOINT_SAVER": "false"})
    async def test_lifespan_skips_initialization_when_checkpoint_not_configured(self):
        """Verify no pool initialization when LANGGRAPH_CHECKPOINT_SAVER=False."""
        from src.server.app import lifespan

        mock_app = MagicMock()

        with patch("src.server.app.AsyncConnectionPool") as mock_pg_pool:
            async with lifespan(mock_app):
                pass

            mock_pg_pool.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {"LANGGRAPH_CHECKPOINT_SAVER": "true", "LANGGRAPH_CHECKPOINT_DB_URL": ""},
    )
    async def test_lifespan_skips_initialization_when_url_empty(self):
        """Verify no pool initialization when checkpoint URL is empty."""
        from src.server.app import lifespan

        mock_app = MagicMock()

        with patch("src.server.app.AsyncConnectionPool") as mock_pg_pool:
            async with lifespan(mock_app):
                pass

            mock_pg_pool.assert_not_called()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "postgresql://localhost:5432/test",
            "PG_POOL_MIN_SIZE": "2",
            "PG_POOL_MAX_SIZE": "10",
            "PG_POOL_TIMEOUT": "30",
        },
    )
    async def test_lifespan_postgresql_pool_initialization_success(self):
        """Test successful PostgreSQL connection pool initialization."""
        from src.server.app import lifespan

        mock_app = MagicMock()
        mock_pool = MagicMock()
        mock_pool.open = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        with (
            patch("src.server.app.AsyncConnectionPool", return_value=mock_pool),
            patch("src.server.app.AsyncPostgresSaver", return_value=mock_checkpointer),
        ):
            async with lifespan(mock_app):
                pass

            mock_pool.open.assert_called_once()
            mock_checkpointer.setup.assert_called_once()
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "postgresql://localhost:5432/test",
        },
    )
    async def test_lifespan_postgresql_pool_initialization_failure(self):
        """Verify RuntimeError raised when PostgreSQL pool initialization fails."""
        from src.server.app import lifespan

        mock_app = MagicMock()
        mock_pool = MagicMock()
        mock_pool.open = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        with patch("src.server.app.AsyncConnectionPool", return_value=mock_pool):
            with pytest.raises(RuntimeError) as exc_info:
                async with lifespan(mock_app):
                    pass

            assert "PostgreSQL" in str(exc_info.value) or "initialization failed" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
            "MONGO_MIN_POOL_SIZE": "2",
            "MONGO_MAX_POOL_SIZE": "10",
        },
    )
    async def test_lifespan_mongodb_pool_initialization_success(self):
        """Test successful MongoDB connection pool initialization."""
        from src.server.app import lifespan

        mock_app = MagicMock()
        mock_client = MagicMock()
        mock_client.close = MagicMock()

        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        # Create a mock motor module
        mock_motor_asyncio = MagicMock()
        mock_motor_asyncio.AsyncIOMotorClient = MagicMock(return_value=mock_client)

        with (
            patch.dict("sys.modules", {"motor": MagicMock(), "motor.motor_asyncio": mock_motor_asyncio}),
            patch("src.server.app.AsyncMongoDBSaver", return_value=mock_checkpointer),
        ):
            async with lifespan(mock_app):
                pass

            mock_checkpointer.setup.assert_called_once()
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
        },
    )
    async def test_lifespan_mongodb_import_error(self):
        """Verify RuntimeError when motor package is missing."""
        from src.server.app import lifespan

        mock_app = MagicMock()

        with patch.dict("sys.modules", {"motor": None, "motor.motor_asyncio": None}):
            with pytest.raises(RuntimeError) as exc_info:
                async with lifespan(mock_app):
                    pass

            assert "motor" in str(exc_info.value).lower() or "MongoDB" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
        },
    )
    async def test_lifespan_mongodb_connection_failure(self):
        """Verify RuntimeError on MongoDB connection failure."""
        from src.server.app import lifespan

        mock_app = MagicMock()

        # Create a mock motor module that raises an exception
        mock_motor_asyncio = MagicMock()
        mock_motor_asyncio.AsyncIOMotorClient = MagicMock(
            side_effect=Exception("Connection refused")
        )

        with patch.dict("sys.modules", {"motor": MagicMock(), "motor.motor_asyncio": mock_motor_asyncio}):
            with pytest.raises(RuntimeError) as exc_info:
                async with lifespan(mock_app):
                    pass

            assert "MongoDB" in str(exc_info.value) or "initialized" in str(exc_info.value)

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "postgresql://localhost:5432/test",
        },
    )
    async def test_lifespan_postgresql_cleanup_on_shutdown(self):
        """Verify PostgreSQL pool.close() is called during shutdown."""
        from src.server.app import lifespan

        mock_app = MagicMock()
        mock_pool = MagicMock()
        mock_pool.open = AsyncMock()
        mock_pool.close = AsyncMock()

        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        with (
            patch("src.server.app.AsyncConnectionPool", return_value=mock_pool),
            patch("src.server.app.AsyncPostgresSaver", return_value=mock_checkpointer),
        ):
            async with lifespan(mock_app):
                # Verify pool is open during app lifetime
                mock_pool.open.assert_called_once()

            # Verify pool is closed after context exit
            mock_pool.close.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
        },
    )
    async def test_lifespan_mongodb_cleanup_on_shutdown(self):
        """Verify MongoDB client.close() is called during shutdown."""
        from src.server.app import lifespan

        mock_app = MagicMock()
        mock_client = MagicMock()
        mock_client.close = MagicMock()

        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        # Create a mock motor module
        mock_motor_asyncio = MagicMock()
        mock_motor_asyncio.AsyncIOMotorClient = MagicMock(return_value=mock_client)

        with (
            patch.dict("sys.modules", {"motor": MagicMock(), "motor.motor_asyncio": mock_motor_asyncio}),
            patch("src.server.app.AsyncMongoDBSaver", return_value=mock_checkpointer),
        ):
            async with lifespan(mock_app):
                pass

            # Verify client is closed after context exit
            mock_client.close.assert_called_once()


class TestGlobalConnectionPoolUsage:
    """Tests for _astream_workflow_generator using global connection pools (Issue #778).
    
    These tests verify that the workflow generator correctly uses global pools
    when available and falls back to per-request connections when not.
    """

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "postgresql://localhost:5432/test",
        },
    )
    @patch("src.server.app.graph")
    async def test_astream_uses_global_postgresql_pool_when_available(self, mock_graph):
        """Verify global _pg_checkpointer is used when available."""
        mock_checkpointer = MagicMock()

        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        with (
            patch("src.server.app._pg_checkpointer", mock_checkpointer),
            patch("src.server.app._pg_pool", MagicMock()),
            patch("src.server.app._process_initial_messages"),
            patch("src.server.app._stream_graph_events") as mock_stream,
        ):
            mock_stream.return_value = self._empty_async_gen()

            generator = _astream_workflow_generator(
                messages=[{"role": "user", "content": "Hello"}],
                thread_id="test_thread",
                resources=[],
                max_plan_iterations=3,
                max_step_num=10,
                max_search_results=5,
                auto_accepted_plan=True,
                interrupt_feedback="",
                mcp_settings={},
                enable_background_investigation=False,
                enable_web_search=True,
                report_style=ReportStyle.ACADEMIC,
                enable_deep_thinking=False,
                enable_clarification=False,
                max_clarification_rounds=3,
            )

            async for _ in generator:
                pass

            # Verify global checkpointer was assigned to graph
            assert mock_graph.checkpointer == mock_checkpointer

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "postgresql://localhost:5432/test",
        },
    )
    @patch("src.server.app.graph")
    async def test_astream_falls_back_to_per_request_postgresql(self, mock_graph):
        """Verify fallback to per-request connection when _pg_checkpointer is None."""
        mock_pool_instance = MagicMock()
        mock_checkpointer = MagicMock()
        mock_checkpointer.setup = AsyncMock()

        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        with (
            patch("src.server.app._pg_checkpointer", None),
            patch("src.server.app._pg_pool", None),
            patch("src.server.app._process_initial_messages"),
            patch("src.server.app.AsyncConnectionPool") as mock_pool_class,
            patch("src.server.app.AsyncPostgresSaver", return_value=mock_checkpointer),
            patch("src.server.app._stream_graph_events") as mock_stream,
        ):
            mock_pool_class.return_value.__aenter__ = AsyncMock(return_value=mock_pool_instance)
            mock_pool_class.return_value.__aexit__ = AsyncMock()
            mock_stream.return_value = self._empty_async_gen()

            generator = _astream_workflow_generator(
                messages=[{"role": "user", "content": "Hello"}],
                thread_id="test_thread",
                resources=[],
                max_plan_iterations=3,
                max_step_num=10,
                max_search_results=5,
                auto_accepted_plan=True,
                interrupt_feedback="",
                mcp_settings={},
                enable_background_investigation=False,
                enable_web_search=True,
                report_style=ReportStyle.ACADEMIC,
                enable_deep_thinking=False,
                enable_clarification=False,
                max_clarification_rounds=3,
            )

            async for _ in generator:
                pass

            # Verify per-request connection pool was created
            mock_pool_class.assert_called_once()

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
        },
    )
    @patch("src.server.app.graph")
    async def test_astream_uses_global_mongodb_pool_when_available(self, mock_graph):
        """Verify global _mongo_checkpointer is used when available."""
        mock_checkpointer = MagicMock()

        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        with (
            patch("src.server.app._mongo_checkpointer", mock_checkpointer),
            patch("src.server.app._mongo_client", MagicMock()),
            patch("src.server.app._process_initial_messages"),
            patch("src.server.app._stream_graph_events") as mock_stream,
        ):
            mock_stream.return_value = self._empty_async_gen()

            generator = _astream_workflow_generator(
                messages=[{"role": "user", "content": "Hello"}],
                thread_id="test_thread",
                resources=[],
                max_plan_iterations=3,
                max_step_num=10,
                max_search_results=5,
                auto_accepted_plan=True,
                interrupt_feedback="",
                mcp_settings={},
                enable_background_investigation=False,
                enable_web_search=True,
                report_style=ReportStyle.ACADEMIC,
                enable_deep_thinking=False,
                enable_clarification=False,
                max_clarification_rounds=3,
            )

            async for _ in generator:
                pass

            # Verify global checkpointer was assigned to graph
            assert mock_graph.checkpointer == mock_checkpointer

    @pytest.mark.asyncio
    @patch.dict(
        os.environ,
        {
            "LANGGRAPH_CHECKPOINT_SAVER": "true",
            "LANGGRAPH_CHECKPOINT_DB_URL": "mongodb://localhost:27017/test",
        },
    )
    @patch("src.server.app.graph")
    async def test_astream_falls_back_to_per_request_mongodb(self, mock_graph):
        """Verify fallback to per-request connection when _mongo_checkpointer is None."""
        mock_checkpointer = MagicMock()

        async def mock_astream(*args, **kwargs):
            yield ("agent1", "step1", {"test": "data"})

        mock_graph.astream = mock_astream

        with (
            patch("src.server.app._mongo_checkpointer", None),
            patch("src.server.app._mongo_client", None),
            patch("src.server.app._process_initial_messages"),
            patch("src.server.app.AsyncMongoDBSaver") as mock_saver_class,
            patch("src.server.app._stream_graph_events") as mock_stream,
        ):
            mock_saver_class.from_conn_string.return_value.__aenter__ = AsyncMock(
                return_value=mock_checkpointer
            )
            mock_saver_class.from_conn_string.return_value.__aexit__ = AsyncMock()
            mock_stream.return_value = self._empty_async_gen()

            generator = _astream_workflow_generator(
                messages=[{"role": "user", "content": "Hello"}],
                thread_id="test_thread",
                resources=[],
                max_plan_iterations=3,
                max_step_num=10,
                max_search_results=5,
                auto_accepted_plan=True,
                interrupt_feedback="",
                mcp_settings={},
                enable_background_investigation=False,
                enable_web_search=True,
                report_style=ReportStyle.ACADEMIC,
                enable_deep_thinking=False,
                enable_clarification=False,
                max_clarification_rounds=3,
            )

            async for _ in generator:
                pass

            # Verify per-request MongoDB saver was created
            mock_saver_class.from_conn_string.assert_called_once()

    async def _empty_async_gen(self):
        """Helper to create an empty async generator."""
        if False:
            yield
