"""Administrator-managed model profiles, separate from YAML.

The encrypted catalog and its local key live in the persistent runtime home.
Writers are serialized across threads/processes; readers see atomic snapshots.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator, model_validator

from deerflow.config._boolean_guards import reject_boolean
from deerflow.config.encrypted_catalog import EncryptedCatalog
from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.file_signature import get_config_signature
from deerflow.config.managed_model_providers import get_managed_model_provider, resolve_managed_model_provider, resolve_preset_model
from deerflow.config.model_config import ModelConfig, ReasoningCapabilities
from deerflow.config.runtime_paths import runtime_home

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

_lock = threading.RLock()
_cache: tuple | None = None


class ManagedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(default="", pattern=r"^(?:[A-Za-z0-9][A-Za-z0-9_.-]{0,99})?$")
    provider: str = "openai-compatible"
    display_name: str = Field(default="", max_length=100)
    model: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: SecretStr | None = None
    enabled: bool = True
    supports_vision: bool | None = None
    reasoning: ReasoningCapabilities | None = None
    context_window: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    revision: str | None = None

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            url = urlsplit(value)
            port = url.port
        except ValueError:
            raise ValueError("Invalid endpoint URL") from None
        if url.scheme not in {"https", "http"} or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment or (port is not None and port == 0):
            raise ValueError("Use an HTTP(S) base URL without credentials, query or fragment")
        return value.rstrip("/")

    def public(self) -> dict:
        return {**self.model_dump(exclude={"api_key"}), "has_api_key": bool(self.api_key and self.api_key.get_secret_value()), "source": "managed"}

    @field_validator("context_window", "max_tokens", mode="before")
    @classmethod
    def numeric_capabilities(cls, value: object, info: ValidationInfo) -> object:
        return reject_boolean(value, info, kind="an integer")

    @field_validator("provider")
    @classmethod
    def valid_provider(cls, value: str) -> str:
        get_managed_model_provider(value)
        return value

    @field_validator("model")
    @classmethod
    def valid_model_id(cls, value: str) -> str:
        if any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
            raise ValueError("Model IDs cannot contain control characters")
        return value

    @field_validator("api_key")
    @classmethod
    def reject_mask(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and re.fullmatch(r"[＊*•●]+", value.get_secret_value()):
            raise ValueError("Enter a real API key, not a password mask")
        if value is not None and value.get_secret_value() and not value.get_secret_value().strip():
            raise ValueError("API keys cannot consist only of whitespace")
        return value

    @model_validator(mode="after")
    def validate_routing(self) -> ManagedModel:
        if self.provider == "openai-compatible":
            if not self.base_url:
                raise ValueError("Custom providers require a base URL")
        elif self.base_url is not None:
            raise ValueError("Preset endpoints cannot be overridden")
        if self.reasoning and self.reasoning.effort and self.reasoning.effort.path not in {"reasoning_effort", "extra_body.reasoning_effort", "output_config.effort", "effort"}:
            raise ValueError("Managed reasoning effort must target a request effort parameter")
        return self

    def runtime_config(self) -> ModelConfig:
        api_key = self.api_key.get_secret_value() if self.api_key else None
        if self.provider == "openai-compatible":
            settings = {**resolve_managed_model_provider(self.base_url), "api_key": api_key or "not-required"}
        else:
            if not api_key:
                raise ValueError("This provider requires an API key")
            settings = resolve_preset_model(self.provider, self.model, api_key)
        if self.reasoning is not None:
            # Remove derived legacy fields/templates when an admin supplies a
            # contract. Protocol dialect is still interpreted by the factory.
            for field in ("reasoning", "supports_thinking", "supports_reasoning_effort"):
                settings.pop(field, None)
            if self.reasoning.thinking == "unsupported":
                settings.pop("when_thinking_enabled", None)
            if self.reasoning.thinking == "required":
                settings.pop("when_thinking_disabled", None)
            settings["reasoning"] = self.reasoning
        if self.supports_vision is not None:
            settings["supports_vision"] = self.supports_vision
        if self.max_tokens is not None:
            settings["max_tokens"] = self.max_tokens
        return ModelConfig(
            name=self.name or "connection-check",
            display_name=self.display_name or f"{get_managed_model_provider(self.provider).display_name} · {self.model}"[:100],
            model=self.model,
            context_window=self.context_window,
            **settings,
        )


class ManagedModelInputError(ValueError):
    """Safe user input errors, separate from encryption/storage failures."""


def retained_api_key(config: ManagedModel, previous: ManagedModel | None) -> SecretStr | None:
    """Never reuse credentials after changing the provider or custom endpoint."""
    if config.api_key is not None:
        return config.api_key
    if previous and (previous.provider, previous.base_url) == (config.provider, config.base_url):
        return previous.api_key
    return None


class ManagedModelStore:
    def __init__(self):
        self._catalog = EncryptedCatalog(runtime_home() / "managed-models" / "catalog.enc")
        self.path = self._catalog.path
        self.key_path = self._catalog.key_path

    def _cipher(self, *, create: bool = False):
        return self._catalog._cipher(create=create)

    def list(self) -> list[ManagedModel]:
        try:
            raw = self._catalog.read()
            return [ManagedModel.model_validate(item) for item in raw]
        except Exception:
            # Never include provider secrets or decrypted validation inputs.
            raise ValueError("Cannot read managed models; check the catalog and encryption key") from None

    def save(self, config: ManagedModel, *, expected_revision: str | None, reserved_names: set[str] | None = None) -> ManagedModel:
        with _lock, extensions_config_file_lock(self.path):
            records = self.list()
            if not config.name:
                if expected_revision is not None:
                    raise ManagedModelInputError("An existing model name is required when editing")
                slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", config.model).strip("-._") or "model"
                names = {item.name for item in records} | (reserved_names or set())
                while True:
                    name = f"{config.provider}-{slug}"[:85].rstrip("-._") + "-" + uuid4().hex[:12]
                    if name not in names:
                        break
                config = config.model_copy(update={"name": name})
            previous = next((item for item in records if item.name == config.name), None)
            if previous is None and expected_revision is not None:
                raise FileNotFoundError("Model no longer exists")
            if previous is not None and (expected_revision is None or previous.revision != expected_revision):
                raise FileExistsError("Model changed or already exists; reload before saving")
            secret = retained_api_key(config, previous)
            if config.provider != "openai-compatible" and config.enabled and not (secret and secret.get_secret_value()):
                raise ManagedModelInputError("This provider requires an API key; enter a key or disable the model")
            display_name = config.display_name or f"{get_managed_model_provider(config.provider).display_name} · {config.model}"[:100]
            # Validate capability overrides before any encrypted write.
            candidate = config.model_copy(update={"api_key": secret})
            if config.enabled:
                try:
                    candidate.runtime_config()
                except ValueError:
                    raise ManagedModelInputError("Invalid model capability overrides") from None
            saved = config.model_copy(update={"api_key": secret, "display_name": display_name, "revision": uuid4().hex})
            records = [saved if item.name == saved.name else item for item in records] if previous else [*records, saved]
            payload = [{**item.model_dump(exclude={"api_key"}), "api_key": item.api_key.get_secret_value() if item.api_key else None} for item in records]
            self._catalog.write(payload)
            return saved

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        EncryptedCatalog.write_bytes(path, content)


def merge_managed_models(config: AppConfig) -> AppConfig:
    """Return a fresh effective snapshot on changes; never mutate an active run."""
    global _cache
    store = ManagedModelStore()
    signature = (str(store.path), get_config_signature(store.path), get_config_signature(store.key_path))
    if signature[1] is None:
        return config
    with _lock:
        if _cache is not None and _cache[0] is config and _cache[1] == signature:
            return _cache[2]
        yaml_names = {item.name for item in config.models}
        managed = [item.runtime_config() for item in store.list() if item.enabled and item.name not in yaml_names]
        result = config.model_copy(update={"models": [*config.models, *managed]})
        result._models_by_name = {**config._models_by_name, **{item.name: item for item in managed}}
        result._managed_model_names = {item.name for item in managed}
        _cache = (config, signature, result)
        return result
