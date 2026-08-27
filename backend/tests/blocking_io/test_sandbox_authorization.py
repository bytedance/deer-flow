"""Sandbox authorization resolution must stay off the async event loop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.authz.provider import AuthzDecision
from deerflow.config.app_config import AppConfig
from deerflow.config.authorization_config import AuthorizationConfig
from deerflow.config.model_config import ModelConfig
from deerflow.config.sandbox_config import SandboxConfig

pytestmark = pytest.mark.asyncio


async def test_reused_async_sandbox_offloads_config_and_provider_resolution(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both config hashing and custom-provider construction may block."""
    from deerflow.authz import sandbox_authz
    from deerflow.sandbox import tools as sandbox_tools

    probe = tmp_path / "sandbox-authz-probe"
    await asyncio.to_thread(probe.write_text, "probe", encoding="utf-8")

    app_config = AppConfig(
        models=[ModelConfig(name="gpt-4", model="gpt-4", use="langchain_openai:ChatOpenAI")],
        sandbox=SandboxConfig(use="deerflow.sandbox.local:LocalSandboxProvider"),
        authorization=AuthorizationConfig(enabled=True, fail_closed=True, default_role="user"),
    )
    provider = MagicMock()
    provider.aauthorize = AsyncMock(return_value=AuthzDecision(allow=True))

    def blocking_config_load():
        probe.read_text(encoding="utf-8")
        return app_config

    def blocking_provider_resolution(_config):
        probe.read_text(encoding="utf-8")
        return provider

    monkeypatch.setattr(sandbox_authz, "safe_app_config", blocking_config_load)
    monkeypatch.setattr(sandbox_authz, "resolve_authorization_provider", blocking_provider_resolution)

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
    provider.aauthorize.assert_awaited_once()
