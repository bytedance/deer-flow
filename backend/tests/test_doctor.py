"""Unit tests for scripts/doctor.py.

Run from repo root:
    cd backend && uv run pytest tests/test_doctor.py -v
"""

from __future__ import annotations

import sys

import doctor

# ---------------------------------------------------------------------------
# check_python
# ---------------------------------------------------------------------------


class TestCheckPython:
    def test_current_python_passes(self):
        result = doctor.check_python()
        assert sys.version_info >= (3, 12)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_config_exists
# ---------------------------------------------------------------------------


class TestCheckConfigExists:
    def test_missing_config(self, tmp_path):
        result = doctor.check_config_exists(tmp_path / "config.yaml")
        assert result.status == "fail"
        assert result.fix is not None

    def test_present_config(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        result = doctor.check_config_exists(cfg)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_config_version
# ---------------------------------------------------------------------------


class TestCheckConfigVersion:
    def test_up_to_date(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        example = tmp_path / "config.example.yaml"
        example.write_text("config_version: 5\n")
        result = doctor.check_config_version(cfg, tmp_path)
        assert result.status == "ok"

    def test_outdated(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 3\n")
        example = tmp_path / "config.example.yaml"
        example.write_text("config_version: 5\n")
        result = doctor.check_config_version(cfg, tmp_path)
        assert result.status == "warn"
        assert result.fix is not None

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_config_version(tmp_path / "config.yaml", tmp_path)
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# check_config_loadable
# ---------------------------------------------------------------------------


class TestCheckConfigLoadable:
    def test_loadable_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        monkeypatch.setattr(doctor, "_load_app_config", lambda _path: object())
        result = doctor.check_config_loadable(cfg)
        assert result.status == "ok"

    def test_invalid_config(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")

        def fail(_path):
            raise ValueError("bad config")

        monkeypatch.setattr(doctor, "_load_app_config", fail)
        result = doctor.check_config_loadable(cfg)
        assert result.status == "fail"
        assert "bad config" in result.detail


# ---------------------------------------------------------------------------
# check_models_configured
# ---------------------------------------------------------------------------


class TestCheckModelsConfigured:
    def test_no_models(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels: []\n")
        result = doctor.check_models_configured(cfg)
        assert result.status == "fail"

    def test_one_model(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        result = doctor.check_models_configured(cfg)
        assert result.status == "ok"

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_models_configured(tmp_path / "config.yaml")
        assert result.status == "skip"


# ---------------------------------------------------------------------------
# check_llm_api_key
# ---------------------------------------------------------------------------


class TestCheckLLMApiKey:
    def test_key_set(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        results = doctor.check_llm_api_key(cfg)
        assert any(r.status == "ok" for r in results)
        assert all(r.status != "fail" for r in results)

    def test_key_missing(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\n")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        results = doctor.check_llm_api_key(cfg)
        assert any(r.status == "fail" for r in results)
        failed = [r for r in results if r.status == "fail"]
        assert all(r.fix is not None for r in failed)
        assert any("OPENAI_API_KEY" in (r.fix or "") for r in failed)

    def test_missing_config_returns_empty(self, tmp_path):
        results = doctor.check_llm_api_key(tmp_path / "config.yaml")
        assert results == []


# ---------------------------------------------------------------------------
# check_llm_auth
# ---------------------------------------------------------------------------


class TestCheckLLMAuth:
    def test_codex_auth_file_missing_fails(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: codex\n    use: deerflow.models.openai_codex_provider:CodexChatModel\n    model: gpt-5.4\n")
        monkeypatch.setenv("CODEX_AUTH_PATH", str(tmp_path / "missing-auth.json"))
        results = doctor.check_llm_auth(cfg)
        assert any(result.status == "fail" and "Codex CLI auth available" in result.label for result in results)

    def test_claude_oauth_env_passes(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nmodels:\n  - name: claude\n    use: deerflow.models.claude_provider:ClaudeChatModel\n    model: claude-sonnet-4-6\n")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "token")
        results = doctor.check_llm_auth(cfg)
        assert any(result.status == "ok" and "Claude auth available" in result.label for result in results)


# ---------------------------------------------------------------------------
# check_web_search
# ---------------------------------------------------------------------------


class TestCheckWebSearch:
    def test_ddg_always_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(
            "config_version: 5\nmodels:\n  - name: default\n    use: langchain_openai:ChatOpenAI\n    model: gpt-4o\n    api_key: $OPENAI_API_KEY\ntools:\n  - name: web_search\n    use: deerflow.community.ddg_search.tools:web_search_tool\n"
        )
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"
        assert "DuckDuckGo" in result.detail

    def test_tavily_with_key_ok(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.tavily.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "ok"

    def test_tavily_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.tavily.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None
        assert "make setup" in result.fix

    def test_no_search_tool_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools: []\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "warn"
        assert result.fix is not None
        assert "make setup" in result.fix

    def test_missing_config_skipped(self, tmp_path):
        result = doctor.check_web_search(tmp_path / "config.yaml")
        assert result.status == "skip"

    def test_invalid_provider_use_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_search\n    use: deerflow.community.not_real.tools:web_search_tool\n")
        result = doctor.check_web_search(cfg)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# check_web_fetch
# ---------------------------------------------------------------------------


class TestCheckWebFetch:
    def test_jina_always_ok(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.jina_ai.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "ok"
        assert "Jina AI" in result.detail

    def test_firecrawl_without_key_warns(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.firecrawl.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "warn"
        assert "FIRECRAWL_API_KEY" in (result.fix or "")

    def test_no_fetch_tool_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools: []\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "warn"
        assert result.fix is not None

    def test_invalid_provider_use_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\ntools:\n  - name: web_fetch\n    use: deerflow.community.not_real.tools:web_fetch_tool\n")
        result = doctor.check_web_fetch(cfg)
        assert result.status == "fail"


# ---------------------------------------------------------------------------
# check_env_file
# ---------------------------------------------------------------------------


class TestCheckEnvFile:
    def test_missing(self, tmp_path):
        result = doctor.check_env_file(tmp_path)
        assert result.status == "warn"

    def test_present(self, tmp_path):
        (tmp_path / ".env").write_text("KEY=val\n")
        result = doctor.check_env_file(tmp_path)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_frontend_env
# ---------------------------------------------------------------------------


class TestCheckFrontendEnv:
    def test_missing(self, tmp_path):
        result = doctor.check_frontend_env(tmp_path)
        assert result.status == "warn"

    def test_present(self, tmp_path):
        frontend_dir = tmp_path / "frontend"
        frontend_dir.mkdir()
        (frontend_dir / ".env").write_text("KEY=val\n")
        result = doctor.check_frontend_env(tmp_path)
        assert result.status == "ok"


# ---------------------------------------------------------------------------
# check_sandbox
# ---------------------------------------------------------------------------


class TestCheckSandbox:
    def test_missing_sandbox_fails(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\n")
        results = doctor.check_sandbox(cfg)
        assert results[0].status == "fail"

    def test_local_sandbox_with_disabled_host_bash_warns(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n  allow_host_bash: false\ntools:\n  - name: bash\n    use: deerflow.sandbox.tools:bash_tool\n")
        results = doctor.check_sandbox(cfg)
        assert any(result.status == "warn" for result in results)

    def test_container_sandbox_without_runtime_warns(self, tmp_path, monkeypatch):
        cfg = tmp_path / "config.yaml"
        cfg.write_text("config_version: 5\nsandbox:\n  use: deerflow.community.aio_sandbox:AioSandboxProvider\ntools: []\n")
        monkeypatch.setattr(doctor.shutil, "which", lambda _name: None)
        results = doctor.check_sandbox(cfg)
        assert any(result.label == "container runtime available" and result.status == "warn" for result in results)


# ---------------------------------------------------------------------------
# main() exit code
# ---------------------------------------------------------------------------


class TestMainExitCode:
    def test_returns_int(self, tmp_path, monkeypatch, capsys):
        """main() should return 0 or 1 without raising."""
        repo_root = tmp_path / "repo"
        scripts_dir = repo_root / "scripts"
        scripts_dir.mkdir(parents=True)
        fake_doctor = scripts_dir / "doctor.py"
        fake_doctor.write_text("# test-only shim for __file__ resolution\n")

        monkeypatch.chdir(repo_root)
        monkeypatch.setattr(doctor, "__file__", str(fake_doctor))
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)

        exit_code = doctor.main()

        captured = capsys.readouterr()
        output = captured.out + captured.err

        assert exit_code in (0, 1)
        assert output
        assert "config.yaml" in output
        assert ".env" in output
