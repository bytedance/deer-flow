"""Image provider profiles shared by the settings API and sandbox execution."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from deerflow.config.encrypted_catalog import EncryptedCatalog
from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.runtime_paths import runtime_home

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig


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


def managed_image_profiles_enabled() -> bool:
    """Deployment-level switch for the web-managed image catalog."""
    value = os.environ.get("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED", "true").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ImageConfigurationError("DEER_FLOW_MANAGED_IMAGE_PROFILES_ENABLED must be true or false")


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

    def server_environment(self) -> dict[str, str]:
        """Represent a typed server profile for the existing image resolver."""
        key = self.api_key.get_secret_value() if self.api_key else ""
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

    def command_environment(self) -> dict[str, str]:
        if not self.usable():
            raise ImageConfigurationError("Image generation API key is not configured")
        return self.server_environment()


class ManagedImageGenerationProfile(ImageGenerationProfile):
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    display_name: str = Field(default="", max_length=100)
    enabled: bool = True
    revision: str | None = None
    verified_generation: bool = False
    verified_edit: bool = False
    last_generation_result: str | None = None
    last_edit_result: str | None = None
    # Historical server snapshot retained for existing encrypted catalogs;
    # coexistence now requires an explicit choice regardless of save order.
    server_model_at_enable: str | None = None

    def public(self) -> dict:
        return {
            **self.model_dump(mode="json", exclude={"api_key", "server_model_at_enable"}),
            "has_api_key": self.usable(),
            "source": "managed",
        }


_lock = threading.RLock()
_selected_image_source: ContextVar[Literal["managed", "sandbox_environment"] | None] = ContextVar("selected_image_source", default=None)


@contextmanager
def bind_image_generation_source(source: Literal["managed", "sandbox_environment"] | None) -> Iterator[None]:
    token = _selected_image_source.set(source)
    try:
        yield
    finally:
        _selected_image_source.reset(token)


def selected_image_generation_source() -> Literal["managed", "sandbox_environment"] | None:
    return _selected_image_source.get() if managed_image_profiles_enabled() else None


class ManagedImageGenerationProfileStore:
    """An encrypted catalog; one profile may be enabled at a time."""

    def __init__(self):
        self._catalog = EncryptedCatalog(runtime_home() / "managed-image-profiles" / "catalog.enc")
        self.path = self._catalog.path
        self.key_path = self._catalog.key_path

    def list(self) -> list[ManagedImageGenerationProfile]:
        if not managed_image_profiles_enabled():
            return []
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
        if not managed_image_profiles_enabled():
            raise ImageConfigurationError("Web-managed image profiles are disabled")
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
        if not managed_image_profiles_enabled():
            raise ImageConfigurationError("Web-managed image profiles are disabled")
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
        if not managed_image_profiles_enabled():
            raise ImageConfigurationError("Web-managed image profiles are disabled")
        self._catalog.write(
            [
                {
                    **item.model_dump(mode="json", exclude={"api_key"}),
                    "api_key": item.api_key.get_secret_value() if item.api_key else None,
                }
                for item in records
            ]
        )


class ImageGenerationDefault(BaseModel):
    source: Literal["managed", "sandbox_environment"]
    target_identity: str
    peer_identity: str | None
    revision: str


def image_profile_identity(profile: ImageGenerationProfile) -> str:
    """Identify a model and endpoint without including its credential."""
    settings = [profile.provider.value, profile.model, profile.base_url, profile.size]
    if isinstance(profile, ManagedImageGenerationProfile):
        settings.insert(0, profile.name)
    return hashlib.sha256(json.dumps(settings, separators=(",", ":")).encode("utf-8")).hexdigest()[:16]


def image_profile_container_identity(profile: ImageGenerationProfile) -> str:
    """Fence startup credentials without exposing the credential in the ID."""
    secret = profile.api_key.get_secret_value() if profile.api_key else ""
    payload = json.dumps([image_profile_identity(profile), secret], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ImageGenerationDefaultStore:
    """Persist an admin-selected default separately from encrypted credentials."""

    def __init__(self):
        self.path = runtime_home() / "managed-image-profiles" / "default.json"

    def read(self) -> ImageGenerationDefault | None:
        if not managed_image_profiles_enabled():
            return None
        if not self.path.exists():
            return None
        try:
            return ImageGenerationDefault.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("Cannot read the image model default") from None

    def save(
        self,
        source: Literal["managed", "sandbox_environment"],
        *,
        target_identity: str,
        expected_revision: str | None,
        environment: dict[str, str],
    ) -> ImageGenerationDefault:
        if not managed_image_profiles_enabled():
            raise ImageConfigurationError("Web-managed image profiles are disabled")
        with _lock, extensions_config_file_lock(self.path):
            try:
                current = self.read()
            except ValueError:
                if expected_revision is not None:
                    raise FileExistsError("Image model default changed; reload before saving") from None
                current = None
            if (current.revision if current else None) != expected_revision:
                raise FileExistsError("Image model default changed; reload before saving")
            managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
            if len(managed) > 1:
                raise ImageConfigurationError("Multiple image profiles are enabled")
            web = managed[0] if managed else None
            try:
                server = legacy_image_profile(environment)
            except ValueError:
                if source == "sandbox_environment":
                    raise
                server = None
            target = web if source == "managed" else server
            peer = server if source == "managed" else web
            if target is None or not target.usable() or image_profile_identity(target) != target_identity:
                raise ImageConfigurationError("Image model changed; reload before setting the default")
            saved = ImageGenerationDefault(
                source=source,
                target_identity=target_identity,
                peer_identity=image_profile_identity(peer) if peer is not None and peer.usable() else None,
                revision=uuid4().hex,
            )
            EncryptedCatalog.write_bytes(self.path, saved.model_dump_json().encode("utf-8"))
            return saved


class ServerImageProbeStore:
    """Remember admin probe results for the exact current server settings."""

    def __init__(self):
        self._catalog = EncryptedCatalog(runtime_home() / "managed-image-profiles" / "server-probes.enc")

    @staticmethod
    def _fingerprint(profile: ImageGenerationProfile) -> str:
        return image_profile_container_identity(profile)

    def results(self, profile: ImageGenerationProfile) -> dict[str, str]:
        records = self._catalog.read()
        if not records or records[0].get("fingerprint") != self._fingerprint(profile):
            return {}
        return {operation: records[0][operation] for operation in ("generation", "edit") if isinstance(records[0].get(operation), str)}

    def record(self, profile: ImageGenerationProfile, operation: Literal["generation", "edit"], result: str) -> None:
        with _lock, extensions_config_file_lock(self._catalog.path):
            previous = self.results(profile)
            self._catalog.write([{"fingerprint": self._fingerprint(profile), **previous, operation: result}])


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


def resolve_server_image_profile(config: AppConfig) -> ImageGenerationProfile | None:
    """Resolve the one operator-owned image profile, whichever YAML form supplied it."""
    return legacy_image_profile(image_environment(config))


def image_environment(config: AppConfig) -> dict[str, str]:
    """Return normalized image settings, including legacy config test doubles."""
    environment = getattr(config, "image_generation_environment", None)
    return environment if environment is not None else getattr(getattr(config, "sandbox", None), "environment", {})


def legacy_image_model_identity(raw_environment: dict[str, str]) -> str | None:
    profile = legacy_image_profile(raw_environment)
    return f"{profile.provider.value}:{profile.model}" if profile is not None else None


def legacy_image_storage_identity(raw_environment: dict[str, str]) -> str | None:
    """Identify server image settings without putting the API key in a sandbox id."""
    profile = legacy_image_profile(raw_environment)
    if profile is None:
        return None
    return image_profile_identity(profile)


def _saved_default_source(managed: ManagedImageGenerationProfile | None, legacy: ImageGenerationProfile | None) -> Literal["managed", "sandbox_environment"] | None:
    selection = ImageGenerationDefaultStore().read()
    if selection is None:
        return None
    target = managed if selection.source == "managed" else legacy
    peer = legacy if selection.source == "managed" else managed
    if target is None or not target.usable() or image_profile_identity(target) != selection.target_identity:
        return None
    peer_identity = image_profile_identity(peer) if peer is not None and peer.usable() else None
    return selection.source if peer_identity == selection.peer_identity else None


def saved_image_generation_source(raw_environment: dict[str, str]) -> Literal["managed", "sandbox_environment"] | None:
    """Return the saved admin default only while its model context still matches."""
    if not managed_image_profiles_enabled():
        return None
    managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
    if len(managed) > 1:
        raise ImageConfigurationError("Multiple image profiles are enabled")
    try:
        legacy = legacy_image_profile(raw_environment)
    except ValueError:
        if not managed:
            raise
        legacy = None
    return _saved_default_source(managed[0] if managed else None, legacy)


def effective_image_generation_source(raw_environment: dict[str, str]) -> Literal["managed", "sandbox_environment"] | None:
    """Return an explicit chat choice or a still-valid saved admin default."""
    return selected_image_generation_source() or saved_image_generation_source(raw_environment)


def image_generation_source_for_run(raw_environment: dict[str, str], *, allows_clarification: bool) -> Literal["managed", "sandbox_environment"] | None:
    """Use the server image model when an unattended run cannot resolve a choice."""
    source = effective_image_generation_source(raw_environment)
    if source is not None or allows_clarification:
        return source
    return "sandbox_environment" if image_profile_choice_needed(raw_environment) else None


def image_profile_choice_needed(raw_environment: dict[str, str]) -> bool:
    if not managed_image_profiles_enabled():
        return False
    managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
    if len(managed) > 1:
        raise ImageConfigurationError("Multiple image profiles are enabled")
    if not managed:
        return False
    try:
        legacy = legacy_image_profile(raw_environment)
    except ValueError:
        legacy = None
    if legacy is None or not legacy.usable() or not managed[0].usable():
        return False
    return _saved_default_source(managed[0], legacy) is None


def resolve_image_generation_profile(
    raw_environment: dict[str, str],
) -> tuple[ImageGenerationProfile | None, str | None, ManagedImageGenerationProfile | None]:
    if not managed_image_profiles_enabled():
        server = legacy_image_profile(raw_environment)
        return server, "sandbox_environment" if server else None, None
    managed = [item for item in ManagedImageGenerationProfileStore().list() if item.enabled]
    if len(managed) > 1:
        raise ImageConfigurationError("Multiple image profiles are enabled")
    try:
        legacy = legacy_image_profile(raw_environment)
    except ValueError:
        if not managed or _selected_image_source.get() == "sandbox_environment":
            raise
        legacy = None
    source = _selected_image_source.get() or _saved_default_source(managed[0] if managed else None, legacy)
    if source == "sandbox_environment":
        return legacy, "sandbox_environment" if legacy else None, None
    if managed:
        return managed[0], "managed", managed[0]
    return legacy, "sandbox_environment" if legacy else None, None
