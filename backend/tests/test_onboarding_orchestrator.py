"""Tests for the onboarding orchestrator + Korean summary formatter."""

from __future__ import annotations

import pytest

from deerflow.tools.startcloud.onboarding import (
    OffboardResult,
    OnboardRequest,
    OnboardResult,
)
from deerflow.tools.startcloud.onboarding.orchestrator import (
    run_offboarding,
    run_onboarding,
)
from deerflow.tools.startcloud.user_offboard import _format_offboard_summary
from deerflow.tools.startcloud.user_onboard import _format_onboard_summary


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeOK:
    def __init__(self, name: str = "fake") -> None:
        self._name = name
        self.create_calls: list[OnboardRequest] = []
        self.offboard_calls: list[tuple[str, bool]] = []

    @property
    def service_name(self) -> str:
        return self._name

    def is_configured(self) -> bool:
        return True

    def create_user(self, req: OnboardRequest) -> OnboardResult:
        self.create_calls.append(req)
        return OnboardResult(
            service_name=self._name,
            success=True,
            account_id=f"{self._name}-uid",
            login_url=f"https://{self._name}.example.com",
        )

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:
        self.offboard_calls.append((email, delete))
        return OffboardResult(
            service_name=self._name,
            success=True,
            action="deleted" if delete else "disabled",
        )


class _FakeUnconfigured(_FakeOK):
    def is_configured(self) -> bool:
        return False


class _FakeRaises(_FakeOK):
    def create_user(self, req: OnboardRequest) -> OnboardResult:  # type: ignore[override]
        raise RuntimeError("boom")

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:  # type: ignore[override]
        raise RuntimeError("boom")


# ---------------------------------------------------------------------------
# run_onboarding
# ---------------------------------------------------------------------------


class TestRunOnboarding:
    def test_calls_each_configured_client_in_order(self) -> None:
        a, b = _FakeOK("a"), _FakeOK("b")
        results = run_onboarding(
            OnboardRequest(email="x@y.com", first_name="X", last_name="Y"),
            clients=[a, b],
        )
        assert [r.service_name for r in results] == ["a", "b"]
        assert all(r.success for r in results)
        assert len(a.create_calls) == 1
        assert len(b.create_calls) == 1

    def test_unconfigured_client_short_circuits_with_skip_note(self) -> None:
        unconf = _FakeUnconfigured("teable")
        results = run_onboarding(
            OnboardRequest(email="x@y.com", first_name="X", last_name="Y"),
            clients=[unconf],
        )
        assert results[0].success is False
        assert results[0].service_name == "teable"
        assert "not configured" in (results[0].error or "")
        assert unconf.create_calls == []  # method was never called

    def test_one_client_raising_does_not_abort_the_others(self) -> None:
        results = run_onboarding(
            OnboardRequest(email="x@y.com", first_name="X", last_name="Y"),
            clients=[_FakeRaises("broken"), _FakeOK("working")],
        )
        assert len(results) == 2
        broken, working = results
        assert broken.service_name == "broken"
        assert broken.success is False
        assert "boom" in (broken.error or "")
        assert working.service_name == "working"
        assert working.success is True


class TestRunOffboarding:
    def test_propagates_delete_flag_to_each_client(self) -> None:
        a = _FakeOK("a")
        run_offboarding("x@y.com", delete=True, clients=[a])
        assert a.offboard_calls == [("x@y.com", True)]

    def test_default_is_disable_not_delete(self) -> None:
        a = _FakeOK("a")
        run_offboarding("x@y.com", clients=[a])
        assert a.offboard_calls == [("x@y.com", False)]

    def test_one_client_raising_does_not_abort_the_others(self) -> None:
        results = run_offboarding(
            "x@y.com", clients=[_FakeRaises("broken"), _FakeOK("working")]
        )
        assert results[0].success is False
        assert results[0].action == "failed"
        assert results[1].success is True


# ---------------------------------------------------------------------------
# Summary formatting
# ---------------------------------------------------------------------------


class TestOnboardSummary:
    def _req(self) -> OnboardRequest:
        return OnboardRequest(email="sara@example.com", first_name="사라", last_name="김")

    def test_lists_successes_and_failures_separately(self) -> None:
        results = [
            OnboardResult(service_name="google", success=True, login_url="https://g.example"),
            OnboardResult(service_name="vaultwarden", success=False, error="not implemented"),
        ]
        out = _format_onboard_summary(self._req(), results)
        assert "✅" in out
        assert "Google Workspace" in out
        assert "https://g.example" in out
        assert "⚠️" in out
        assert "Vaultwarden" in out
        assert "not implemented" in out

    def test_redacts_temporary_credentials(self) -> None:
        results = [
            OnboardResult(
                service_name="google",
                success=True,
                temporary_credentials={"temporary_password": "ShouldNotLeak!"},
            )
        ]
        out = _format_onboard_summary(self._req(), results)
        assert "ShouldNotLeak!" not in out
        assert "[숨김]" in out

    def test_korean_label_per_service(self) -> None:
        results = [
            OnboardResult(service_name="teable", success=True),
            OnboardResult(service_name="twenty", success=True),
        ]
        out = _format_onboard_summary(self._req(), results)
        assert "Teable" in out
        assert "Twenty CRM" in out

    def test_all_failed_message(self) -> None:
        results = [
            OnboardResult(service_name="google", success=False, error="x"),
        ]
        out = _format_onboard_summary(self._req(), results)
        assert "자동 온보딩이 작동하지 않았" in out


class TestOffboardSummary:
    def test_disable_mode_label(self) -> None:
        out = _format_offboard_summary(
            "x@y.com", disable_only=True, results=[
                OffboardResult(service_name="google", success=True, action="disabled"),
            ]
        )
        assert "비활성화 (복구 가능)" in out
        assert "계정 비활성화 완료" in out

    def test_delete_mode_label(self) -> None:
        out = _format_offboard_summary(
            "x@y.com", disable_only=False, results=[
                OffboardResult(service_name="google", success=True, action="deleted"),
            ]
        )
        assert "영구 삭제 시도" in out
        assert "계정 영구 삭제 완료" in out

    def test_not_found_renders_korean(self) -> None:
        out = _format_offboard_summary(
            "missing@y.com", disable_only=True, results=[
                OffboardResult(service_name="google", success=True, action="not_found"),
            ]
        )
        assert "이미 처리되었거나 미생성" in out


# ---------------------------------------------------------------------------
# Integration: tool wrappers actually work (no real Google calls)
# ---------------------------------------------------------------------------


def test_user_onboard_tool_imports_and_runs_without_real_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The full chain user_onboard.invoke(...) → orchestrator → stubs → summary.

    We assert this runs with no env vars set: every client is unconfigured, so
    the agent gets a 'all four services need manual setup' summary back —
    which is exactly the production state until ops finishes onboarding the
    service accounts.
    """
    monkeypatch.delenv("GOOGLE_ADMIN_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_ADMIN_IMPERSONATE_EMAIL", raising=False)
    monkeypatch.delenv("GOOGLE_ADMIN_DOMAIN", raising=False)

    from deerflow.tools.startcloud import user_onboard

    out = user_onboard.invoke(
        {"email": "sara@example.com", "first_name": "사라", "last_name": "김"}
    )
    assert "사라 김" in out
    assert "sara@example.com" in out
    # All four services should appear in the failure list (Google = unconfigured;
    # Vaultwarden / Teable / Twenty = not yet implemented).
    for label in ("Google Workspace", "Vaultwarden", "Teable", "Twenty CRM"):
        assert label in out
