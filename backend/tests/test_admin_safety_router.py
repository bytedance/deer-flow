"""Authorization contract for the administrator content-safety API."""

from types import SimpleNamespace
from uuid import uuid4

from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import admin_safety


def test_normal_user_cannot_list_safety_events():
    app = make_authed_test_app(
        user_factory=lambda: User(id=uuid4(), email="user@example.com", password_hash="x", system_role="user"),
    )
    app.state.config = SimpleNamespace()
    app.include_router(admin_safety.router)

    with TestClient(app) as client:
        assert client.get("/api/admin/safety/events").status_code == 403
        assert client.post("/api/admin/safety/events/not-an-event/context", json={"reason": "审核风险"}).status_code == 403
