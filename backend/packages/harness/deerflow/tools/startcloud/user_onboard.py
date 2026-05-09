"""Onboard a user across every configured Start-Cloud service.

The agent calls this with the four parameters it can extract from a
sentence like "김사라 sara@bigbangangels.com 으로 온보딩해줘". The tool
fans out across the per-service clients in `onboarding/` and returns a
Korean summary the agent shows the user verbatim.

Sensitive values (temporary passwords) are surfaced through
`temporary_credentials` on each result and rendered in the summary
only as a `[숨김]` placeholder — the agent guidance in
`skills/public/startcloud-admin/SKILL.md` says to retrieve them from
Vaultwarden after the run.
"""

from __future__ import annotations

from langchain_core.tools import tool

from .onboarding.base import OnboardRequest, OnboardResult
from .onboarding.orchestrator import run_onboarding


@tool
def user_onboard(
    email: str,
    first_name: str,
    last_name: str,
    role: str = "member",
    temporary_password: str | None = None,
) -> str:
    """Onboard a new team member to Start-Cloud. Call this tool ONCE with all required parameters.

    Creates accounts across every configured service:
    - Google Workspace (via Admin SDK; requires service-account env vars)
    - Vaultwarden (parallel session)
    - Teable (parallel session)
    - Twenty CRM (parallel session)

    Services that are not yet implemented or not configured are skipped
    silently and reported in the summary so the user can complete those
    manually.

    For Korean names like "김사라": last_name="김", first_name="사라".
    For English names like "John Kim": first_name="John", last_name="Kim".

    Args:
        email: User's email address (required, e.g. "sara.kim@company.com")
        first_name: User's given name (required, e.g. "사라" or "Sara")
        last_name: User's family name (required, e.g. "김" or "Kim")
        role: Role to assign — 'admin' or 'member' (default: member)
        temporary_password: Optional temporary password. Leave blank to auto-generate
            a secure random password the user must change on first login.
    """
    req = OnboardRequest(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role=role,
        temporary_password=temporary_password,
    )
    results = run_onboarding(req)
    return _format_onboard_summary(req, results)


def _format_onboard_summary(req: OnboardRequest, results: list[OnboardResult]) -> str:
    lines: list[str] = []
    lines.append("=== 온보딩 결과 ===")
    lines.append(f"이름: {req.first_name} {req.last_name}")
    lines.append(f"이메일: {req.email}")
    lines.append(f"역할: {req.role}")
    lines.append("")

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    if successes:
        lines.append(f"✅ 성공한 서비스 ({len(successes)}개)")
        for r in successes:
            label = _service_label(r.service_name)
            lines.append(f"  • {label}")
            if r.login_url:
                lines.append(f"      로그인: {r.login_url}")
            if r.invite_url:
                lines.append(f"      초대 링크: {r.invite_url}")
            for note in r.notes:
                lines.append(f"      메모: {note}")
            if r.temporary_credentials:
                lines.append(
                    "      임시 자격증명: [숨김] (사용자에게 안전한 채널로 직접 전달)"
                )
        lines.append("")

    if failures:
        lines.append(f"⚠️ 처리되지 않은 서비스 ({len(failures)}개)")
        for r in failures:
            label = _service_label(r.service_name)
            error = r.error or "원인 불명"
            lines.append(f"  • {label}: {error}")
        lines.append("")

    if successes and not failures:
        lines.append("모든 서비스에 계정이 생성되었습니다.")
    elif successes and failures:
        lines.append(
            "일부 서비스만 자동 처리되었습니다. 위의 미처리 서비스는 수동으로 추가해주세요."
        )
    else:
        lines.append(
            "자동 온보딩이 작동하지 않았습니다. 환경변수 설정을 확인하거나 수동으로 진행해주세요."
        )

    return "\n".join(lines)


_SERVICE_LABELS = {
    "google": "Google Workspace",
    "vaultwarden": "Vaultwarden (비밀번호 매니저)",
    "teable": "Teable (스프레드시트)",
    "twenty": "Twenty CRM",
}


def _service_label(name: str) -> str:
    return _SERVICE_LABELS.get(name, name)
