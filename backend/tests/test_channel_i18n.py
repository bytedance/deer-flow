"""Tests for app.channels.i18n localization helpers."""

import pytest

from app.channels.i18n import (
    DEFAULT_LOCALE,
    PT_BR_LOCALE,
    channel_text,
    normalize_channel_locale,
    resolve_message_locale,
)


class TestNormalizeChannelLocale:
    def test_exact_ptbr(self):
        assert normalize_channel_locale("pt-BR") == PT_BR_LOCALE

    def test_exact_enus(self):
        assert normalize_channel_locale("en-US") == DEFAULT_LOCALE

    def test_pt_prefix_short(self):
        assert normalize_channel_locale("pt") == PT_BR_LOCALE

    def test_pt_underscore_variant(self):
        assert normalize_channel_locale("pt_BR") == PT_BR_LOCALE

    def test_pt_portugal(self):
        assert normalize_channel_locale("pt-PT") == PT_BR_LOCALE

    def test_en_prefix_short(self):
        assert normalize_channel_locale("en") == DEFAULT_LOCALE

    def test_en_gb_variant(self):
        assert normalize_channel_locale("en-GB") == DEFAULT_LOCALE

    def test_en_underscore_variant(self):
        assert normalize_channel_locale("en_US") == DEFAULT_LOCALE

    def test_case_insensitive_PT(self):
        assert normalize_channel_locale("PT-BR") == PT_BR_LOCALE

    def test_case_insensitive_EN(self):
        assert normalize_channel_locale("EN-US") == DEFAULT_LOCALE

    def test_none_returns_default(self):
        assert normalize_channel_locale(None) == DEFAULT_LOCALE

    def test_empty_string_returns_default(self):
        assert normalize_channel_locale("") == DEFAULT_LOCALE

    def test_integer_returns_default(self):
        assert normalize_channel_locale(42) == DEFAULT_LOCALE

    def test_unsupported_locale_returns_default(self):
        assert normalize_channel_locale("fr-FR") == DEFAULT_LOCALE

    def test_unsupported_locale_falls_back_to_default_locale_param(self):
        # If raw_locale is unknown but default_locale is pt-BR, use pt-BR
        assert normalize_channel_locale("fr-FR", "pt-BR") == PT_BR_LOCALE

    def test_none_falls_back_to_default_locale_param(self):
        assert normalize_channel_locale(None, "pt-BR") == PT_BR_LOCALE

    def test_invalid_default_locale_falls_to_global_default(self):
        assert normalize_channel_locale(None, None) == DEFAULT_LOCALE

    def test_whitespace_stripped(self):
        assert normalize_channel_locale("  pt-BR  ") == PT_BR_LOCALE


class TestResolveMessageLocale:
    def test_ptbr_from_metadata(self):
        assert resolve_message_locale({"locale": "pt-BR"}) == PT_BR_LOCALE

    def test_enus_from_metadata(self):
        assert resolve_message_locale({"locale": "en-US"}) == DEFAULT_LOCALE

    def test_none_metadata_returns_default(self):
        assert resolve_message_locale(None) == DEFAULT_LOCALE

    def test_empty_metadata_returns_default(self):
        assert resolve_message_locale({}) == DEFAULT_LOCALE

    def test_missing_locale_key_returns_default(self):
        assert resolve_message_locale({"other_key": "value"}) == DEFAULT_LOCALE

    def test_none_locale_value_returns_default(self):
        assert resolve_message_locale({"locale": None}) == DEFAULT_LOCALE

    def test_unsupported_locale_in_metadata_returns_default(self):
        assert resolve_message_locale({"locale": "fr-FR"}) == DEFAULT_LOCALE

    def test_default_locale_param_used_as_fallback(self):
        assert resolve_message_locale({}, default_locale="pt-BR") == PT_BR_LOCALE

    def test_non_mapping_returns_default(self):
        assert resolve_message_locale("not-a-dict") == DEFAULT_LOCALE


class TestChannelText:
    def test_enus_artifact_created_file(self):
        result = channel_text("en-US", "artifact.created_file", filename="report.pdf")
        assert result == "Created File: 📎 report.pdf"

    def test_ptbr_artifact_created_file(self):
        result = channel_text("pt-BR", "artifact.created_file", filename="relatorio.pdf")
        assert result == "Arquivo criado: 📎 relatorio.pdf"

    def test_enus_command_help(self):
        result = channel_text("en-US", "command.help")
        assert "Available commands:" in result
        assert "/help" in result

    def test_ptbr_command_help(self):
        result = channel_text("pt-BR", "command.help")
        assert "Comandos disponiveis" in result
        assert "/help" in result

    def test_ptbr_bootstrap_default(self):
        assert channel_text("pt-BR", "command.bootstrap_default") == "Inicializar workspace"

    def test_enus_bootstrap_default(self):
        assert channel_text("en-US", "command.bootstrap_default") == "Initialize workspace"

    def test_ptbr_running(self):
        assert channel_text("pt-BR", "channel.running") == "Trabalhando nisso..."

    def test_enus_running(self):
        assert channel_text("en-US", "channel.running") == "Working on it..."

    def test_ptbr_telegram_welcome(self):
        result = channel_text("pt-BR", "telegram.welcome")
        assert "Boas-vindas ao DeerFlow" in result

    def test_enus_telegram_welcome(self):
        result = channel_text("en-US", "telegram.welcome")
        assert "Welcome to DeerFlow" in result

    def test_status_active_with_thread_id(self):
        result = channel_text("en-US", "command.status.active", thread_id="abc-123")
        assert "abc-123" in result

    def test_ptbr_status_active_with_thread_id(self):
        result = channel_text("pt-BR", "command.status.active", thread_id="xyz-789")
        assert "xyz-789" in result

    def test_unknown_locale_falls_back_to_enus(self):
        result = channel_text("fr-FR", "channel.running")
        assert result == "Working on it..."

    def test_none_locale_falls_back_to_enus(self):
        result = channel_text(None, "channel.running")
        assert result == "Working on it..."

    def test_pt_short_resolves_to_ptbr(self):
        result = channel_text("pt", "command.bootstrap_default")
        assert result == "Inicializar workspace"

    def test_session_assistant_id_invalid_with_format(self):
        result = channel_text("en-US", "session.assistant_id_invalid", raw_value="bad agent!")
        assert "bad agent!" in result

    def test_ptbr_session_assistant_id_invalid_with_format(self):
        result = channel_text("pt-BR", "session.assistant_id_invalid", raw_value="bad!")
        assert "bad!" in result

    def test_gateway_models_available_with_items(self):
        result = channel_text("en-US", "gateway.models.available", items="- gpt-4\n- claude")
        assert "gpt-4" in result

    def test_ptbr_gateway_models_available(self):
        result = channel_text("pt-BR", "gateway.models.available", items="- modelo-1")
        assert "modelo-1" in result
        assert "Modelos disponiveis" in result
