"""Offboard a user from every configured Start-Cloud service."""

from __future__ import annotations

from langchain_core.tools import tool

from .onboarding.base import OffboardResult
from .onboarding.orchestrator import run_offboarding


@tool
def user_offboard(email: str, disable_only: bool = True) -> str:
    """Offboard a team member from Start-Cloud.

    By default, disables (suspends) the account so data is preserved and the
    action is reversible. Use `disable_only=False` to permanently delete on
    services that support it; services that don't (Vaultwarden, Teable,
    Twenty in our stack) downgrade to disable and report it in the summary.

    Args:
        email: Email of the user to offboard
        disable_only: If True (default), disable accounts. If False, attempt
            permanent delete.
    """
    results = run_offboarding(email, delete=not disable_only)
    return _format_offboard_summary(email, disable_only, results)


def _format_offboard_summary(
    email: str, disable_only: bool, results: list[OffboardResult]
) -> str:
    lines: list[str] = []
    lines.append("=== 오프보딩 결과 ===")
    lines.append(f"이메일: {email}")
    lines.append(f"모드: {'비활성화 (복구 가능)' if disable_only else '영구 삭제 시도'}")
    lines.append("")

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    if successes:
        lines.append(f"✅ 처리된 서비스 ({len(successes)}개)")
        for r in successes:
            label = _service_label(r.service_name)
            action_kr = _ACTION_LABELS.get(r.action, r.action)
            lines.append(f"  • {label}: {action_kr}")

    if failures:
        if successes:
            lines.append("")
        lines.append(f"⚠️ 처리되지 않은 서비스 ({len(failures)}개)")
        for r in failures:
            label = _service_label(r.service_name)
            error = r.error or "원인 불명"
            lines.append(f"  • {label}: {error}")

    return "\n".join(lines)


_SERVICE_LABELS = {
    "google": "Google Workspace",
    "vaultwarden": "Vaultwarden",
    "teable": "Teable",
    "twenty": "Twenty CRM",
}


_ACTION_LABELS = {
    "disabled": "계정 비활성화 완료",
    "deleted": "계정 영구 삭제 완료",
    "not_found": "해당 사용자가 존재하지 않음 (이미 처리되었거나 미생성)",
    "failed": "처리 실패",
}


def _service_label(name: str) -> str:
    return _SERVICE_LABELS.get(name, name)
