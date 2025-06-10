# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import base64
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from uuid import uuid4
from fastapi.responses import JSONResponse, StreamingResponse
import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException, logger
from src.server.app import app, _make_event, _astream_workflow_generator
from src.server.mcp_request import MCPServerMetadataRequest
from src.server.rag_request import RAGResourceRequest
from src.config.report_style import ReportStyle

from src.server.chat_request import (
    ChatRequest,
    TTSRequest,
    GeneratePodcastRequest,
    GeneratePPTRequest,
    GenerateProseRequest,
    EnhancePromptRequest,
)


@pytest.fixture
def client():
    return TestClient(app)


class TestMakeEvent:
    def test_make_event_with_content(self):
        event_type = "message_chunk"
        data = {"content": "Hello", "role": "assistant"}
        result = _make_event(event_type, data)
        expected = 'event: message_chunk\ndata: {"content": "Hello", "role": "assistant"}\n\n'
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
        expected = 'event: tool_calls\ndata: {"role": "assistant", "tool_calls": []}\n\n'
        assert result == expected


class TestTTSEndpoint:
    @patch.dict(os.environ, {
        "VOLCENGINE_TTS_APPID": "test_app_id",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "test_token",
        "VOLCENGINE_TTS_CLUSTER": "test_cluster",
        "VOLCENGINE_TTS_VOICE_TYPE": "test_voice"
    })
    @patch('src.server.app.VolcengineTTS')
    def test_tts_success(self, mock_tts_class, client):
        mock_tts_instance = MagicMock()
        mock_tts_class.return_value = mock_tts_instance
        
        # Mock successful TTS response
        audio_data_b64 = base64.b64encode(b"fake_audio_data").decode()
        mock_tts_instance.text_to_speech.return_value = {
            "success": True,
            "audio_data": audio_data_b64
        }
        
        request_data = {
            "text": "Hello world",
            "encoding": "mp3",
            "speed_ratio": 1.0,
            "volume_ratio": 1.0,
            "pitch_ratio": 1.0,
            "text_type": "plain",
            "with_frontend": True,
            "frontend_type": "unitTson"
        }
        
        response = client.post("/api/tts", json=request_data)
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mp3"
        assert b"fake_audio_data" in response.content

    @patch.dict(os.environ, {}, clear=True)
    def test_tts_missing_app_id(self, client):
        request_data = {
            "text": "Hello world",
            "encoding": "mp3"
        }
        
        response = client.post("/api/tts", json=request_data)
        
        assert response.status_code == 400
        assert "VOLCENGINE_TTS_APPID is not set" in response.json()["detail"]

    @patch.dict(os.environ, {
        "VOLCENGINE_TTS_APPID": "test_app_id",
        "VOLCENGINE_TTS_ACCESS_TOKEN": ""
    })
    def test_tts_missing_access_token(self, client):
        request_data = {
            "text": "Hello world",
            "encoding": "mp3"
        }

        response = client.post("/api/tts", json=request_data)

        assert response.status_code == 400
        assert "VOLCENGINE_TTS_ACCESS_TOKEN is not set" in response.json()["detail"]

    @patch.dict(os.environ, {
        "VOLCENGINE_TTS_APPID": "test_app_id",
        "VOLCENGINE_TTS_ACCESS_TOKEN": "test_token"
    })
    @patch('src.server.app.VolcengineTTS')
    def test_tts_api_error(self, mock_tts_class, client):
        mock_tts_instance = MagicMock()
        mock_tts_class.return_value = mock_tts_instance
        
        # Mock TTS error response
        mock_tts_instance.text_to_speech.return_value = {
            "success": False,
            "error": "TTS API error"
        }
        
        request_data = {
            "text": "Hello world",
            "encoding": "mp3"
        }
        
        response = client.post("/api/tts", json=request_data)
        
        assert response.status_code == 500
        assert "TTS API error" in response.json()["detail"]


class TestPodcastEndpoint:
    @patch('src.server.app.build_podcast_graph')
    def test_generate_podcast_success(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": b"fake_audio_data"}
        
        request_data = {"content": "Test content for podcast"}
        
        response = client.post("/api/podcast/generate", json=request_data)
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/mp3"
        assert response.content == b"fake_audio_data"

    @patch('src.server.app.build_podcast_graph')
    def test_generate_podcast_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("Podcast generation failed")
        
        request_data = {"content": "Test content"}
        
        response = client.post("/api/podcast/generate", json=request_data)
        
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestPPTEndpoint:
    @patch('src.server.app.build_ppt_graph')
    @patch('builtins.open', new_callable=mock_open, read_data=b"fake_ppt_data")
    def test_generate_ppt_success(self, mock_file, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"generated_file_path": "/fake/path/test.pptx"}
        
        request_data = {"content": "Test content for PPT"}
        
        response = client.post("/api/ppt/generate", json=request_data)
        
        assert response.status_code == 200
        assert "application/vnd.openxmlformats-officedocument.presentationml.presentation" in response.headers["content-type"]
        assert response.content == b"fake_ppt_data"

    @patch('src.server.app.build_ppt_graph')
    def test_generate_ppt_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("PPT generation failed")
        
        request_data = {"content": "Test content"}
        
        response = client.post("/api/ppt/generate", json=request_data)
        
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestEnhancePromptEndpoint:
    @patch('src.server.app.build_prompt_enhancer_graph')
    def test_enhance_prompt_success(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": "Enhanced prompt"}
        
        request_data = {
            "prompt": "Original prompt",
            "context": "Some context",
            "report_style": "academic"
        }
        
        response = client.post("/api/prompt/enhance", json=request_data)
        
        assert response.status_code == 200
        assert response.json()["result"] == "Enhanced prompt"

    @patch('src.server.app.build_prompt_enhancer_graph')
    def test_enhance_prompt_with_different_styles(self, mock_build_graph, client):
        mock_workflow = MagicMock()
        mock_build_graph.return_value = mock_workflow
        mock_workflow.invoke.return_value = {"output": "Enhanced prompt"}
        
        styles = ["ACADEMIC", "popular_science", "NEWS", "social_media", "invalid_style"]
        
        for style in styles:
            request_data = {
                "prompt": "Test prompt",
                "report_style": style
            }
            
            response = client.post("/api/prompt/enhance", json=request_data)
            assert response.status_code == 200

    @patch('src.server.app.build_prompt_enhancer_graph')
    def test_enhance_prompt_error(self, mock_build_graph, client):
        mock_build_graph.side_effect = Exception("Enhancement failed")
        
        request_data = {"prompt": "Test prompt"}
        
        response = client.post("/api/prompt/enhance", json=request_data)
        
        assert response.status_code == 500
        assert response.json()["detail"] == "Internal Server Error"


class TestMCPEndpoint:
    @patch('src.server.app.load_mcp_tools')
    def test_mcp_server_metadata_success(self, mock_load_tools, client):
        mock_load_tools.return_value = [{"name": "test_tool", "description": "Test tool"}]
        
        request_data = {
            "transport": "stdio",
            "command": "test_command",
            "args": ["arg1", "arg2"],
            "env": {"ENV_VAR": "value"}
        }
        
        response = client.post("/api/mcp/server/metadata", json=request_data)
        
        assert response.status_code == 200
        response_data = response.json()
        assert response_data["transport"] == "stdio"
        assert response_data["command"] == "test_command"
        assert len(response_data["tools"]) == 1

    @patch('src.server.app.load_mcp_tools')
    def test_mcp_server_metadata_with_custom_timeout(self, mock_load_tools, client):
        mock_load_tools.return_value = []
        
        request_data = {
            "transport": "stdio",
            "command": "test_command",
            "timeout_seconds": 600
        }
        
        response = client.post("/api/mcp/server/metadata", json=request_data)
        
        assert response.status_code == 200
        mock_load_tools.assert_called_once()


class TestRAGEndpoints:
    @patch('src.server.app.SELECTED_RAG_PROVIDER', 'test_provider')
    def test_rag_config(self, client):
        response = client.get("/api/rag/config")
        
        assert response.status_code == 200
        assert response.json()["provider"] == "test_provider"

    @patch('src.server.app.build_retriever')
    def test_rag_resources_with_retriever(self, mock_build_retriever, client):
        mock_retriever = MagicMock()
        mock_retriever.list_resources.return_value = [{
            "uri": "test_uri",
            "title": "Test Resource",
            "description": "Test Description"
        }]
        mock_build_retriever.return_value = mock_retriever
        
        response = client.get("/api/rag/resources?query=test")
        
        assert response.status_code == 200
        assert len(response.json()["resources"]) == 1

    @patch('src.server.app.build_retriever')
    def test_rag_resources_without_retriever(self, mock_build_retriever, client):
        mock_build_retriever.return_value = None
        
        response = client.get("/api/rag/resources")
        
        assert response.status_code == 200
        assert response.json()["resources"] == []


class TestChatStreamEndpoint:
    @patch('src.server.app.graph')
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
            "report_style": "academic"
        }
        
        response = client.post("/api/chat/stream", json=request_data)
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

