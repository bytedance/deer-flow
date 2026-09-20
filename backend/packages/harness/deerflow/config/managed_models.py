"""Administrator-managed OpenAI-compatible model profiles, separate from YAML.

The encrypted catalog and its local key live in the persistent runtime home.
Writers are serialized across threads/processes; readers see atomic snapshots.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.file_signature import get_config_signature
from deerflow.config.model_config import ModelConfig
from deerflow.config.runtime_paths import runtime_home

if TYPE_CHECKING:
    from deerflow.config.app_config import AppConfig

_lock = threading.RLock()
_cache: tuple | None = None


class ManagedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
    provider: Literal["openai-compatible"] = "openai-compatible"
    display_name: str = Field(default="", max_length=100)
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(max_length=2048)
    api_key: SecretStr | None = None
    enabled: bool = True
    supports_vision: bool = False
    context_window: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    revision: str | None = None

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value: str) -> str:
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

    def runtime_config(self) -> ModelConfig:
        return ModelConfig(
            name=self.name,
            display_name=self.display_name or self.name,
            use="langchain_openai:ChatOpenAI",
            model=self.model,
            base_url=self.base_url,
            api_key=self.api_key.get_secret_value() if self.api_key and self.api_key.get_secret_value() else "not-required",
            supports_vision=self.supports_vision,
            context_window=self.context_window,
            max_tokens=self.max_tokens,
        )


class ManagedModelStore:
    def __init__(self):
        self.path = runtime_home() / "managed-models" / "catalog.enc"
        self.key_path = self.path.with_name("key")

    def _cipher(self, *, create: bool = False):
        from cryptography.fernet import Fernet

        if not self.key_path.exists():
            if not create or self.path.exists():
                raise ValueError("Managed model encryption key is missing; restore it from backup")
            self._write(self.key_path, Fernet.generate_key())
        return Fernet(self.key_path.read_bytes())

    def list(self) -> list[ManagedModel]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self._cipher().decrypt(self.path.read_bytes()))
            return [ManagedModel.model_validate(item) for item in raw]
        except Exception:
            # Never include provider secrets or decrypted validation inputs.
            raise ValueError("Cannot read managed models; check the catalog and encryption key") from None

    def save(self, config: ManagedModel, *, expected_revision: str | None) -> ManagedModel:
        with _lock, extensions_config_file_lock(self.path):
            records = self.list()
            previous = next((item for item in records if item.name == config.name), None)
            if previous is None and expected_revision is not None:
                raise FileNotFoundError("Model no longer exists")
            if previous is not None and (expected_revision is None or previous.revision != expected_revision):
                raise FileExistsError("Model changed or already exists; reload before saving")
            secret = config.api_key if config.api_key is not None else (previous.api_key if previous else None)
            saved = config.model_copy(update={"api_key": secret, "revision": uuid4().hex})
            records = [saved if item.name == saved.name else item for item in records] if previous else [*records, saved]
            payload = [{**item.model_dump(exclude={"api_key"}), "api_key": item.api_key.get_secret_value() if item.api_key else None} for item in records]
            cipher = self._cipher(create=True)
            self._write(self.path, cipher.encrypt(json.dumps(payload).encode("utf-8")))
            return saved

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


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
