from __future__ import annotations

import base64
import json
from pathlib import Path

import yaml

from app.gateway.railway_runtime import prepare_gateway_runtime


def _write_template_files(tmp_path: Path) -> tuple[Path, Path]:
    config_template = tmp_path / "config.template.yaml"
    config_template.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"name": "gpt-5.4", "use": "deerflow.models.openai_codex_provider:CodexChatModel", "model": "gpt-5.4"},
                    {"name": "gpt-5", "use": "langchain_openai:ChatOpenAI", "model": "gpt-5", "api_key": "$OPENAI_API_KEY"},
                    {"name": "gemini-2.5-pro", "use": "langchain_google_genai:ChatGoogleGenerativeAI", "model": "gemini-2.5-pro", "gemini_api_key": "$GEMINI_API_KEY"},
                ],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider", "allow_host_bash": False},
                "checkpointer": {"type": "sqlite", "connection_string": "checkpoints.db"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    extensions_template = tmp_path / "extensions.template.json"
    extensions_template.write_text('{"mcpServers":{},"skills":{}}', encoding="utf-8")
    return config_template, extensions_template


def test_prepare_gateway_runtime_codex_primary_with_fallbacks(tmp_path: Path) -> None:
    config_template, extensions_template = _write_template_files(tmp_path)
    home = tmp_path / "home"
    config_path = tmp_path / "runtime" / "config.yaml"
    extensions_path = home / "extensions_config.json"
    codex_auth_path = tmp_path / "runtime" / "codex-auth.json"
    auth_payload = {"tokens": {"access_token": "token", "refresh_token": "refresh", "account_id": "acct"}}

    result = prepare_gateway_runtime(
        deer_flow_home=home,
        config_output_path=config_path,
        extensions_output_path=extensions_path,
        codex_auth_output_path=codex_auth_path,
        config_template_path=config_template,
        extensions_template_path=extensions_template,
        env={
            "DEER_FLOW_PRIMARY_MODEL": "codex",
            "CODEX_AUTH_JSON_B64": base64.b64encode(json.dumps(auth_payload).encode("utf-8")).decode("utf-8"),
            "OPENAI_API_KEY": "openai-key",
            "GEMINI_API_KEY": "gemini-key",
        },
    )

    rendered = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert [model["name"] for model in rendered["models"]] == ["gpt-5.4", "gpt-5", "gemini-2.5-pro"]
    assert rendered["sandbox"]["allow_host_bash"] is True
    assert json.loads(codex_auth_path.read_text(encoding="utf-8")) == auth_payload
    assert json.loads(extensions_path.read_text(encoding="utf-8")) == {"mcpServers": {}, "skills": {}}
    assert result["primary_model"] == "gpt-5.4"


def test_prepare_gateway_runtime_respects_existing_extensions_file(tmp_path: Path) -> None:
    config_template, extensions_template = _write_template_files(tmp_path)
    home = tmp_path / "home"
    config_path = tmp_path / "runtime" / "config.yaml"
    extensions_path = home / "extensions_config.json"
    codex_auth_path = tmp_path / "runtime" / "codex-auth.json"
    extensions_path.parent.mkdir(parents=True, exist_ok=True)
    extensions_path.write_text('{"mcpServers":{"demo":{"enabled":true}},"skills":{}}', encoding="utf-8")

    prepare_gateway_runtime(
        deer_flow_home=home,
        config_output_path=config_path,
        extensions_output_path=extensions_path,
        codex_auth_output_path=codex_auth_path,
        config_template_path=config_template,
        extensions_template_path=extensions_template,
        env={
            "DEER_FLOW_PRIMARY_MODEL": "openai",
            "OPENAI_API_KEY": "openai-key",
            "DEER_FLOW_ALLOW_HOST_BASH": "false",
        },
    )

    rendered = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert [model["name"] for model in rendered["models"]] == ["gpt-5"]
    assert rendered["sandbox"]["allow_host_bash"] is False
    assert extensions_path.read_text(encoding="utf-8") == '{"mcpServers":{"demo":{"enabled":true}},"skills":{}}'
    assert not codex_auth_path.exists()


def test_prepare_gateway_runtime_requires_credentials_for_primary_model(tmp_path: Path) -> None:
    config_template, extensions_template = _write_template_files(tmp_path)

    try:
        prepare_gateway_runtime(
            deer_flow_home=tmp_path / "home",
            config_output_path=tmp_path / "runtime" / "config.yaml",
            extensions_output_path=tmp_path / "home" / "extensions_config.json",
            codex_auth_output_path=tmp_path / "runtime" / "codex-auth.json",
            config_template_path=config_template,
            extensions_template_path=extensions_template,
            env={"DEER_FLOW_PRIMARY_MODEL": "codex"},
        )
    except ValueError as exc:
        assert "CODEX_AUTH_JSON_B64" in str(exc)
    else:
        raise AssertionError("Expected prepare_gateway_runtime() to reject codex primary without auth")
