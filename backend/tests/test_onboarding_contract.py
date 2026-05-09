"""Contract tests for the cross-service onboarding interface.

These tests do NOT exercise any real service. They lock down the shape that
every per-service client must satisfy so the parallel sessions implementing
google_admin_client / vaultwarden_client / teable_client / twenty_client
can run their own client through `validate_client()` and know whether
they're conforming before integration.
"""

from __future__ import annotations

import inspect

import pytest

from deerflow.tools.startcloud.onboarding import (
    OffboardResult,
    OnboardRequest,
    OnboardResult,
    ServiceOnboardClient,
)


# ---------------------------------------------------------------------------
# Reference fake — what every client should look like at minimum.
# ---------------------------------------------------------------------------


class _FakeClient:
    @property
    def service_name(self) -> str:
        return "fake"

    def is_configured(self) -> bool:
        return True

    def create_user(self, req: OnboardRequest) -> OnboardResult:
        return OnboardResult(service_name=self.service_name, success=True, account_id="fake-1")

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:
        return OffboardResult(service_name=self.service_name, success=True, action="disabled")


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------


class TestRequestAndResultShapes:
    def test_onboard_request_minimum_fields(self) -> None:
        req = OnboardRequest(email="x@y.com", first_name="X", last_name="Y")
        assert req.role == "member"
        assert req.temporary_password is None

    def test_onboard_result_defaults(self) -> None:
        r = OnboardResult(service_name="fake", success=True)
        assert r.account_id is None
        assert r.notes == []
        assert r.temporary_credentials == {}

    def test_offboard_result_minimum_fields(self) -> None:
        r = OffboardResult(service_name="fake", success=True, action="disabled")
        assert r.error is None


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_fake_client_satisfies_protocol(self) -> None:
        client: ServiceOnboardClient = _FakeClient()
        assert isinstance(client, ServiceOnboardClient)

    def test_missing_method_fails_isinstance(self) -> None:
        class Broken:
            @property
            def service_name(self) -> str:
                return "broken"

            def is_configured(self) -> bool:
                return False

            # missing create_user / offboard_user

        assert not isinstance(Broken(), ServiceOnboardClient)

    def test_create_user_signature_is_keyword_compatible(self) -> None:
        # `from __future__ import annotations` makes annotations strings, so
        # resolve them through get_type_hints rather than reading raw values.
        hints = inspect.get_annotations(_FakeClient.create_user, eval_str=True)
        assert hints["req"] is OnboardRequest
        assert hints["return"] is OnboardResult

    def test_offboard_user_has_keyword_only_delete_flag(self) -> None:
        sig = inspect.signature(_FakeClient.offboard_user)
        delete_param = sig.parameters["delete"]
        assert delete_param.kind == inspect.Parameter.KEYWORD_ONLY
        assert delete_param.default is False


# ---------------------------------------------------------------------------
# Public helper: validate_client(client) — runtime check used by tests
# in each per-service module to assert their own conformance.
# ---------------------------------------------------------------------------


def validate_client(client: object) -> None:
    """Raise AssertionError with a specific message if `client` doesn't conform.

    Per-service tests call this to keep the failure message targeted at the
    method that drifted, instead of just "isinstance returned False".
    """
    assert isinstance(client, ServiceOnboardClient), (
        f"{type(client).__name__} does not satisfy ServiceOnboardClient: missing "
        f"one of service_name / is_configured / create_user / offboard_user"
    )
    assert isinstance(client.service_name, str) and client.service_name == client.service_name.lower(), (
        "service_name must be a lowercase string"
    )
    assert isinstance(client.is_configured(), bool), "is_configured() must return bool"


class TestValidateHelper:
    def test_passes_for_conforming_client(self) -> None:
        validate_client(_FakeClient())

    def test_rejects_non_lowercase_service_name(self) -> None:
        class WrongCase(_FakeClient):
            @property
            def service_name(self) -> str:
                return "GoogleAdmin"

        with pytest.raises(AssertionError, match="lowercase"):
            validate_client(WrongCase())
