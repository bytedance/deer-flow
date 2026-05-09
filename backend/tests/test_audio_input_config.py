from deerflow.config.audio_input_config import (
    AudioInputConfig,
    load_audio_input_config_from_dict,
    reset_audio_input_config,
)


def teardown_function() -> None:
    reset_audio_input_config()


def test_audio_input_config_defaults() -> None:
    config = AudioInputConfig()

    assert config.enabled is False
    assert config.microphone_enabled is True
    assert config.file_transcription_enabled is False
    assert config.default_locale == "zh-CN"
    assert config.supported_locales == ["zh-CN", "en-US"]
    assert "audio/mpeg" in config.accepted_mime_types
    assert config.max_file_size == 25 * 1024 * 1024
    assert (
        config.provider.use
        == "deerflow.audio.providers.openai:OpenAITranscriptionProvider"
    )


def test_load_audio_input_config_from_dict_parses_provider_settings() -> None:
    config = load_audio_input_config_from_dict(
        {
            "enabled": True,
            "file_transcription_enabled": True,
            "supported_locales": ["en-US"],
            "accepted_mime_types": ["audio/webm"],
            "provider": {
                "use": "tests.fake:Provider",
                "config": {"model": "demo-model"},
            },
        }
    )

    assert config.enabled is True
    assert config.file_transcription_enabled is True
    assert config.supported_locales == ["en-US"]
    assert config.accepted_mime_types == ["audio/webm"]
    assert config.provider.use == "tests.fake:Provider"
    assert config.provider.config == {"model": "demo-model"}
