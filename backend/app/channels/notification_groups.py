"""SDK-free checks for explicit group notification destinations."""

from __future__ import annotations

from collections.abc import Mapping


def notification_group_display_name(metadata: object) -> str | None:
    """Read the bounded label from the owner's browser-issued binding state."""
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("notification_group_name")
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:256] or None


def is_feishu_notification_group(*, provider: object, status: object, workspace_id: object, metadata: object) -> bool:
    """Check the Feishu group shape; callers must separately verify owner and ID."""
    return (
        provider == "feishu" and status == "connected" and isinstance(workspace_id, str) and bool(workspace_id.strip()) and isinstance(metadata, Mapping) and metadata.get("chat_type") == "group" and metadata.get("chat_id") == workspace_id
    )


def qq_notification_group_openid(
    *,
    provider: object,
    status: object,
    workspace_id: object,
    metadata: object,
    app_id: str | None = None,
) -> str | None:
    """Return the bound QQ ``group_openid`` when the connection is a valid QQ group binding."""
    if provider != "qq" or status != "connected" or not isinstance(workspace_id, str) or ":group:" not in workspace_id:
        return None
    bound_app_id, _sep, group_openid = workspace_id.partition(":group:")
    if not bound_app_id.strip() or bound_app_id != bound_app_id.strip() or not group_openid.strip() or group_openid != group_openid.strip():
        return None
    if app_id is not None and bound_app_id != app_id:
        return None
    if not isinstance(metadata, Mapping) or metadata.get("chat_type") != "group":
        return None
    meta_openid = metadata.get("group_openid")
    if meta_openid is not None and (not isinstance(meta_openid, str) or meta_openid != group_openid):
        return None
    return group_openid


def wecom_notification_group_chat_id(
    *,
    provider: object,
    status: object,
    workspace_id: object,
    metadata: object,
    bot_id: str | None = None,
) -> str | None:
    """Return the bound WeCom ``chatid`` when the connection is a valid WeCom group binding."""
    if provider != "wecom" or status != "connected" or not isinstance(workspace_id, str) or not isinstance(metadata, Mapping):
        return None
    if metadata.get("chattype") != "group":
        return None
    chatid = metadata.get("chatid")
    if not isinstance(chatid, str) or not chatid.strip() or chatid != chatid.strip():
        return None
    aibotid = metadata.get("aibotid")
    if aibotid is None or aibotid == "":
        expected_workspace_id = f"group:{chatid}"
    elif isinstance(aibotid, str) and bool(aibotid.strip()) and aibotid == aibotid.strip():
        if bot_id and aibotid != bot_id:
            return None
        expected_workspace_id = f"{aibotid}:group:{chatid}"
    else:
        return None
    if workspace_id != expected_workspace_id:
        return None
    return chatid


def is_notification_group(*, provider: object, status: object, workspace_id: object, metadata: object) -> bool:
    """Whether a channel connection record represents an eligible group notification target."""
    if is_feishu_notification_group(provider=provider, status=status, workspace_id=workspace_id, metadata=metadata):
        return True
    if qq_notification_group_openid(provider=provider, status=status, workspace_id=workspace_id, metadata=metadata) is not None:
        return True
    if wecom_notification_group_chat_id(provider=provider, status=status, workspace_id=workspace_id, metadata=metadata) is not None:
        return True
    return False
