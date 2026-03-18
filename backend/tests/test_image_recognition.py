"""Tests for image recognition tool."""

import base64
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from deerflow.community.image_recognition.tools import (
    _download_image,
    _encode_image,
    _is_url,
    _load_local_image,
    image_recognition_tool,
)


class TestImageRecognitionHelpers:
    """Test helper functions."""

    def test_is_url_with_http_url(self):
        """Test URL detection with HTTP URL."""
        assert _is_url("http://example.com/image.jpg") is True

    def test_is_url_with_https_url(self):
        """Test URL detection with HTTPS URL."""
        assert _is_url("https://example.com/image.jpg") is True

    def test_is_url_with_local_path(self):
        """Test URL detection with local path."""
        assert _is_url("/path/to/image.jpg") is False
        assert _is_url("C:\\path\\to\\image.jpg") is False

    def test_is_url_with_relative_path(self):
        """Test URL detection with relative path."""
        assert _is_url("image.jpg") is False
        assert _is_url("./image.jpg") is False

    def test_encode_image(self):
        """Test image encoding to base64."""
        image_bytes = b"fake image data"
        encoded = _encode_image(image_bytes)
        expected = base64.b64encode(image_bytes).decode("utf-8")
        assert encoded == expected


class TestDownloadImage:
    """Test image download functionality."""

    @patch("deerflow.community.image_recognition.tools.requests.get")
    def test_download_image_success(self, mock_get):
        """Test successful image download."""
        mock_response = Mock()
        mock_response.content = b"fake image content"
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        image_bytes, mime_type = _download_image("https://example.com/image.jpg")

        assert image_bytes == b"fake image content"
        assert mime_type == "image/jpeg"
        mock_get.assert_called_once()

    @patch("deerflow.community.image_recognition.tools.requests.get")
    def test_download_image_failure(self, mock_get):
        """Test failed image download."""
        from requests import RequestException

        mock_get.side_effect = RequestException("Connection error")

        with pytest.raises(RequestException):
            _download_image("https://example.com/image.jpg")


class TestLoadLocalImage:
    """Test local image loading functionality."""

    def test_load_local_image_not_absolute_path(self, tmp_path):
        """Test loading image with relative path fails."""
        with pytest.raises(ValueError, match="Path must be absolute"):
            _load_local_image("relative/path/image.jpg")

    def test_load_local_image_not_exists(self, tmp_path):
        """Test loading non-existent image fails."""
        non_existent = tmp_path / "non_existent.jpg"
        with pytest.raises(ValueError, match="Image file not found"):
            _load_local_image(str(non_existent))

    def test_load_local_image_unsupported_format(self, tmp_path):
        """Test loading image with unsupported format fails."""
        image_file = tmp_path / "image.xyz"
        image_file.write_bytes(b"fake content")
        with pytest.raises(ValueError, match="Unsupported image format"):
            _load_local_image(str(image_file))

    def test_load_local_image_success(self, tmp_path):
        """Test successful local image loading."""
        image_file = tmp_path / "test_image.png"
        image_file.write_bytes(b"fake png content")

        image_bytes, mime_type = _load_local_image(str(image_file))

        assert image_bytes == b"fake png content"
        assert mime_type == "image/png"


class TestImageRecognitionTool:
    """Test image recognition tool."""

    def test_tool_with_url(self):
        """Test tool with URL image source."""
        mock_runtime = MagicMock()

        with patch(
            "deerflow.community.image_recognition.tools._is_url", return_value=True
        ), patch(
            "deerflow.community.image_recognition.tools._download_image",
            return_value=(b"fake image", "image/jpeg"),
        ), patch(
            "deerflow.community.image_recognition.tools._analyze_image_with_vision_model"
        ) as mock_analyze:
            mock_analyze.return_value = {
                "analysis_type": "general",
                "model_used": "test-model",
                "description": "A test image description",
            }

            result = image_recognition_tool(
                mock_runtime,
                "https://example.com/image.jpg",
                "tool-call-id-123",
                "general",
                None,
            )

            assert isinstance(result, Command)
            assert "messages" in result.update

    def test_tool_with_local_path(self, tmp_path):
        """Test tool with local image path."""
        mock_runtime = MagicMock()
        image_file = tmp_path / "test.jpg"
        image_file.write_bytes(b"fake jpg content")

        with patch(
            "deerflow.community.image_recognition.tools._is_url", return_value=False
        ), patch(
            "deerflow.community.image_recognition.tools._analyze_image_with_vision_model"
        ) as mock_analyze:
            mock_analyze.return_value = {
                "analysis_type": "general",
                "model_used": "test-model",
                "description": "A test image description",
            }

            result = image_recognition_tool(
                mock_runtime,
                str(image_file),
                "tool-call-id-123",
                "general",
                None,
            )

            assert isinstance(result, Command)
            assert "messages" in result.update

    def test_tool_download_error(self):
        """Test tool handles download errors gracefully."""
        mock_runtime = MagicMock()

        with patch(
            "deerflow.community.image_recognition.tools._is_url", return_value=True
        ), patch(
            "deerflow.community.image_recognition.tools._download_image",
            side_effect=Exception("Download failed"),
        ):
            result = image_recognition_tool(
                mock_runtime,
                "https://example.com/image.jpg",
                "tool-call-id-123",
                "general",
                None,
            )

            assert isinstance(result, Command)
            assert "messages" in result.update
            messages = result.update["messages"]
            assert len(messages) == 1
            assert "Download failed" in messages[0].content

    def test_tool_invalid_local_path(self):
        """Test tool handles invalid local path gracefully."""
        mock_runtime = MagicMock()

        with patch(
            "deerflow.community.image_recognition.tools._is_url", return_value=False
        ):
            result = image_recognition_tool(
                mock_runtime,
                "relative/path.jpg",
                "tool-call-id-123",
                "general",
                None,
            )

            assert isinstance(result, Command)
            assert "messages" in result.update
            messages = result.update["messages"]
            assert len(messages) == 1
            assert "Error loading image" in messages[0].content
