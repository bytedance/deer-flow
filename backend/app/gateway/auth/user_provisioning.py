"""User provisioning for OIDC logins.

Handles the logic of finding existing users, auto-creating new ones, and
enforcing email domain restrictions. A pre-existing local account is never
auto-linked to an OIDC identity: an email collision blocks the SSO login with
a 409 instead, so an SSO login can never seize a local password account.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException, status

from app.gateway.auth.local_provider import LocalAuthProvider
from app.gateway.auth.oidc import OIDCIdentity
from deerflow.config.auth_config import OIDCProviderConfig

logger = logging.getLogger(__name__)


async def get_or_provision_oidc_user(
    provider_id: str,
    provider_config: OIDCProviderConfig,
    identity: OIDCIdentity,
    local_provider: LocalAuthProvider,
) -> dict:
    """Resolve an OIDC identity to a DeerFlow user.

    Flow:
    1. Look up existing user by (provider, subject)
    2. If not found, enforce domain/email-verified rules
    3. Block if a local account already owns the email (never auto-link)
    4. Auto-create if enabled

    Returns a dict with ``user`` (the User model instance) and ``created`` (bool).
    """
    # 1. Existing OAuth link
    existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
    if existing:
        return {"user": existing, "created": False}

    # 2. Verified email requirement
    if provider_config.require_verified_email and not identity.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Your email could not be verified by the identity provider. Please contact your administrator."),
        )

    if not identity.email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The identity provider did not provide an email address.",
        )

    email = identity.email.lower()

    # 3. Domain restriction
    if provider_config.allowed_email_domains:
        domain = email.rsplit("@", 1)[-1]
        if domain not in {d.lower().lstrip("@") for d in provider_config.allowed_email_domains}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your email domain is not allowed. Please use an approved email address.",
            )

    # 4. Block if a local account already owns this email. We never auto-link an
    # SSO identity onto a pre-existing local account, since that would let an SSO
    # login take over a password account that happens to share the email.
    local_user = await local_provider.get_user_by_email(email)

    if local_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("An account with this email already exists. Contact your administrator to link it to your SSO account."),
        )

    # 5. Auto-create
    if not provider_config.auto_create_users:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Automatic account creation is disabled. Contact your administrator.",
        )

    role = _resolve_role(email, provider_config.admin_emails)
    try:
        user = await local_provider.create_oauth_user(
            email=email,
            oauth_provider=provider_id,
            oauth_id=identity.subject,
            system_role=role,
        )
    except ValueError:
        # Lost a race: a concurrent callback (double-click, replayed code) already
        # inserted a row that collides on the unique index. Re-resolve instead of
        # bubbling a raw 500. If the winner created this same identity, return it;
        # otherwise the email now belongs to a different account → 409.
        existing = await local_provider.get_user_by_oauth(provider_id, identity.subject)
        if existing:
            return {"user": existing, "created": False}
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("An account with this email already exists. Contact your administrator to link it to your SSO account."),
        ) from None
    logger.info("Auto-created OIDC user %s (provider=%s, role=%s)", email, provider_id, role)
    return {"user": user, "created": True}


def _resolve_role(email: str, admin_emails: list[str]) -> str:
    """Return ``admin`` if the email is in the admin list, otherwise ``user``."""
    email_lower = email.lower()
    return "admin" if any(e.lower() == email_lower for e in admin_emails) else "user"
