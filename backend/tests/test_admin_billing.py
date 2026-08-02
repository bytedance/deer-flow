from types import SimpleNamespace

import pytest
from fastapi import HTTPException


def test_model_pricing_rejects_model_missing_from_config(monkeypatch):
    from app.gateway.routers import admin_billing

    monkeypatch.setattr(
        admin_billing,
        "get_app_config",
        lambda: SimpleNamespace(models=[SimpleNamespace(name="deepseek-chat")]),
    )

    with pytest.raises(HTTPException, match="Model is not configured"):
        admin_billing.validate_configured_model("not-configured")


def test_model_pricing_accepts_model_from_config(monkeypatch):
    from app.gateway.routers import admin_billing

    monkeypatch.setattr(
        admin_billing,
        "get_app_config",
        lambda: SimpleNamespace(models=[SimpleNamespace(name="deepseek-chat")]),
    )

    admin_billing.validate_configured_model("deepseek-chat")


def test_freezing_last_active_admin_is_rejected():
    from app.gateway.routers.admin_billing import validate_admin_freeze

    with pytest.raises(HTTPException, match="last active administrator"):
        validate_admin_freeze(target_is_admin=True, active_admin_count=1)


def test_freezing_non_admin_or_one_of_many_admins_is_allowed():
    from app.gateway.routers.admin_billing import validate_admin_freeze

    validate_admin_freeze(target_is_admin=False, active_admin_count=1)
    validate_admin_freeze(target_is_admin=True, active_admin_count=2)
