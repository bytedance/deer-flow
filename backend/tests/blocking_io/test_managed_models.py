"""Managed model encryption, persistence and config merging stay off the loop."""

from types import SimpleNamespace

import pytest

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel


@pytest.mark.asyncio
async def test_admin_catalog_round_trip_offloads_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    request = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    body = router.SaveModelRequest(config=ManagedModel(name="test", model="test", base_url="https://example.com/v1", api_key="secret"))
    result = await router.save_model(request, body)
    assert result["has_api_key"] is True
    catalog = await router.list_managed_models(request)
    assert catalog["models"][0]["name"] == "test"
    assert "secret" not in str(catalog)
