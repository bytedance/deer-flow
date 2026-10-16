"""``$VAR`` config values are resolved exactly once, when ``config.yaml`` loads.

``AppConfig`` replaces each ``$VAR`` reference at load time. A consumer that
resolves the result again treats a secret that itself starts with ``$`` (a
bcrypt hash, a generated password) as another reference and injects the wrong
value -- ``""``, or an unrelated host variable's value when that name exists.

These tests start from YAML text so they also fail if load-time resolution is
ever dropped for these sections.
"""

import importlib
from pathlib import Path

import pytest

from deerflow.config.app_config import AppConfig
from deerflow.config.extensions_config import ExtensionsConfig

_PROVIDERS = [
    pytest.param("deerflow.community.aio_sandbox.aio_sandbox_provider", "AioSandboxProvider", id="aio"),
    pytest.param("deerflow.community.e2b_sandbox.e2b_sandbox_provider", "E2BSandboxProvider", id="e2b"),
    pytest.param("deerflow.community.opensandbox.provider", "OpenSandboxProvider", id="opensandbox"),
    pytest.param("deerflow.community.boxlite.provider", "BoxliteProvider", id="boxlite"),
]

_RESOLVED = {
    "PASSWORD_HASH": "$2b$12$abcdefghijklmnopqrstuv",
    "API_SECRET": "$DEERFLOW_TEST_HOST_ONLY",
    "NODE_ENV": "production",
}


@pytest.fixture
def secret_env(monkeypatch):
    # One value names no host variable (blanked by a second pass), one names a
    # real host variable (swapped for the host value by a second pass).
    monkeypatch.setenv("DEERFLOW_TEST_HASH", _RESOLVED["PASSWORD_HASH"])
    monkeypatch.setenv("DEERFLOW_TEST_SECRET", _RESOLVED["API_SECRET"])
    monkeypatch.setenv("DEERFLOW_TEST_HOST_ONLY", "host-value")


def _load(monkeypatch, tmp_path: Path, yaml_text: str) -> AppConfig:
    """Run the real parse -> resolve -> validate pipeline without touching process singletons."""
    monkeypatch.setattr(AppConfig, "_apply_singleton_configs", classmethod(lambda cls, config, acp_agents: None))
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    return AppConfig._from_yaml_text(yaml_text, path, extensions=ExtensionsConfig(mcp_servers={}, skills={}))


@pytest.mark.usefixtures("secret_env")
@pytest.mark.parametrize(("module_name", "class_name"), _PROVIDERS)
def test_provider_receives_sandbox_environment_resolved_once(monkeypatch, tmp_path, module_name, class_name):
    app_config = _load(
        monkeypatch,
        tmp_path,
        f"""
sandbox:
  use: {module_name}:{class_name}
  environment:
    PASSWORD_HASH: $DEERFLOW_TEST_HASH
    API_SECRET: $DEERFLOW_TEST_SECRET
    NODE_ENV: production
""",
    )
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "get_app_config", lambda: app_config)
    provider_cls = getattr(module, class_name)
    provider = provider_cls.__new__(provider_cls)

    loaded = provider._load_config()

    assert loaded["environment"] == _RESOLVED


@pytest.mark.usefixtures("secret_env")
def test_acp_agent_env_is_resolved_once_at_load(monkeypatch, tmp_path):
    # invoke_acp_agent passes this env through unchanged; see
    # test_invoke_acp_agent_tool.py::test_invoke_acp_agent_passes_env_to_spawn.
    app_config = _load(
        monkeypatch,
        tmp_path,
        """
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
acp_agents:
  codex:
    command: codex-acp
    description: Codex CLI
    env:
      PASSWORD_HASH: $DEERFLOW_TEST_HASH
      API_SECRET: $DEERFLOW_TEST_SECRET
      NODE_ENV: production
""",
    )

    assert app_config.acp_agents["codex"].env == _RESOLVED
