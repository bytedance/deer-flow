"""Resolve durable item owners through the Gateway's current account store."""

from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, get_auth_disabled_user, is_auth_disabled
from deerflow.authz.provider import Principal


async def resolve_batch_principal(batch, *, load_user) -> Principal:
    owner = batch["user_id"]
    spec = batch["execution_spec"]
    internal = spec.get("is_internal") is True
    if owner == AUTH_DISABLED_USER_ID and is_auth_disabled():
        user = get_auth_disabled_user()
    else:
        try:
            if load_user is None:
                raise RuntimeError("Account repository unavailable")
            user = await load_user(owner)
        except Exception:
            # Never restore serialized grants when the account store fails.
            raise PermissionError("Batch owner could not be verified") from None
    if user is None:
        # Gateway stamps no role on an unmapped, trusted internal identity.
        # A missing formerly mapped account must not take this fallback.
        if internal and spec.get("user_role") is None:
            return Principal(user_id=owner, is_internal=True, channel_user_id=spec.get("channel_user_id"))
        raise PermissionError("Batch owner is no longer available")
    if str(user.id) != owner or getattr(user, "disabled", False) or user.needs_setup:
        raise PermissionError("Batch owner is no longer active")
    if user.system_role != spec.get("user_role"):
        # Custom roles are not ordered. Refuse changed grants rather than
        # retaining a revoked role or widening old work after a promotion.
        raise PermissionError("Batch owner role changed; submit a new batch with current permissions")
    return Principal(
        user_id=owner,
        role=user.system_role,
        oauth_provider=user.oauth_provider,
        oauth_id=getattr(user, "oauth_id", None),
        channel_user_id=spec.get("channel_user_id"),
        is_internal=internal,
        # Gateway admission does not mint ABAC attributes. Stored attributes
        # and OAuth claims are not a renewable source of authority.
    )
