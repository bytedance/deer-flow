"""Tests for `GoogleAdminClient`.

No real Google API calls. We monkeypatch the lazy `_get_service` factory
to return a fake that captures the request bodies, and we synthesize
`HttpError` instances directly when we want to exercise the 409/404
branches.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from deerflow.tools.startcloud.onboarding import (
    OffboardResult,
    OnboardRequest,
    OnboardResult,
    ServiceOnboardClient,
)
from deerflow.tools.startcloud.onboarding.google_admin_client import GoogleAdminClient


# ---------------------------------------------------------------------------
# Fake Directory API surface — captures bodies so tests can assert payloads.
# ---------------------------------------------------------------------------


def _make_fake_service(
    *,
    insert_response: dict[str, Any] | None = None,
    insert_raises: Exception | None = None,
    get_response: dict[str, Any] | None = None,
    update_raises: Exception | None = None,
    delete_raises: Exception | None = None,
) -> tuple[MagicMock, dict[str, Any]]:
    """Return a (fake_service, captured) pair.

    `captured` accumulates the kwargs each Directory API call received so
    tests can assert the wire format without mocking google's HTTP client.
    """
    captured: dict[str, Any] = {}

    fake = MagicMock()

    def insert(body: dict[str, Any]):
        captured["insert_body"] = body
        chain = MagicMock()
        if insert_raises is not None:
            chain.execute.side_effect = insert_raises
        else:
            chain.execute.return_value = insert_response or {}
        return chain

    def get(userKey: str):
        captured["get_userKey"] = userKey
        chain = MagicMock()
        chain.execute.return_value = get_response or {}
        return chain

    def update(userKey: str, body: dict[str, Any]):
        captured["update_userKey"] = userKey
        captured["update_body"] = body
        chain = MagicMock()
        if update_raises is not None:
            chain.execute.side_effect = update_raises
        else:
            chain.execute.return_value = {}
        return chain

    def delete(userKey: str):
        captured["delete_userKey"] = userKey
        chain = MagicMock()
        if delete_raises is not None:
            chain.execute.side_effect = delete_raises
        else:
            chain.execute.return_value = ""
        return chain

    users = MagicMock()
    users.insert = insert
    users.get = get
    users.update = update
    users.delete = delete
    fake.users.return_value = users
    return fake, captured


def _client_with_fake(monkeypatch: pytest.MonkeyPatch, fake: MagicMock) -> GoogleAdminClient:
    """Return a GoogleAdminClient pre-configured with `fake` as its service."""
    client = GoogleAdminClient(
        service_account_file="/fake/path/sa.json",
        impersonate_email="admin@example.com",
        domain="example.com",
    )
    # Skip the real `is_configured` filesystem check.
    monkeypatch.setattr(client, "is_configured", lambda: True)
    monkeypatch.setattr(client, "_get_service", lambda: fake)
    return client


def _http_error(status: int, message: str = "boom") -> Exception:
    """Build an HttpError without hitting the network."""
    from googleapiclient.errors import HttpError

    resp = MagicMock()
    resp.status = status
    resp.reason = message
    body = (
        b'{"error":{"code":' + str(status).encode() + b',"message":"' + message.encode() + b'"}}'
    )
    return HttpError(resp=resp, content=body, uri="http://test/")


# ---------------------------------------------------------------------------
# Conformance — the contract test from test_onboarding_contract reused.
# ---------------------------------------------------------------------------


class TestConformance:
    def test_satisfies_protocol(self) -> None:
        c = GoogleAdminClient()
        assert isinstance(c, ServiceOnboardClient)

    def test_service_name_is_lowercase(self) -> None:
        assert GoogleAdminClient().service_name == "google"

    def test_unconfigured_is_configured_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_ADMIN_SERVICE_ACCOUNT_FILE", raising=False)
        monkeypatch.delenv("GOOGLE_ADMIN_IMPERSONATE_EMAIL", raising=False)
        monkeypatch.delenv("GOOGLE_ADMIN_DOMAIN", raising=False)
        assert GoogleAdminClient().is_configured() is False


# ---------------------------------------------------------------------------
# create_user — happy path, 409 idempotency, generic failure.
# ---------------------------------------------------------------------------


class TestCreateUser:
    def test_happy_path_sends_expected_body_and_returns_account_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, captured = _make_fake_service(
            insert_response={"id": "google-uid-123", "primaryEmail": "sara@example.com"}
        )
        client = _client_with_fake(monkeypatch, fake)

        result = client.create_user(
            OnboardRequest(
                email="sara@example.com",
                first_name="사라",
                last_name="김",
                temporary_password="TempPass123!",
            )
        )

        assert result.success is True
        assert result.account_id == "google-uid-123"
        assert result.service_name == "google"
        assert result.temporary_credentials == {"temporary_password": "TempPass123!"}

        body = captured["insert_body"]
        assert body["primaryEmail"] == "sara@example.com"
        assert body["name"]["givenName"] == "사라"
        assert body["name"]["familyName"] == "김"
        assert body["password"] == "TempPass123!"
        assert body["changePasswordAtNextLogin"] is True

    def test_auto_generates_password_when_caller_omits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, captured = _make_fake_service(insert_response={"id": "uid"})
        client = _client_with_fake(monkeypatch, fake)

        result = client.create_user(
            OnboardRequest(email="x@y.com", first_name="X", last_name="Y")
        )

        assert result.success is True
        password = result.temporary_credentials["temporary_password"]
        assert len(password) >= 12
        assert any(c.isupper() for c in password)
        assert any(c.islower() for c in password)
        assert any(c.isdigit() for c in password)
        assert captured["insert_body"]["password"] == password

    def test_409_existing_user_treated_as_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, captured = _make_fake_service(
            insert_raises=_http_error(409, "Entity already exists."),
            get_response={"id": "existing-uid"},
        )
        client = _client_with_fake(monkeypatch, fake)

        result = client.create_user(
            OnboardRequest(email="dup@example.com", first_name="D", last_name="U")
        )

        assert result.success is True
        assert result.account_id == "existing-uid"
        assert any("already existed" in n for n in result.notes)

    def test_generic_http_error_returns_failure_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _ = _make_fake_service(insert_raises=_http_error(403, "Forbidden"))
        client = _client_with_fake(monkeypatch, fake)

        result = client.create_user(
            OnboardRequest(email="x@y.com", first_name="X", last_name="Y")
        )

        assert result.success is False
        assert result.error is not None
        assert "403" in result.error
        # Even on failure, surface the password the caller passed in (or that we
        # generated) so the operator can hand it off manually.
        assert "temporary_password" in result.temporary_credentials


# ---------------------------------------------------------------------------
# offboard_user — disable / delete / 404 / failure.
# ---------------------------------------------------------------------------


class TestOffboardUser:
    def test_disable_calls_users_update_with_suspended_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, captured = _make_fake_service()
        client = _client_with_fake(monkeypatch, fake)

        result = client.offboard_user("x@y.com")

        assert isinstance(result, OffboardResult)
        assert result.success is True
        assert result.action == "disabled"
        assert captured["update_userKey"] == "x@y.com"
        assert captured["update_body"] == {"suspended": True}

    def test_delete_uses_users_delete(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake, captured = _make_fake_service()
        client = _client_with_fake(monkeypatch, fake)

        result = client.offboard_user("x@y.com", delete=True)

        assert result.success is True
        assert result.action == "deleted"
        assert captured["delete_userKey"] == "x@y.com"

    def test_404_treated_as_idempotent_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _ = _make_fake_service(update_raises=_http_error(404, "Resource Not Found"))
        client = _client_with_fake(monkeypatch, fake)

        result = client.offboard_user("missing@y.com")

        assert result.success is True
        assert result.action == "not_found"

    def test_other_http_error_returns_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake, _ = _make_fake_service(update_raises=_http_error(500, "Internal"))
        client = _client_with_fake(monkeypatch, fake)

        result = client.offboard_user("x@y.com")

        assert result.success is False
        assert result.action == "failed"
        assert result.error is not None
        assert "500" in result.error
