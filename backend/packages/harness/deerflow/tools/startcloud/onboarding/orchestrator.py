"""Fan-out runner for onboarding / offboarding across configured services.

The lead `user_onboard` / `user_offboard` tools call into this module so the
agent's view of "온보딩" is just one operation — even though it touches up to
four backing services. The orchestrator:

1. Discovers which clients are configured (`is_configured() == True`),
   skipping the rest silently.
2. Calls each client sequentially. Failures are isolated per service —
   one broken integration does not abort the others.
3. Returns the full list of `OnboardResult` / `OffboardResult` objects
   so the caller (the tool wrapper) can format a Korean summary.

Sequential, not parallel, on purpose. Four HTTP-bound operations finishing
in 5–10s each is well under the 90s SLA, and serial execution makes
"who failed first" obvious in logs without contending with deer-flow's
existing thread pool budget. Revisit if a single service hits >30s.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from .base import OffboardResult, OnboardRequest, OnboardResult, ServiceOnboardClient

logger = logging.getLogger(__name__)


def get_default_clients() -> list[ServiceOnboardClient]:
    """Return the default ordered list of onboarding clients.

    Order matters: Google first because every other service binds to a
    Google email, so creating Google last would race the invite emails
    with the Google account's existence.

    Clients land here as parallel sessions implement them. Today only
    the Google client is real; the others are placeholders that report
    "not implemented" so the orchestrator's interface is exercised end
    to end and a future PR is a one-line wiring change rather than a
    refactor.
    """
    from .google_admin_client import GoogleAdminClient

    clients: list[ServiceOnboardClient] = [GoogleAdminClient()]

    # The remaining clients land here as their parallel sessions land.
    # Until then we surface them as a single placeholder so the agent's
    # summary mentions them — beats silently dropping the user's request.
    clients.extend(_pending_service_clients())

    return clients


def run_onboarding(
    req: OnboardRequest,
    clients: Iterable[ServiceOnboardClient] | None = None,
) -> list[OnboardResult]:
    """Create accounts on every configured service. Never raises."""
    chosen = list(clients) if clients is not None else get_default_clients()
    results: list[OnboardResult] = []
    for client in chosen:
        if not client.is_configured():
            results.append(
                OnboardResult(
                    service_name=client.service_name,
                    success=False,
                    error="Service not configured (skipped).",
                )
            )
            continue
        try:
            results.append(client.create_user(req))
        except Exception as e:  # contract says clients shouldn't raise; belt + braces
            logger.exception("Unhandled error in %s.create_user", client.service_name)
            results.append(
                OnboardResult(
                    service_name=client.service_name,
                    success=False,
                    error=f"Unhandled exception: {type(e).__name__}: {e}",
                )
            )
    return results


def run_offboarding(
    email: str,
    *,
    delete: bool = False,
    clients: Iterable[ServiceOnboardClient] | None = None,
) -> list[OffboardResult]:
    """Disable (default) or delete the account everywhere. Never raises."""
    chosen = list(clients) if clients is not None else get_default_clients()
    results: list[OffboardResult] = []
    for client in chosen:
        if not client.is_configured():
            results.append(
                OffboardResult(
                    service_name=client.service_name,
                    success=False,
                    action="failed",
                    error="Service not configured (skipped).",
                )
            )
            continue
        try:
            results.append(client.offboard_user(email, delete=delete))
        except Exception as e:
            logger.exception("Unhandled error in %s.offboard_user", client.service_name)
            results.append(
                OffboardResult(
                    service_name=client.service_name,
                    success=False,
                    action="failed",
                    error=f"Unhandled exception: {type(e).__name__}: {e}",
                )
            )
    return results


# ─── Placeholder clients for services not yet implemented ──────────────────


class _PendingClient:
    """Stub used while a real per-service client is in flight in another session.

    `is_configured()` is False, so `run_onboarding` / `run_offboarding`
    short-circuit cleanly with a 'not configured' note. The point of
    listing them here is so the agent's chat summary names them — the
    user sees Vaultwarden / Teable / Twenty in the report instead of
    silently missing services.
    """

    def __init__(self, service_name: str) -> None:
        self._service_name = service_name

    @property
    def service_name(self) -> str:
        return self._service_name

    def is_configured(self) -> bool:
        return False

    def create_user(self, req: OnboardRequest) -> OnboardResult:
        return OnboardResult(
            service_name=self._service_name,
            success=False,
            error=(
                f"{self._service_name} onboarding client is not yet implemented. "
                "Tracked in docs/PARALLEL-ONBOARDING-WORK.md."
            ),
        )

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:
        return OffboardResult(
            service_name=self._service_name,
            success=False,
            action="failed",
            error=f"{self._service_name} offboarding client is not yet implemented.",
        )


def _pending_service_clients() -> list[ServiceOnboardClient]:
    return [
        _PendingClient("vaultwarden"),
        _PendingClient("teable"),
        _PendingClient("twenty"),
    ]
