# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
from unittest.mock import patch, MagicMock
import base64

from src.tools.tts import VolcengineTTS


class TestVolcengineTTS:
    """Test suite for the VolcengineTTS class."""

    def test_initialization(self):
        """Test that VolcengineTTS can be properly initialized."""
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
            cluster="test_cluster",
            voice_type="test_voice",
            host="test.host.com",
        )

        assert tts.appid == "test_appid"
        assert tts.access_token == "test_token"
        assert tts.cluster == "test_cluster"
        assert tts.voice_type == "test_voice"
        assert tts.host == "test.host.com"
        assert tts.api_url == "https://test.host.com/api/v1/tts"
        assert tts.header == {"Authorization": "Bearer;test_token"}

    def test_initialization_with_defaults(self):
        """Test initialization with default values."""
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        assert tts.appid == "test_appid"
        assert tts.access_token == "test_token"
        assert tts.cluster == "volcano_tts"
        assert tts.voice_type == "BV700_V2_streaming"
        assert tts.host == "openspeech.bytedance.com"
        assert tts.api_url == "https://openspeech.bytedance.com/api/v1/tts"

    @patch("src.tools.tts.requests.post")
    def test_text_to_speech_success(self, mock_post):
        """Test successful text-to-speech conversion."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Create a base64 encoded string for the mock audio data
        mock_audio_data = base64.b64encode(b"audio_data").decode()
        mock_response.json.return_value = {
            "code": 0,
            "message": "success",
            "data": mock_audio_data,
        }
        mock_post.return_value = mock_response

        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        # Call the method
        result = tts.text_to_speech("Hello, world!")

        # Verify the result
        assert result["success"] is True
        assert result["audio_data"] == mock_audio_data
        assert "response" in result

        # Verify the request
        mock_post.assert_called_once()
        args, _ = mock_post.call_args
        assert args[0] == "https://openspeech.bytedance.com/api/v1/tts"

        # Verify request JSON - the data is passed as the second positional argument
        request_json = json.loads(args[1])
        assert request_json["app"]["appid"] == "test_appid"
        assert request_json["app"]["token"] == "test_token"
        assert request_json["app"]["cluster"] == "volcano_tts"
        assert request_json["audio"]["voice_type"] == "BV700_V2_streaming"
        assert request_json["audio"]["encoding"] == "mp3"
        assert request_json["request"]["text"] == "Hello, world!"

    @patch("src.tools.tts.requests.post")
    def test_text_to_speech_api_error(self, mock_post):
        """Test error handling when API returns an error."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "code": 400,
            "message": "Bad request",
        }
        mock_post.return_value = mock_response

        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        # Call the method
        result = tts.text_to_speech("Hello, world!")

        # Verify the result
        assert result["success"] is False
        assert result["error"] == {"code": 400, "message": "Bad request"}
        assert result["audio_data"] is None

    @patch("src.tools.tts.requests.post")
    def test_text_to_speech_no_data(self, mock_post):
        """Test error handling when API response doesn't contain data."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": 0,
            "message": "success",
            # No data field
        }
        mock_post.return_value = mock_response

        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        # Call the method
        result = tts.text_to_speech("Hello, world!")

        # Verify the result
        assert result["success"] is False
        assert result["error"] == "No audio data returned"
        assert result["audio_data"] is None

    @patch("src.tools.tts.requests.post")
    def test_text_to_speech_with_custom_parameters(self, mock_post):
        """Test text_to_speech with custom parameters."""
        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Create a base64 encoded string for the mock audio data
        mock_audio_data = base64.b64encode(b"audio_data").decode()
        mock_response.json.return_value = {
            "code": 0,
            "message": "success",
            "data": mock_audio_data,
        }
        mock_post.return_value = mock_response

        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        # Call the method with custom parameters
        result = tts.text_to_speech(
            text="Custom text",
            encoding="wav",
            speed_ratio=1.2,
            volume_ratio=0.8,
            pitch_ratio=1.1,
            text_type="ssml",
            with_frontend=0,
            frontend_type="custom",
            uid="custom-uid",
        )

        # Verify the result
        assert result["success"] is True
        assert result["audio_data"] == mock_audio_data

        # Verify request JSON - the data is passed as the second positional argument
        args, kwargs = mock_post.call_args
        request_json = json.loads(args[1])
        assert request_json["audio"]["encoding"] == "wav"
        assert request_json["audio"]["speed_ratio"] == 1.2
        assert request_json["audio"]["volume_ratio"] == 0.8
        assert request_json["audio"]["pitch_ratio"] == 1.1
        assert request_json["request"]["text"] == "Custom text"
        assert request_json["request"]["text_type"] == "ssml"
        assert request_json["request"]["with_frontend"] == 0
        assert request_json["request"]["frontend_type"] == "custom"
        assert request_json["user"]["uid"] == "custom-uid"

    @patch("src.tools.tts.requests.post")
    @patch("src.tools.tts.uuid.uuid4")
    def test_text_to_speech_auto_generated_uid(self, mock_uuid, mock_post):
        """Test that UUID is auto-generated if not provided."""
        # Mock UUID
        mock_uuid_value = "test-uuid-value"
        mock_uuid.return_value = mock_uuid_value

        # Mock response
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Create a base64 encoded string for the mock audio data
        mock_audio_data = base64.b64encode(b"audio_data").decode()
        mock_response.json.return_value = {
            "code": 0,
            "message": "success",
            "data": mock_audio_data,
        }
        mock_post.return_value = mock_response

        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )

        # Call the method without providing a UID
        result = tts.text_to_speech("Hello, world!")

        # Verify the result
        assert result["success"] is True
        assert result["audio_data"] == mock_audio_data

        # Verify the request JSON - the data is passed as the second positional argument
        args, kwargs = mock_post.call_args
        request_json = json.loads(args[1])
        assert request_json["user"]["uid"] == str(mock_uuid_value)

    @patch("src.tools.tts.requests.post")
    def test_text_to_speech_request_exception(self, mock_post):
        """Test error handling when requests.post raises an exception."""
        # Mock requests.post to raise an exception
        mock_post.side_effect = Exception("Network error")
        # Create TTS client
        tts = VolcengineTTS(
            appid="test_appid",
            access_token="test_token",
        )
        # Call the method
        result = tts.text_to_speech("Hello, world!")
        # Verify the result
        assert result["success"] is False
        # The TTS error is caught and returned as a string
        assert result["error"] == "TTS API call error"
        assert result["audio_data"] is None
