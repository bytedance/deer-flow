"""All shipped ingress routes must admit the maximum configurable STT body."""

import pytest
from support.nginx_conf import NGINX_CONFIGS, extract_location_block, parse_body_size_bytes, parse_read_timeout_seconds, read_config

from deerflow.config.voice_input_config import VoiceInputConfig


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_audio_route_preserves_recording_limits(path):
    block = extract_location_block(read_config(path), "= /api/voice-input/transcribe")
    config = VoiceInputConfig(base_url="https://speech.example/v1", model="stt", max_audio_bytes=25 * 1024 * 1024, timeout_seconds=120)
    assert parse_body_size_bytes(block) >= config.max_audio_bytes
    assert parse_read_timeout_seconds(block) >= config.timeout_seconds + 30
    assert "proxy_request_buffering off;" in block
    assert "proxy_http_version 1.1;" in block
