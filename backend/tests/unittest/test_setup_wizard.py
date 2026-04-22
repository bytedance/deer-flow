"""Unit tests for the Setup Wizard (scripts/wizard/).

Run from repo root:
    cd backend && uv run pytest tests/test_setup_wizard.py -v
"""

from __future__ import annotations

import yaml
from wizard.providers import LLM_PROVIDERS, SEARCH_PROVIDERS, WEB_FETCH_PROVIDERS
from wizard.steps import search as search_step
from wizard.writer import (
    build_minimal_config,
    read_env_file,
    write_config_yaml,
    write_env_file,
)


class TestProviders:
    def test_llm_providers_not_empty(self):
        assert len(LLM_PROVIDERS) >= 8

    def test_llm_providers_have_required_fields(self):
        for p in LLM_PROVIDERS:
            assert p.name
            assert p.display_name
            assert p.use
            assert ":" in p.use, f"Provider '{p.name}' use path must contain ':'"
            assert p.models
            assert p.default_model in p.models

    def test_search_providers_have_required_fields(self):
        for sp in SEARCH_PROVIDERS:
            assert sp.name
            assert sp.display_name
            assert sp.use
            assert ":" in sp.use

    def test_search_and_fetch_include_firecrawl(self):
        assert any(provider.name == "firecrawl" for provider in SEARCH_PROVIDERS)
        assert any(provider.name == "firecrawl" for provider in WEB_FETCH_PROVIDERS)

    def test_web_fetch_providers_have_required_fields(self):
        for provider in WEB_FETCH_PROVIDERS:
            assert provider.name
            assert provider.display_name
            assert provider.use
            assert ":" in provider.use
            assert provider.tool_name == "web_fetch"

    def test_at_least_one_free_search_provider(self):
        """At least one search provider needs no API key."""
        free = [sp for sp in SEARCH_PROVIDERS if sp.env_var is None]
        assert free, "Expected at least one free (no-key) search provider"

    def test_at_least_one_free_web_fetch_provider(self):
        free = [provider for provider in WEB_FETCH_PROVIDERS if provider.env_var is None]
        assert free, "Expected at least one free (no-key) web fetch provider"


class TestBuildMinimalConfig:
    def test_produces_valid_yaml(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        assert data is not None
        assert "models" in data
        assert len(data["models"]) == 1
        model = data["models"][0]
        assert model["name"] == "gpt-4o"
        assert model["use"] == "langchain_openai:ChatOpenAI"
        assert model["model"] == "gpt-4o"
        assert model["api_key"] == "$OPENAI_API_KEY"

    def test_gemini_uses_gemini_api_key_field(self):
        content = build_minimal_config(
            provider_use="langchain_google_genai:ChatGoogleGenerativeAI",
            model_name="gemini-2.0-flash",
            display_name="Gemini",
            api_key_field="gemini_api_key",
            env_var="GEMINI_API_KEY",
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert "gemini_api_key" in model
        assert model["gemini_api_key"] == "$GEMINI_API_KEY"
        assert "api_key" not in model

    def test_search_tool_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            search_use="deerflow.community.tavily.tools:web_search_tool",
            search_extra_config={"max_results": 5},
        )
        data = yaml.safe_load(content)
        search_tool = next(t for t in data.get("tools", []) if t["name"] == "web_search")
        assert search_tool["max_results"] == 5

    def test_openrouter_defaults_are_preserved(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="google/gemini-2.5-flash-preview",
            display_name="OpenRouter",
            api_key_field="api_key",
            env_var="OPENROUTER_API_KEY",
            extra_model_config={
                "base_url": "https://openrouter.ai/api/v1",
                "request_timeout": 600.0,
                "max_retries": 2,
                "max_tokens": 8192,
                "temperature": 0.7,
            },
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert model["base_url"] == "https://openrouter.ai/api/v1"
        assert model["request_timeout"] == 600.0
        assert model["max_retries"] == 2
        assert model["max_tokens"] == 8192
        assert model["temperature"] == 0.7

    def test_web_fetch_tool_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            web_fetch_use="deerflow.community.jina_ai.tools:web_fetch_tool",
            web_fetch_extra_config={"timeout": 10},
        )
        data = yaml.safe_load(content)
        fetch_tool = next(t for t in data.get("tools", []) if t["name"] == "web_fetch")
        assert fetch_tool["timeout"] == 10

    def test_no_search_tool_when_not_configured(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "web_search" not in tool_names
        assert "web_fetch" not in tool_names

    def test_sandbox_included(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        assert "sandbox" in data
        assert "use" in data["sandbox"]
        assert data["sandbox"]["use"] == "deerflow.sandbox.local:LocalSandboxProvider"
        assert data["sandbox"]["allow_host_bash"] is False

    def test_bash_tool_disabled_by_default(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "bash" not in tool_names

    def test_can_enable_container_sandbox_and_bash(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            sandbox_use="deerflow.community.aio_sandbox:AioSandboxProvider",
            include_bash_tool=True,
        )
        data = yaml.safe_load(content)
        assert data["sandbox"]["use"] == "deerflow.community.aio_sandbox:AioSandboxProvider"
        assert "allow_host_bash" not in data["sandbox"]
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "bash" in tool_names

    def test_can_disable_write_tools(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            include_write_tools=False,
        )
        data = yaml.safe_load(content)
        tool_names = [t["name"] for t in data.get("tools", [])]
        assert "write_file" not in tool_names
        assert "str_replace" not in tool_names

    def test_config_version_present(self):
        content = build_minimal_config(
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
            config_version=5,
        )
        data = yaml.safe_load(content)
        assert data["config_version"] == 5

    def test_cli_provider_does_not_emit_fake_api_key(self):
        content = build_minimal_config(
            provider_use="deerflow.models.openai_codex_provider:CodexChatModel",
            model_name="gpt-5.4",
            display_name="Codex CLI",
            api_key_field="api_key",
            env_var=None,
        )
        data = yaml.safe_load(content)
        model = data["models"][0]
        assert "api_key" not in model


# ---------------------------------------------------------------------------
# writer.py — env file helpers
# ---------------------------------------------------------------------------


class TestEnvFileHelpers:
    def test_write_and_read_new_file(self, tmp_path):
        env_file = tmp_path / ".env"
        write_env_file(env_file, {"OPENAI_API_KEY": "sk-test123"})
        pairs = read_env_file(env_file)
        assert pairs["OPENAI_API_KEY"] == "sk-test123"

    def test_update_existing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OPENAI_API_KEY=old-key\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "new-key"})
        pairs = read_env_file(env_file)
        assert pairs["OPENAI_API_KEY"] == "new-key"
        # Should not duplicate
        content = env_file.read_text()
        assert content.count("OPENAI_API_KEY") == 1

    def test_preserve_existing_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("TAVILY_API_KEY=tavily-val\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "sk-new"})
        pairs = read_env_file(env_file)
        assert pairs["TAVILY_API_KEY"] == "tavily-val"
        assert pairs["OPENAI_API_KEY"] == "sk-new"

    def test_preserve_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# My .env file\nOPENAI_API_KEY=old\n")
        write_env_file(env_file, {"OPENAI_API_KEY": "new"})
        content = env_file.read_text()
        assert "# My .env file" in content

    def test_read_ignores_comments(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("# comment\nKEY=value\n")
        pairs = read_env_file(env_file)
        assert "# comment" not in pairs
        assert pairs["KEY"] == "value"


# ---------------------------------------------------------------------------
# writer.py — write_config_yaml
# ---------------------------------------------------------------------------


class TestWriteConfigYaml:
    def test_generated_config_loadable_by_appconfig(self, tmp_path):
        """The generated config.yaml must be parseable (basic YAML validity)."""

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        assert config_path.exists()
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "models" in data

    def test_copies_example_defaults_for_unconfigured_sections(self, tmp_path):
        example_path = tmp_path / "config.example.yaml"
        example_path.write_text(
            yaml.safe_dump(
                {
                    "config_version": 5,
                    "log_level": "info",
                    "token_usage": {"enabled": False},
                    "tool_groups": [{"name": "web"}, {"name": "file:read"}, {"name": "file:write"}, {"name": "bash"}],
                    "tools": [
                        {
                            "name": "web_search",
                            "group": "web",
                            "use": "deerflow.community.ddg_search.tools:web_search_tool",
                            "max_results": 5,
                        },
                        {
                            "name": "web_fetch",
                            "group": "web",
                            "use": "deerflow.community.jina_ai.tools:web_fetch_tool",
                            "timeout": 10,
                        },
                        {
                            "name": "image_search",
                            "group": "web",
                            "use": "deerflow.community.image_search.tools:image_search_tool",
                            "max_results": 5,
                        },
                        {"name": "ls", "group": "file:read", "use": "deerflow.sandbox.tools:ls_tool"},
                        {"name": "write_file", "group": "file:write", "use": "deerflow.sandbox.tools:write_file_tool"},
                        {"name": "bash", "group": "bash", "use": "deerflow.sandbox.tools:bash_tool"},
                    ],
                    "sandbox": {
                        "use": "deerflow.sandbox.local:LocalSandboxProvider",
                        "allow_host_bash": False,
                    },
                    "summarization": {"max_tokens": 2048},
                },
                sort_keys=False,
            )
        )

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI / gpt-4o",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert data["log_level"] == "info"
        assert data["token_usage"]["enabled"] is False
        assert data["tool_groups"][0]["name"] == "web"
        assert data["summarization"]["max_tokens"] == 2048
        assert any(tool["name"] == "image_search" and tool["max_results"] == 5 for tool in data["tools"])

    def test_config_version_read_from_example(self, tmp_path):
        """write_config_yaml should read config_version from config.example.yaml if present."""

        example_path = tmp_path / "config.example.yaml"
        example_path.write_text("config_version: 99\n")

        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="gpt-4o",
            display_name="OpenAI",
            api_key_field="api_key",
            env_var="OPENAI_API_KEY",
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert data["config_version"] == 99

    def test_model_base_url_from_extra_config(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        write_config_yaml(
            config_path,
            provider_use="langchain_openai:ChatOpenAI",
            model_name="google/gemini-2.5-flash-preview",
            display_name="OpenRouter",
            api_key_field="api_key",
            env_var="OPENROUTER_API_KEY",
            extra_model_config={"base_url": "https://openrouter.ai/api/v1"},
        )
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert data["models"][0]["base_url"] == "https://openrouter.ai/api/v1"


class TestSearchStep:
    def test_reuses_api_key_for_same_provider(self, monkeypatch):
        monkeypatch.setattr(search_step, "print_header", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(search_step, "print_success", lambda *_args, **_kwargs: None)
        monkeypatch.setattr(search_step, "print_info", lambda *_args, **_kwargs: None)

        choices = iter([3, 1])
        prompts: list[str] = []

        def fake_choice(_prompt, _options, default=0):
            return next(choices)

        def fake_secret(prompt):
            prompts.append(prompt)
            return "shared-api-key"

        monkeypatch.setattr(search_step, "ask_choice", fake_choice)
        monkeypatch.setattr(search_step, "ask_secret", fake_secret)

        result = search_step.run_search_step()

        assert result.search_provider is not None
        assert result.fetch_provider is not None
        assert result.search_provider.name == "exa"
        assert result.fetch_provider.name == "exa"
        assert result.search_api_key == "shared-api-key"
        assert result.fetch_api_key == "shared-api-key"
        assert prompts == ["EXA_API_KEY"]
