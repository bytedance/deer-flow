"""Operator-configured, optional speech-to-text for the composer."""

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class VoiceInputConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    base_url: str = Field(description="OpenAI-compatible API base URL, including /v1 if required")
    model: str = Field(min_length=1, description="Transcription model served by this endpoint")
    api_key: SecretStr | None = Field(default=None, description="Optional bearer key; supports $ENV_VAR through AppConfig")
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$", description="Optional ISO-639-1 language hint; omit for automatic detection")
    max_audio_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=25 * 1024 * 1024)
    max_duration_seconds: int = Field(default=120, ge=1, le=600, description="Browser recording time limit")
    timeout_seconds: int = Field(default=60, ge=1, le=120, description="Total provider request timeout")

    @field_validator("max_audio_bytes", "max_duration_seconds", "timeout_seconds", mode="before")
    @classmethod
    def reject_boolean_limits(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("base_url must be an HTTP(S) API base URL without credentials, query or fragment")
        # Validate the port even though the provider client builds the URL later.
        _ = parsed.port
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model must not be blank")
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and (not value.get_secret_value().strip() or any(c in value.get_secret_value() for c in "\r\n")):
            raise ValueError("api_key must not be blank or contain newlines")
        return value
