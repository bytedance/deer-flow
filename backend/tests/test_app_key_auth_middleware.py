from types import SimpleNamespace

from app.gateway.auth_middleware import _APP_KEY_REQUESTS, _derive_app_user_id
from app.gateway.csrf_middleware import should_check_csrf


def test_app_key_authentication_has_an_exact_five_endpoint_allowlist():
    assert _APP_KEY_REQUESTS == {
        ("GET", "/api/models"),
        ("GET", "/api/skills"),
        ("GET", "/api/agents"),
        ("POST", "/api/runs/stream"),
        ("POST", "/api/runs/wait"),
    }


def test_derived_identity_is_stable_and_scoped_to_the_authenticated_app():
    assert _derive_app_user_id("sales-app", "alice") == _derive_app_user_id("sales-app", "alice")
    assert _derive_app_user_id("sales-app", "alice") != _derive_app_user_id("support-app", "alice")


def test_app_key_run_requests_bypass_csrf_only_on_the_exact_allowlisted_paths():
    allowed = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/runs/stream"),
        headers={"X-DeerFlow-App-Key": "test-key"},
    )
    denied = SimpleNamespace(
        method="POST",
        url=SimpleNamespace(path="/api/runs/stream/other"),
        headers={"X-DeerFlow-App-Key": "test-key"},
    )

    assert should_check_csrf(allowed) is False
    assert should_check_csrf(denied) is True
