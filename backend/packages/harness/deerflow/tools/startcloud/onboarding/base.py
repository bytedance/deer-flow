"""Cross-service onboarding contract.

Every backing service (Google Workspace, Vaultwarden, Teable, Twenty CRM, …)
gets its own `*_client.py` that satisfies `ServiceOnboardClient`. The
`user_onboard` and `user_offboard` agent tools fan out across whichever
clients are configured and return a `list[OnboardResult]` / `list[OffboardResult]`.

Why a Protocol (not an ABC):
- Each client lands in its own PR from a different parallel session. Protocol
  lets us check shape conformance without forcing every client to inherit a
  shared base — useful when a service-specific client wants to live in its
  own module with no upward dependency.
- `runtime_checkable` so tests can `isinstance(client, ServiceOnboardClient)`
  catch missing methods early.

Sync, not async: deer-flow's existing startcloud tools are synchronous (see
`stack_status`, `service_info`). Service API calls inside a single onboarding
run are sequential and bounded — overlapping fan-out across services is the
orchestrator's job (`onboarding/orchestrator.py`), not the client's.

Conventions every client must honour:
1. **Idempotency on create**: if the user already exists, return
   `success=True` with `account_id` filled and a note in `notes` —
   never raise. The orchestrator treats "already exists" as a success.
2. **No partial state on failure**: if a step partway through fails (e.g.
   user created but invite-send fails), set `success=False` and explain in
   `error`; do not silently leave half-configured accounts.
3. **No secrets in result fields**: temporary passwords, tokens, anything
   sensitive goes through `temporary_credentials` (a redaction-friendly
   dict). The agent's chat output redacts that field.
4. **Localised errors are OK in `error`**: the orchestrator forwards them
   verbatim to the agent, which presents them to the user in Korean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class OnboardRequest:
    """Inputs the agent collects before fan-out begins.

    `temporary_password` is optional because OIDC-only services (Vaultwarden,
    Teable, Twenty in our deployment) never set a local password — the user
    just clicks "Sign in with Google". Clients that don't need it must accept
    `None` without erroring.
    """

    email: str
    first_name: str
    last_name: str
    role: str = "member"
    temporary_password: str | None = None


@dataclass
class OnboardResult:
    """Per-service outcome returned by `ServiceOnboardClient.create_user`."""

    service_name: str
    success: bool
    account_id: str | None = None
    """Service-native identifier (e.g. Google `userId`, Twenty `workspaceMemberId`)."""

    login_url: str | None = None
    """User-facing URL the agent surfaces in its summary."""

    invite_url: str | None = None
    """Optional explicit invite link (Vaultwarden / Twenty), distinct from login_url."""

    error: str | None = None
    """Human-readable failure detail. Empty when success=True."""

    notes: list[str] = field(default_factory=list)
    """Non-failure observations — e.g. 'Account already existed; re-sent invite'."""

    temporary_credentials: dict[str, str] = field(default_factory=dict)
    """Sensitive payload (passwords, one-time tokens). Redacted in chat output."""


@dataclass
class OffboardResult:
    """Per-service outcome returned by `ServiceOnboardClient.offboard_user`."""

    service_name: str
    success: bool
    action: str
    """One of: 'disabled' | 'deleted' | 'not_found' | 'failed'."""

    error: str | None = None


@runtime_checkable
class ServiceOnboardClient(Protocol):
    """A per-service user lifecycle client.

    Implementations live in sibling modules (`google_admin_client.py`,
    `vaultwarden_client.py`, `teable_client.py`, `twenty_client.py`).
    Each constructs itself from environment variables it owns; the
    orchestrator assembles them lazily so a misconfigured service does
    not block the others.
    """

    @property
    def service_name(self) -> str:
        """Stable, lowercase identifier — 'google', 'vaultwarden', 'teable', 'twenty'.

        Used as a dict key in the orchestrator and shown to the user.
        """
        ...

    def is_configured(self) -> bool:
        """True iff the client has the credentials it needs to make real calls.

        The orchestrator uses this to skip silently-misconfigured services
        instead of failing the whole onboarding run. Returning False from
        a freshly-constructed client is a normal state in development.
        """
        ...

    def create_user(self, req: OnboardRequest) -> OnboardResult:
        """Create or invite the user on this service. Idempotent; never raises."""
        ...

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:
        """Disable (default) or delete the account.

        `delete=True` is destructive and irreversible — Vaultwarden / Teable /
        Twenty mappings should refuse it for OIDC-managed users and downgrade
        to disable, recording the downgrade in `OffboardResult.action`.
        """
        ...
