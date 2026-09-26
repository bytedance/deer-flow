"""Configuration for the PII redaction middleware (issue #3190)."""

from pydantic import BaseModel, Field, model_validator

# Minimum accepted token_secret length: a short secret makes the keyed digest
# brute-forceable offline for low-entropy identifiers (e.g. phone numbers).
MIN_TOKEN_SECRET_LENGTH = 16


class PiiRedactionConfig(BaseModel):
    """Configuration for deterministic PII redaction in model-bound context.

    Default-off. When enabled, personally identifiable information found in
    genuine user messages and remote-content tool results is rewritten to
    keyed, value-derived placeholders (128-bit HMAC digests encoded over
    base-26 letters, keyed by the required ``token_secret``) before it reaches
    the model.
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
    token_secret: str | None = Field(
        default=None,
        description=(
            "Deployment-scoped secret used as the HMAC key for placeholder "
            "digests; required (non-empty, at least 16 characters) whenever "
            "enabled is true. Tokens are linkable only within this deployment "
            "and cannot be re-derived offline without the secret — an unkeyed "
            "digest would instead be a publicly computable, globally linkable "
            "fingerprint of the raw values."
        ),
    )

    @model_validator(mode="after")
    def _token_secret_required_when_enabled(self) -> "PiiRedactionConfig":
        """Reject enabling redaction without a usable key (review round 11 on #5577).

        An unkeyed digest is a publicly computable fingerprint: linkable
        across deployments and confirmable by offline guessing for low-entropy
        values such as phone numbers, which defeats the module's
        re-identification guarantee for exactly the values redaction exists to
        protect.
        """
        if not self.enabled:
            return self
        if self.token_secret is None or not self.token_secret.strip():
            raise ValueError("pii_redaction.enabled=true requires a non-empty token_secret: without a deployment-scoped HMAC key, placeholders are publicly computable fingerprints linkable across deployments")
        if len(self.token_secret) < MIN_TOKEN_SECRET_LENGTH:
            raise ValueError(f"token_secret must be at least {MIN_TOKEN_SECRET_LENGTH} characters; use a long random value")
        return self
