from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_prewarm_checks_live_authorization_before_touching_provider(monkeypatch, allowed):
    from app.gateway import sandbox_prewarm as module
    from deerflow.sandbox.exceptions import SandboxAuthorizationError

    config = SimpleNamespace(sandbox=SimpleNamespace(use=module.USER_POOL_PROVIDER, prewarm_on_login=True))
    monkeypatch.setattr(module, "get_app_config", lambda: config)
    authorize = MagicMock(side_effect=None if allowed else SandboxAuthorizationError())
    monkeypatch.setattr(module, "authorize_sandbox_for_request", authorize)
    provider = SimpleNamespace(prewarm_async=AsyncMock())
    get_provider = MagicMock(return_value=provider)
    monkeypatch.setattr(module, "get_sandbox_provider", get_provider)
    await module._prewarm(SimpleNamespace(id="alice", system_role="user"))
    authorize.assert_called_once()
    assert get_provider.call_count == int(allowed)
    assert provider.prewarm_async.await_count == int(allowed)
