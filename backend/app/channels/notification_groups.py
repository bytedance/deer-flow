"""SDK-free checks for explicit Feishu group notification destinations."""


def is_feishu_notification_group(*, provider: object, status: object, workspace_id: object, metadata: object) -> bool:
    """Check the group shape; callers must separately verify owner and ID."""
    return provider == "feishu" and status == "connected" and isinstance(workspace_id, str) and bool(workspace_id.strip()) and isinstance(metadata, dict) and metadata.get("chat_type") == "group" and metadata.get("chat_id") == workspace_id
