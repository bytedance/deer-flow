"""Image provider profiles shared by the settings API and sandbox execution."""

from __future__ import annotations

import os
import threading
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from deerflow.config.encrypted_catalog import EncryptedCatalog
from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.runtime_paths import runtime_home


class ImageProvider(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    MINIMAX = "minimax"


class ImageConnectionStatus(StrEnum):
    NOT_CONFIGURED = "not_configured"
    INVALID_CONFIG = "invalid_config"
    CONFIGURED_UNVERIFIED = "configured_unverified"
    READY = "ready"
    UNREACHABLE = "unreachable"


class ImageConfigurationError(ValueError):
    pass


class ImageGenerationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: ImageProvider
    model: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: SecretStr | None = None
    size: str | None = Field(default=None, max_length=50)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = urlsplit(value)
            port = parsed.port
        except ValueError:
            raise ValueError("Invalid image provider URL") from None
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment or port == 0:
            raise ValueError("Use an HTTP(S) image provider URL without credentials, query or fragment")
        return value.rstrip("/")

    @model_validator(mode="after")
    def provider_fields(self) -> ImageGenerationProfile:
        if self.provider == ImageProvider.OPENAI and not self.base_url:
            raise ValueError("OpenAI-compatible image providers require a base URL")
        return self

    def usable(self) -> bool:
        return bool(self.api_key and self.api_key.get_secret_value())

    def command_environment(self) -> dict[str, str]:
        if not self.usable():
            raise ImageConfigurationError("Image generation API key is not configured")
        key = self.api_key.get_secret_value()  # type: ignore[union-attr]
        # Clear image credentials inherited from a previously configured
        # container so the selected profile is the only effective provider.
        env = {
            "IMAGE_GENERATION_PROVIDER": self.provider.value,
            "GEMINI_API_KEY": "",
            "MINIMAX_API_KEY": "",
            "IMAGE_GENERATION_API_KEY": "",
        }
        if self.provider == ImageProvider.OPENAI:
            env.update(
                IMAGE_GENERATION_API_KEY=key,
                IMAGE_GENERATION_BASE_URL=self.base_url or "",
                IMAGE_GENERATION_MODEL=self.model,
            )
            env["IMAGE_GENERATION_SIZE"] = self.size or ""
        elif self.provider == ImageProvider.GEMINI:
            env.update(GEMINI_API_KEY=key, GEMINI_IMAGE_MODEL=self.model)
        else:
            env.update(MINIMAX_API_KEY=key, MINIMAX_IMAGE_MODEL=self.model)
            env["MINIMAX_API_HOST"] = self.base_url or "https://api.minimaxi.com"
        return env


class ManagedImageGenerationProfile(ImageGenerationProfile):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    display_name: str = Field(default="", max_length=100)
    enabled: bool = True
    revision: str | None = None
    verified_generation: bool = False
    verified_edit: bool = False
    last_generation_result: str | None = None
    last_edit_result: str | None = None

    def public(self) -> dict:
        return {
            **self.model_dump(mode="json", exclude={"api_key"}),
            "has_api_key": self.usable(),
            "source": "managed",
        }


_lock = threading.RLock()


class ManagedImageGenerationProfileStore:
    """An encrypted catalog; one profile may be enabled at a time."""

    def __init__(self):
        self._catalog = EncryptedCatalog(runtime_home() / "managed-image-profiles" / "catalog.enc")
        self.path = self._catalog.path
        self.key_path = self._catalog.key_path

    def list(self) -> list[ManagedImageGenerationProfile]:
        try:
            return [ManagedImageGenerationProfile.model_validate(item) for item in self._catalog.read()]
        except Exception:
            raise ValueError("Cannot read managed image profiles; check the catalog and encryption key") from None

    def save(
        self,
        profile: ManagedImageGenerationProfile,
        *,
        expected_revision: str | None,
    ) -> ManagedImageGenerationProfile:
        with _lock, extensions_config_file_lock(self.path):
            records = self.list()
            previous = next((item for item in records if item.name == profile.name), None)
            if previous is None and expected_revision is not None:
                raise FileNotFoundError("Image profile no longer exists")
            if previous is not None and (expected_revision is None or previous.revision != expected_revision):
                raise FileExistsError("Image profile changed; reload before saving")
            if profile.enabled and any(item.enabled and item.name != profile.name for item in records):
                raise ImageConfigurationError("Disable the active image profile before enabling another")
            secret = profile.api_key if profile.api_key is not None else (previous.api_key if previous else None)
            same_provider_settings = bool(
                previous
                and (profile.provider, profile.model, profile.base_url, profile.size) == (previous.provider, previous.model, previous.base_url, previous.size)
                and (secret.get_secret_value() if secret else None) == (previous.api_key.get_secret_value() if previous.api_key else None)
            )
            saved = profile.model_copy(
                update={
                    "api_key": secret,
                    "revision": uuid4().hex,
                    "verified_generation": previous.verified_generation if same_provider_settings else False,
                    "verified_edit": previous.verified_edit if same_provider_settings else False,
                    "last_generation_result": previous.last_generation_result if same_provider_settings else None,
                    "last_edit_result": previous.last_edit_result if same_provider_settings else None,
                }
            )
            records = [saved if item.name == saved.name else item for item in records] if previous else [*records, saved]
            self._write(records)
            return saved

    def record_test(
        self,
        name: str,
        revision: str,
        operation: Literal["generation", "edit"],
        result: str,
    ) -> ManagedImageGenerationProfile:
        with _lock, extensions_config_file_lock(self.path):
            records = self.list()
            profile = next((item for item in records if item.name == name), None)
            if profile is None:
                raise FileNotFoundError("Image profile no longer exists")
            if profile.revision != revision:
                raise FileExistsError("Image profile changed; reload before testing")
            updated = profile.model_copy(
                update={
                    f"verified_{operation}": result == "success",
                    f"last_{operation}_result": result,
                }
            )
            self._write([updated if item.name == name else item for item in records])
            return updated

    def _write(self, records: list[ManagedImageGenerationProfile]) -> None:
        self._catalog.write(
            [
                {
                    **item.model_dump(mode="json", exclude={"api_key"}),
                    "api_key": item.api_key.get_secret_value() if item.api_key else None,
                }
                for item in records
            ]
        )


def _legacy_environment(raw: dict[str, str]) -> dict[str, str]:
    return {key: os.environ.get(value[1:], "") if isinstance(value, str) and value.startswith("$") else str(value) for key, value in raw.items()}


def legacy_image_profile(raw_environment: dict[str, str]) -> ImageGenerationProfile | None:
    env = _legacy_environment(raw_environment)
    raw_provider = env.get("IMAGE_GENERATION_PROVIDER", "").strip().lower()
    if not raw_provider:
        raw_provider = next(
            (
                provider
                for key, provider in (
                    ("GEMINI_API_KEY", "gemini"),
                    ("MINIMAX_API_KEY", "minimax"),
                    ("IMAGE_GENERATION_API_KEY", "openai"),
                )
                if env.get(key)
            ),
            "",
        )
    if not raw_provider:
        return None
    if raw_provider == "openai-compatible":
        raw_provider = "openai"
    if raw_provider == "google":
        raw_provider = "gemini"
    try:
        provider = ImageProvider(raw_provider)
    except ValueError:
        raise ImageConfigurationError("Unknown image generation provider") from None
    if provider == ImageProvider.OPENAI:
        return ImageGenerationProfile(
            provider=provider,
            model=env.get("IMAGE_GENERATION_MODEL") or "gpt-image-2.5-flare",
            base_url=env.get("IMAGE_GENERATION_BASE_URL") or "https://api.openai.com/v1",
            api_key=env.get("IMAGE_GENERATION_API_KEY"),
            size=env.get("IMAGE_GENERATION_SIZE") or None,
        )
    if provider == ImageProvider.GEMINI:
        return ImageGenerationProfile(
            provider=provider,
            model=env.get("GEMINI_IMAGE_MODEL") or "gemini-3-pro-image-preview",
            api_key=env.get("GEMINI_API_KEY"),
        )
    return ImageGenerationProfile(
        provider=provider,
        model=env.get("MINIMAX_IMAGE_MODEL") or "image-01",
        base_url=env.get("MINIMAX_API_HOST") or None,
        api_key=env.get("MINIMAX_API_KEY"),
    )


def resolve_image_generation_profile(
    raw_environment: dict[str, str],
) -> tuple[ImageGenerationProfile | None, str | None, ManagedImageGenerationProfile | None]:
    managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
    if len(managed) > 1:
        raise ImageConfigurationError("Multiple image profiles are enabled")
    if managed:
        return managed[0], "managed", managed[0]
    legacy = legacy_image_profile(raw_environment)
    return legacy, "sandbox_environment" if legacy else None, None
