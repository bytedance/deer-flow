"""Configuration for the PII redaction middleware (issue #3190)."""

from pydantic import BaseModel, Field


class PiiRedactionConfig(BaseModel):
    """Configuration for deterministic PII redaction in model-bound context.

    Default-off. When enabled, personally identifiable information found in
    genuine user messages and remote-content tool results is rewritten to
    irreversible placeholders (``[EMAIL_1]`` …) before it reaches the model.
    Each detector can be toggled independently for deployments that only need
    a subset (e.g. credentials but not phone numbers).
    """

    enabled: bool = Field(
        default=False,
        description="Whether to enable PII redaction in model-bound context",
    )
    redact_email: bool = Field(
        default=True,
        description="Redact email addresses",
    )
    redact_api_key: bool = Field(
        default=True,
        description="Redact API keys and bearer-style tokens (OpenAI sk-, AWS AKIA, GitHub ghp_/github_pat_, Slack xox-, Google AIza)",
    )
    redact_credit_card: bool = Field(
        default=True,
        description="Redact credit-card numbers passing the Luhn checksum",
    )
    redact_phone: bool = Field(
        default=True,
        description="Redact phone numbers (international +CC form, CN mobile, US formatted)",
    )
    redact_national_id: bool = Field(
        default=True,
        description="Redact national IDs (CN resident ID and CPF with checksum validation, formatted CUIT/RFC)",
    )
