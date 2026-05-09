"""Start-Cloud onboarding clients — one module per backing service.

Each `*_client.py` provides a `ServiceOnboardClient` implementation that knows
how to create / disable / delete a user account on its own service. The lead
`user_onboard` / `user_offboard` tools fan out across whichever clients are
configured at runtime and return a unified report.

Layout (clients land here as separate sessions implement them):
    base.py                 — Protocol + dataclasses (this is the cross-session contract)
    google_admin_client.py  — Google Workspace via Admin SDK Directory API
    vaultwarden_client.py   — Vaultwarden organization invites
    teable_client.py        — Teable space invitations
    twenty_client.py        — Twenty CRM workspace invitations
    orchestrator.py         — Fan-out runner consumed by the user_onboard tool
"""

from .base import (
    OffboardResult,
    OnboardRequest,
    OnboardResult,
    ServiceOnboardClient,
)

__all__ = [
    "OffboardResult",
    "OnboardRequest",
    "OnboardResult",
    "ServiceOnboardClient",
]
