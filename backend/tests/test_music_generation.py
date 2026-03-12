"""Tests for the ElevenLabs music generation tool."""

import importlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

tool_module = importlib.import_module("src.community.music_generation.tools")
music_tool = tool_module.generate_music_tool


def _make_runtime(sandbox_id="local", thread_data=None):
    return SimpleNamespace(
        state={
            "sandbox": {"sandbox_id": sandbox_id},
            "thread_data": thread_data or {
                "workspace_path": "/tmp/workspace",
                "uploads_path": "/tmp/uploads",
                "outputs_path": "/tmp/outputs",
            },
        },
        context={"thread_id": "test-thread"},
    )


@pytest.fixture(autouse=True)
def _patch_sandbox(monkeypatch):
    monkeypatch.setattr(tool_module, "ensure_sandbox_initialized", lambda runtime: None)
    monkeypatch.setattr(tool_module, "ensure_thread_directories_exist", lambda runtime: None)
    monkeypatch.setattr(tool_module, "is_local_sandbox", lambda runtime: True)
    monkeypatch.setattr(tool_module, "get_thread_data", lambda runtime: {
        "workspace_path": "/tmp/workspace",
        "uploads_path": "/tmp/uploads",
        "outputs_path": "/tmp/outputs",
    })


def _call_tool(runtime=None, **kwargs):
    if runtime is None:
        runtime = _make_runtime()
    return music_tool.func(runtime=runtime, **kwargs)


class TestGenerateMusicTool:
    def test_tool_has_correct_name(self):
        assert music_tool.name == "generate_music"

    def test_tool_has_description(self):
        assert "music" in music_tool.description.lower()
        assert "ElevenLabs" in music_tool.description

    def test_missing_api_key(self, monkeypatch):
        monkeypatch.setattr(tool_module, "_get_elevenlabs_api_key", lambda: None)
        result = _call_tool(prompt="jazz piano")
        assert "Error" in result
        assert "ELEVENLABS_API_KEY" in result

    def test_successful_generation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tool_module, "_get_elevenlabs_api_key", lambda: "test-key")

        # Mock path translation to use tmp_path
        monkeypatch.setattr(tool_module, "replace_virtual_path", lambda path, td: str(tmp_path / "output.mp3"))

        mock_client = MagicMock()
        mock_client.music.compose.return_value = iter([b"\x00" * 1024, b"\x00" * 512])

        with patch.object(tool_module, "ElevenLabs", return_value=mock_client, create=True):
            # Patch the import inside the function
            import sys
            mock_elevenlabs_module = MagicMock()
            mock_elevenlabs_module.client.ElevenLabs = MagicMock(return_value=mock_client)
            monkeypatch.setitem(sys.modules, "elevenlabs", mock_elevenlabs_module)
            monkeypatch.setitem(sys.modules, "elevenlabs.client", mock_elevenlabs_module.client)

            result = _call_tool(prompt="jazz piano ballad", duration_seconds=30)

        assert "successfully" in result
        assert "present_files" in result
        mock_client.music.compose.assert_called_once()
        call_kwargs = mock_client.music.compose.call_args[1]
        assert call_kwargs["prompt"] == "jazz piano ballad"
        assert call_kwargs["music_length_ms"] == 30000
        assert call_kwargs["force_instrumental"] is False

    def test_instrumental_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tool_module, "_get_elevenlabs_api_key", lambda: "test-key")
        monkeypatch.setattr(tool_module, "replace_virtual_path", lambda path, td: str(tmp_path / "output.mp3"))

        mock_client = MagicMock()
        mock_client.music.compose.return_value = iter([b"\x00" * 256])

        import sys
        mock_elevenlabs_module = MagicMock()
        mock_elevenlabs_module.client.ElevenLabs = MagicMock(return_value=mock_client)
        monkeypatch.setitem(sys.modules, "elevenlabs", mock_elevenlabs_module)
        monkeypatch.setitem(sys.modules, "elevenlabs.client", mock_elevenlabs_module.client)

        _call_tool(prompt="ambient synth pad", instrumental=True)

        call_kwargs = mock_client.music.compose.call_args[1]
        assert call_kwargs["force_instrumental"] is True

    def test_duration_clamped(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tool_module, "_get_elevenlabs_api_key", lambda: "test-key")
        monkeypatch.setattr(tool_module, "replace_virtual_path", lambda path, td: str(tmp_path / "output.mp3"))

        mock_client = MagicMock()
        mock_client.music.compose.return_value = iter([b"\x00" * 256])

        import sys
        mock_elevenlabs_module = MagicMock()
        mock_elevenlabs_module.client.ElevenLabs = MagicMock(return_value=mock_client)
        monkeypatch.setitem(sys.modules, "elevenlabs", mock_elevenlabs_module)
        monkeypatch.setitem(sys.modules, "elevenlabs.client", mock_elevenlabs_module.client)

        # Duration above max should be clamped to 300
        _call_tool(prompt="test", duration_seconds=999)
        call_kwargs = mock_client.music.compose.call_args[1]
        assert call_kwargs["music_length_ms"] == 300000

    def test_empty_audio_returns_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tool_module, "_get_elevenlabs_api_key", lambda: "test-key")
        monkeypatch.setattr(tool_module, "replace_virtual_path", lambda path, td: str(tmp_path / "output.mp3"))

        mock_client = MagicMock()
        mock_client.music.compose.return_value = iter([])  # Empty

        import sys
        mock_elevenlabs_module = MagicMock()
        mock_elevenlabs_module.client.ElevenLabs = MagicMock(return_value=mock_client)
        monkeypatch.setitem(sys.modules, "elevenlabs", mock_elevenlabs_module)
        monkeypatch.setitem(sys.modules, "elevenlabs.client", mock_elevenlabs_module.client)

        result = _call_tool(prompt="test")
        assert "Error" in result
        assert "no audio data" in result
