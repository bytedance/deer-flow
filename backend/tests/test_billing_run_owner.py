from types import SimpleNamespace


def _request(*, user_id: str, system_role: str = "user") -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(id=user_id, system_role=system_role)))


def test_billing_owner_uses_authenticated_browser_user(monkeypatch):
    from app.gateway import services

    monkeypatch.setattr(services, "get_trusted_internal_owner_user_id", lambda request: None)

    assert services.resolve_billing_owner_user_id(_request(user_id="browser-user")) == "browser-user"


def test_billing_owner_prefers_trusted_internal_owner(monkeypatch):
    from app.gateway import services

    monkeypatch.setattr(services, "get_trusted_internal_owner_user_id", lambda request: "channel-user")

    assert services.resolve_billing_owner_user_id(_request(user_id="internal-user", system_role="internal")) == "channel-user"
