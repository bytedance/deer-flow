"""Google Workspace user lifecycle via Admin SDK Directory API.

Authentication uses a Google Cloud service account with **domain-wide
delegation** enabled in the Workspace admin console — that's the only
auth shape that lets a non-interactive process create users on behalf
of the workspace. Plain user OAuth (which is what Gmail / Drive MCP
servers use) cannot reach the Directory API even with admin consent.

Setup checklist (one-time per Workspace tenant):

1. GCP Console → IAM → Service Accounts → create one for Start-Cloud.
2. Service Account → Keys → JSON → download. Path goes in
   ``GOOGLE_ADMIN_SERVICE_ACCOUNT_FILE``.
3. Service Account → Show advanced settings → copy the OAuth client ID.
4. Workspace Admin Console → Security → API Controls → Domain-wide
   delegation → Add new. Paste the client ID; scopes:
   ``https://www.googleapis.com/auth/admin.directory.user``.
5. Pick a real workspace admin email (not the service account itself);
   the SDK impersonates this user. Goes in
   ``GOOGLE_ADMIN_IMPERSONATE_EMAIL``.
6. Domain that owns the user accounts (e.g. ``bigbangangels.com``)
   goes in ``GOOGLE_ADMIN_DOMAIN``.

If any of those env vars are missing, ``is_configured()`` returns False
and the orchestrator skips this client without failing the run.

Idempotency: ``users.insert`` returns 409 Conflict for an existing
``primaryEmail``. We treat that as success, look up the existing user
to fill ``account_id``, and add a note. Same shape as the other
clients per the contract.
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from typing import Any

from .base import OffboardResult, OnboardRequest, OnboardResult

logger = logging.getLogger(__name__)

_DIRECTORY_SCOPE = "https://www.googleapis.com/auth/admin.directory.user"


class GoogleAdminClient:
    """Service-account-backed Admin SDK client.

    Concrete implementation of `ServiceOnboardClient` for Google Workspace.
    """

    service_name: str = "google"

    def __init__(
        self,
        *,
        service_account_file: str | None = None,
        impersonate_email: str | None = None,
        domain: str | None = None,
    ) -> None:
        self._service_account_file = service_account_file or os.environ.get(
            "GOOGLE_ADMIN_SERVICE_ACCOUNT_FILE"
        )
        self._impersonate_email = impersonate_email or os.environ.get(
            "GOOGLE_ADMIN_IMPERSONATE_EMAIL"
        )
        self._domain = domain or os.environ.get("GOOGLE_ADMIN_DOMAIN")
        self._service: Any | None = None  # Lazily built googleapiclient resource

    # ── Conformance ────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(
            self._service_account_file
            and self._impersonate_email
            and self._domain
            and os.path.exists(self._service_account_file)
        )

    def create_user(self, req: OnboardRequest) -> OnboardResult:
        if not self.is_configured():
            return OnboardResult(
                service_name=self.service_name,
                success=False,
                error="GoogleAdminClient is not configured (missing service account or env vars).",
            )

        password = req.temporary_password or _generate_temp_password()

        body = {
            "primaryEmail": req.email,
            "name": {
                "givenName": req.first_name,
                "familyName": req.last_name,
            },
            "password": password,
            "changePasswordAtNextLogin": True,
        }

        try:
            service = self._get_service()
            user = service.users().insert(body=body).execute()
            return OnboardResult(
                service_name=self.service_name,
                success=True,
                account_id=user.get("id"),
                login_url="https://workspace.google.com/dashboard",
                temporary_credentials={"temporary_password": password},
            )
        except Exception as e:  # broad on purpose — contract says never raise
            return self._handle_create_error(e, req, password)

    def offboard_user(self, email: str, *, delete: bool = False) -> OffboardResult:
        if not self.is_configured():
            return OffboardResult(
                service_name=self.service_name,
                success=False,
                action="failed",
                error="GoogleAdminClient is not configured.",
            )

        try:
            service = self._get_service()
            if delete:
                service.users().delete(userKey=email).execute()
                return OffboardResult(
                    service_name=self.service_name,
                    success=True,
                    action="deleted",
                )
            # Suspend instead of delete — reversible, preserves data.
            service.users().update(
                userKey=email, body={"suspended": True}
            ).execute()
            return OffboardResult(
                service_name=self.service_name,
                success=True,
                action="disabled",
            )
        except Exception as e:
            return self._handle_offboard_error(e, email)

    # ── Internals ──────────────────────────────────────────────────────────

    def _get_service(self) -> Any:
        if self._service is not None:
            return self._service

        # Imported lazily so a deployment without google-api-python-client
        # installed (or with the env vars absent) doesn't fail at import time.
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            self._service_account_file,
            scopes=[_DIRECTORY_SCOPE],
        ).with_subject(self._impersonate_email)

        # cache_discovery=False silences a noisy warning under non-cached envs.
        self._service = build(
            "admin", "directory_v1", credentials=creds, cache_discovery=False
        )
        return self._service

    def _handle_create_error(
        self, exc: Exception, req: OnboardRequest, password: str
    ) -> OnboardResult:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError) and exc.resp.status == 409:
            # User already exists — look it up to fill account_id.
            try:
                existing = self._get_service().users().get(userKey=req.email).execute()
                return OnboardResult(
                    service_name=self.service_name,
                    success=True,
                    account_id=existing.get("id"),
                    login_url="https://workspace.google.com/dashboard",
                    notes=[f"Account already existed; not modified: {req.email}"],
                )
            except Exception as inner:
                logger.warning("Existing-user lookup failed for %s: %s", req.email, inner)
                return OnboardResult(
                    service_name=self.service_name,
                    success=True,
                    notes=[
                        f"Account exists for {req.email} but lookup failed; "
                        "treated as success."
                    ],
                )

        message = _format_http_error(exc)
        logger.error("Google Admin create_user failed for %s: %s", req.email, message)
        return OnboardResult(
            service_name=self.service_name,
            success=False,
            error=message,
            temporary_credentials={"temporary_password": password},
        )

    def _handle_offboard_error(self, exc: Exception, email: str) -> OffboardResult:
        from googleapiclient.errors import HttpError

        if isinstance(exc, HttpError) and exc.resp.status == 404:
            return OffboardResult(
                service_name=self.service_name,
                success=True,
                action="not_found",
            )
        message = _format_http_error(exc)
        logger.error("Google Admin offboard failed for %s: %s", email, message)
        return OffboardResult(
            service_name=self.service_name,
            success=False,
            action="failed",
            error=message,
        )


# ─────────────────────────────────────────────────────────────────────────────


def _generate_temp_password(length: int = 16) -> str:
    """Workspace requires ≥8 chars + mixed case + digit. 16 chars covers it."""
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pw)
            and any(c.isupper() for c in pw)
            and any(c.isdigit() for c in pw)
        ):
            return pw


def _format_http_error(exc: Exception) -> str:
    """Surface the most actionable bit of a googleapiclient HttpError."""
    from googleapiclient.errors import HttpError

    if isinstance(exc, HttpError):
        try:
            import json

            content = json.loads(exc.content.decode("utf-8"))
            msg = content.get("error", {}).get("message")
            if msg:
                return f"HTTP {exc.resp.status}: {msg}"
        except Exception:
            pass
        return f"HTTP {exc.resp.status}: {exc}"
    return f"{type(exc).__name__}: {exc}"
