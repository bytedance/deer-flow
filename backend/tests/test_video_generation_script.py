"""Tests for the video generation skill script."""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add skills path so we can import the script
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "skills", "public", "video-generation", "scripts")
sys.path.insert(0, SCRIPT_PATH)

import generate as gen_module


@pytest.fixture
def prompt_file(tmp_path):
    """Create a temporary prompt file."""
    p = tmp_path / "prompt.json"
    p.write_text(json.dumps({"title": "Test video", "description": "A test scene"}))
    return str(p)


@pytest.fixture
def reference_image(tmp_path):
    """Create a temporary reference image."""
    img = tmp_path / "ref.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # Minimal JPEG header
    return str(img)


class TestGenerateVideoSeedance:
    def test_text_to_video(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video_seedance(prompt_file, [], output_file)

        assert "successfully" in result
        mock_fal.subscribe.assert_called_once()
        call_args = mock_fal.subscribe.call_args
        assert "seedance" in call_args[0][0]
        assert "text-to-video" in call_args[0][0]

    def test_image_to_video(self, prompt_file, reference_image, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.upload_file.return_value = "https://fal.ai/uploaded/ref.jpg"
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video_seedance(prompt_file, [reference_image], output_file)

        assert "successfully" in result
        mock_fal.upload_file.assert_called_once_with(reference_image)
        call_args = mock_fal.subscribe.call_args
        assert "image-to-video" in call_args[0][0]
        assert call_args[1]["arguments"]["image_url"] == "https://fal.ai/uploaded/ref.jpg"

    def test_missing_fal_key(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        output_file = str(tmp_path / "out.mp4")
        result = gen_module.generate_video_seedance(prompt_file, [], output_file)
        assert "FAL_KEY is not set" in result

    def test_valid_aspect_ratios(self, prompt_file, tmp_path, monkeypatch):
        """Seedance supports more aspect ratios than Kling."""
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        # 4:3 is valid for Seedance but not for Kling
        gen_module.generate_video_seedance(prompt_file, [], output_file, aspect_ratio="4:3")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["aspect_ratio"] == "4:3"

    def test_invalid_aspect_ratio_defaults(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_seedance(prompt_file, [], output_file, aspect_ratio="5:4")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["aspect_ratio"] == "16:9"

    def test_duration_range(self, prompt_file, tmp_path, monkeypatch):
        """Seedance supports 4-12 second durations."""
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_seedance(prompt_file, [], output_file, duration="8")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["duration"] == 8  # int, not string

    def test_duration_out_of_range_defaults(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_seedance(prompt_file, [], output_file, duration="20")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["duration"] == 5  # Defaults to 5

    def test_audio_enabled_by_default(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_seedance(prompt_file, [], output_file)
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["generate_audio"] is True

    def test_audio_disabled(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_seedance(prompt_file, [], output_file, generate_audio=False)
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["generate_audio"] is False


class TestGenerateVideoKling:
    def test_text_to_video(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video_kling(prompt_file, [], output_file)

        assert "successfully" in result
        mock_fal.subscribe.assert_called_once()
        call_args = mock_fal.subscribe.call_args
        assert "text-to-video" in call_args[0][0]

    def test_image_to_video(self, prompt_file, reference_image, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.upload_file.return_value = "https://fal.ai/uploaded/ref.jpg"
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video_kling(prompt_file, [reference_image], output_file)

        assert "successfully" in result
        mock_fal.upload_file.assert_called_once_with(reference_image)
        call_args = mock_fal.subscribe.call_args
        assert "image-to-video" in call_args[0][0]
        assert call_args[1]["arguments"]["image_url"] == "https://fal.ai/uploaded/ref.jpg"

    def test_missing_fal_key(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.delenv("FAL_KEY", raising=False)
        output_file = str(tmp_path / "out.mp4")
        result = gen_module.generate_video_kling(prompt_file, [], output_file)
        assert "FAL_KEY is not set" in result

    def test_invalid_aspect_ratio_defaults(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_kling(prompt_file, [], output_file, aspect_ratio="4:3")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["aspect_ratio"] == "16:9"  # Defaults to 16:9

    def test_duration_10(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_kling(prompt_file, [], output_file, duration="10")
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["duration"] == "10"


class TestAudioGeneration:
    def test_audio_enabled_by_default(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_kling(prompt_file, [], output_file)
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["generate_audio"] is True

    def test_audio_disabled(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video_kling(prompt_file, [], output_file, generate_audio=False)
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["generate_audio"] is False

    def test_audio_passed_through_generate_video(self, prompt_file, tmp_path, monkeypatch):
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        gen_module.generate_video(prompt_file, [], output_file, model="seedance", generate_audio=False)
        call_args = mock_fal.subscribe.call_args[1]["arguments"]
        assert call_args["generate_audio"] is False


class TestModelSelection:
    def test_default_is_seedance(self, prompt_file, tmp_path, monkeypatch):
        """generate_video with default model should call seedance."""
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video(prompt_file, [], output_file)
        assert "successfully" in result
        mock_fal.subscribe.assert_called_once()
        # Verify it called seedance endpoint
        call_args = mock_fal.subscribe.call_args
        assert "seedance" in call_args[0][0]

    def test_kling_model(self, prompt_file, tmp_path, monkeypatch):
        """generate_video with model=kling should call kling."""
        monkeypatch.setenv("FAL_KEY", "test-key")
        output_file = str(tmp_path / "out.mp4")

        mock_fal = MagicMock()
        mock_fal.subscribe.return_value = {"video": {"url": "https://example.com/v.mp4"}}
        monkeypatch.setitem(sys.modules, "fal_client", mock_fal)

        def fake_retrieve(url, path):
            with open(path, "wb") as f:
                f.write(b"\x00" * 512)

        monkeypatch.setattr(gen_module.urllib.request, "urlretrieve", fake_retrieve)

        result = gen_module.generate_video(prompt_file, [], output_file, model="kling")
        assert "successfully" in result
        call_args = mock_fal.subscribe.call_args
        assert "kling" in call_args[0][0]

    def test_veo3_uses_gemini(self, prompt_file, tmp_path, monkeypatch):
        """generate_video with model=veo3 should call Gemini API."""
        monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
        output_file = str(tmp_path / "out.mp4")

        # Mock the requests module used by veo3
        mock_post_response = MagicMock()
        mock_post_response.json.return_value = {"name": "operations/123"}

        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {
            "done": True,
            "response": {
                "generateVideoResponse": {
                    "generatedSamples": [{"video": {"uri": "https://gemini.example.com/video.mp4"}}]
                }
            },
        }

        mock_download_response = MagicMock()
        mock_download_response.content = b"\x00" * 1024

        with patch.object(gen_module.requests, "post", return_value=mock_post_response) as mock_post, \
             patch.object(gen_module.requests, "get", side_effect=[mock_get_response, mock_download_response]):
            result = gen_module.generate_video(prompt_file, [], output_file, model="veo3")

        assert "successfully" in result
        mock_post.assert_called_once()
        assert "veo-3.1" in mock_post.call_args[0][0]
