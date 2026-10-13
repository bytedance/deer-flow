"""Opt-in real vendor probe. No discovery or credentials in test output."""

import os
from types import SimpleNamespace

import pytest

from app.gateway.routers import managed_models as router
from deerflow.config.managed_models import ManagedModel

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("DEER_FLOW_RUN_LIVE_TESTS") != "1" or not all(os.getenv(name) for name in ("MANAGED_MODEL_TEST_PROVIDER", "MANAGED_MODEL_TEST_MODEL", "MANAGED_MODEL_TEST_API_KEY")) or bool(os.getenv("CI")),
        reason="Requires explicit live opt-in and vendor test settings; never runs in CI",
    ),
]


@pytest.mark.asyncio
async def test_preset_connection_live(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    profile = ManagedModel(provider=os.environ["MANAGED_MODEL_TEST_PROVIDER"], model=os.environ["MANAGED_MODEL_TEST_MODEL"], api_key=os.environ["MANAGED_MODEL_TEST_API_KEY"])
    assert profile.provider != "openai-compatible", "Use the existing custom endpoint test for legacy profiles"
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    result = await router.test_model(admin, router.SaveModelRequest(config=profile))
    assert result["ok"], result["message"]
    assert not (tmp_path / "managed-models").exists()
