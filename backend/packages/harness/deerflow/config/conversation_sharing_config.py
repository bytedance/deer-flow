from pydantic import BaseModel, Field


class ConversationSharingConfig(BaseModel):
    """Configuration for read-only conversation sharing (#4548).

    Disabled by default: public sharing is an opt-in deployment feature.
    The share-token pepper is deliberately NOT a YAML field — it lives in the
    process environment or the operator-managed secret store, never in
    persisted application data.
    """

    enabled: bool = Field(default=False, description="Whether owners can create public read-only share links")
    default_expiry_days: int = Field(default=30, ge=1, le=365, description="Default link lifetime in days")
    allow_no_expiry: bool = Field(
        default=False,
        description="Allow the explicit 'never expires' advanced choice when creating a share",
    )
