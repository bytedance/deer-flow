"""Sandbox authorization resolution must stay off the async event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from deerflow.authz import sandbox_authz
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig, AuthorizationProviderConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox import tools as sandbox_tools

pytestmark = pytest.mark.asyncio


async def test_reused_async_sandbox_offloads_config_and_provider_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Config hashing and class discovery stay off-loop; construction does not."""
    probe = tmp_path / "sandbox-authz-probe"
    await asyncio.to_thread(probe.write_text, "probe", encoding="utf-8")

    app_config = AppConfig(
        models=[ModelConfig(name="gpt-4", model="gpt-4", use="langchain_openai:ChatOpenAI")],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(
            enabled=True,
            fail_closed=True,
            default_role="user",
            provider=AuthorizationProviderConfig(
                use="deerflow.authz.rbac:RbacAuthorizationProvider",
                config={"roles": {"user": {"sandbox": {"allow": "*"}}}},
            ),
        ),
    )

    def blocking_config_load():
        probe.read_text(encoding="utf-8")
        return app_config

    discover_provider = sandbox_authz.resolve_authorization_provider_spec

    def blocking_provider_discovery(config):
        probe.read_text(encoding="utf-8")
        return discover_provider(config)

    monkeypatch.setattr(sandbox_authz, "safe_app_config", blocking_config_load)
    monkeypatch.setattr(sandbox_authz, "resolve_authorization_provider_spec", blocking_provider_discovery)

    sandbox = MagicMock()
    sandbox_provider = MagicMock()
    sandbox_provider.get.return_value = sandbox
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: sandbox_provider)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": "sbx-existing"}},
        context={"thread_id": "t1", "user_id": "u1", "user_role": "user"},
        config=None,
    )

    assert await sandbox_tools.ensure_sandbox_initialized_async(runtime) is sandbox
