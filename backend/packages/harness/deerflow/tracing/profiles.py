"""Tracing control plane and encrypted, immutable admission snapshots.

All public functions perform blocking storage I/O. Async callers must offload them.
Raw credentials are decrypted only for execution; public projections never carry them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from deerflow.config.credentials_key import CredentialsCipher, CredentialsDecryptError, get_credentials_cipher
from deerflow.config.tracing_config import get_tracing_config
from deerflow.persistence.tracing_profiles.sql import ProfileRevisionConflict, SqlTracingProfileRepository

TracingMode = Literal["inherit", "disabled", "configured"]
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class TracingControlError(Exception):
    code = "tracing_unavailable"
    status_code = 503


class TracingUnavailableError(TracingControlError):
    """Authority, encryption or an immutable snapshot is unavailable."""


class TracingConflictError(TracingControlError):
    code = "tracing_revision_conflict"
    status_code = 409


class TracingAuthorizationError(TracingControlError):
    code = "tracing_profile_forbidden"
    status_code = 403


class TracingInputError(TracingControlError):
    code = "invalid_tracing_configuration"
    status_code = 422


class TracingOperatorLockError(TracingControlError):
    code = "tracing_operator_lock"
    status_code = 409


class ProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: Literal["arize", "langsmith", "langfuse"]
    endpoint: str
    project: str = ""
    space_id: str = ""
    workspace_id: str = ""
    public_key: str = ""
    api_key: SecretStr | None = None
    secret_key: SecretStr | None = None
    transport: Literal["http", "grpc"] = "http"

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        try:
            endpoint = urlsplit(value)
            port = endpoint.port
            del port
        except ValueError:
            raise ValueError("Invalid tracing endpoint") from None
        if endpoint.scheme not in {"http", "https"} or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or any(ord(char) < 33 for char in value):
            raise ValueError("Tracing endpoint must be an HTTP(S) URL without credentials, query or fragment")
        return value.rstrip("/")


class RunTracingSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    owner_user_id: str
    agent_name: str
    mode: TracingMode
    revision: str
    providers: tuple[ProviderConfig, ...]
    monocle_enabled: bool = False
    monocle_fingerprint: str = ""
    agent_incarnation: str = ""


def canonical_agent_name(name: str | None) -> str:
    if name in (None, "", "lead_agent"):
        return "lead_agent"
    if not _IDENTIFIER.fullmatch(name):
        raise TracingInputError("Invalid Agent name")
    return name.lower()


def _provider_payload(provider: ProviderConfig) -> dict:
    result = provider.model_dump(exclude={"api_key", "secret_key"})
    for field in ("api_key", "secret_key"):
        value = getattr(provider, field)
        result[field] = value.get_secret_value() if value is not None else None
    return result


def _public_provider(provider: ProviderConfig) -> dict:
    return {**provider.model_dump(exclude={"api_key", "secret_key"}), "has_api_key": bool(provider.api_key and provider.api_key.get_secret_value()), "has_secret_key": bool(provider.secret_key and provider.secret_key.get_secret_value())}


def _validate_providers(providers: tuple[ProviderConfig, ...]) -> None:
    if not providers or len({item.provider for item in providers}) != len(providers):
        raise TracingInputError("Select one or more distinct tracing providers")
    for item in providers:
        if item.provider in {"arize", "langsmith"} and not (item.api_key and item.api_key.get_secret_value()):
            raise TracingInputError("The selected tracing provider requires an API key")
        if item.provider == "arize" and not (item.project and item.space_id):
            raise TracingInputError("Arize requires project and space ID")
        if item.provider == "langfuse" and not (item.public_key and item.secret_key and item.secret_key.get_secret_value()):
            raise TracingInputError("Langfuse requires public and secret keys")
        if item.provider != "arize" and item.transport != "http":
            raise TracingInputError("This tracing provider requires HTTP transport")


def _inherited_providers() -> tuple[tuple[ProviderConfig, ...], bool]:
    try:
        config = get_tracing_config()
        config.validate_enabled()
        providers = []
        if config.langsmith.is_configured:
            workspace_id = os.environ.get("LANGSMITH_WORKSPACE_ID", "").strip() or os.environ.get("LANGCHAIN_WORKSPACE_ID", "").strip()
            providers.append(ProviderConfig(provider="langsmith", endpoint=config.langsmith.endpoint, project=config.langsmith.project, api_key=config.langsmith.api_key, workspace_id=workspace_id))
        if config.langfuse.is_configured:
            providers.append(ProviderConfig(provider="langfuse", endpoint=config.langfuse.host, public_key=config.langfuse.public_key or "", secret_key=config.langfuse.secret_key))
        return tuple(providers), config.monocle.enabled
    except ValueError:
        raise TracingUnavailableError("Global tracing configuration is incomplete") from None


def _operator_locked() -> bool:
    if not get_tracing_config().monocle.enabled:
        return False
    from deerflow.tracing.scoped import is_global_tracing_guard_installed

    return not is_global_tracing_guard_installed()


def current_monocle_fingerprint() -> str:
    """Fingerprint settings without persisting raw exporter/cloud credentials."""
    config = get_tracing_config().monocle
    prefixes = ("MONOCLE_", "OKAHU_", "AWS_", "AZURE_", "GOOGLE_", "GCP_", "GCLOUD_", "OTEL_")
    settings = {"config": config.model_dump(), "environment": {key: value for key, value in os.environ.items() if key.startswith(prefixes)}, "working_directory": os.getcwd()}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()


def validate_snapshot_environment(snapshot: RunTracingSnapshot) -> None:
    """A frozen snapshot cannot redirect global instrumentation on another worker."""
    if snapshot.monocle_enabled:
        if not get_tracing_config().monocle.enabled or not snapshot.monocle_fingerprint or snapshot.monocle_fingerprint != current_monocle_fingerprint():
            raise TracingUnavailableError("The frozen Monocle exporter configuration differs from this worker")
    elif _operator_locked():
        raise TracingOperatorLockError("This worker cannot suppress global Monocle tracing for the frozen run")


class TracingProfileService:
    def __init__(self, repository: SqlTracingProfileRepository, cipher: CredentialsCipher, *, identity_resolver=None) -> None:
        self.repository = repository
        self.cipher = cipher
        from deerflow.persistence.tracing_profiles.identity import resolve_agent_incarnation

        self.identity_resolver = identity_resolver or resolve_agent_incarnation

    def _state(self, name: str, owner: str) -> tuple[dict, dict | None]:
        try:
            return self.repository.read_live_state(owner, name, self.identity_resolver)
        except FileNotFoundError:
            raise TracingConflictError("The Agent was deleted or replaced; reload its configuration") from None

    def _decode_providers(self, row: dict) -> tuple[ProviderConfig, ...]:
        try:
            return tuple(ProviderConfig.model_validate(item) for item in json.loads(self.cipher.decrypt_text(row["providers_ciphertext"])))
        except (CredentialsDecryptError, ValueError, TypeError):
            raise TracingUnavailableError("Stored tracing credentials are unavailable") from None

    def _can_use(self, profile: dict, user_id: str, is_admin: bool = False) -> bool:
        if is_admin or user_id in profile["allowed_user_ids"]:
            return True
        from deerflow.runtime.user_context import get_current_user

        current = get_current_user()
        if current is not None and str(current.id) == user_id and getattr(current, "system_role", None) == "admin":
            # Explicit auth-disabled development uses a server-created admin
            # identity without a users row. This context is never caller JSON.
            return True
        # Admission runs outside HTTP too (scheduler/IM). Read the shared user
        # authority rather than persisting an administrator bypass in a binding.
        return self.repository.is_admin(user_id)

    def list_profiles(self, user_id: str, *, is_admin: bool) -> list[dict]:
        profiles = self.repository.list_profiles()
        return [self._public_profile(row) for row in profiles if is_admin or user_id in row["allowed_user_ids"]]

    def _public_profile(self, row: dict) -> dict:
        return {"id": row["id"], "name": row["name"], "revision": row["revision"], "providers": [_public_provider(item) for item in self._decode_providers(row)], "allowed_user_ids": row["allowed_user_ids"]}

    def save_profile(self, *, profile_id: str | None = None, name: str, providers: tuple[ProviderConfig, ...], allowed_user_ids: list[str], expected_revision: int) -> dict:
        profile_id = profile_id or uuid4().hex
        if not _IDENTIFIER.fullmatch(profile_id) or not name.strip() or len(name) > 128 or expected_revision < 0:
            raise TracingInputError("Invalid tracing profile")
        previous = self.repository.get_profile(profile_id)
        if (previous is None and expected_revision != 0) or (previous is not None and previous["revision"] != expected_revision):
            raise TracingConflictError("Tracing profile changed; reload before saving")
        previous_providers = {item.provider: item for item in self._decode_providers(previous)} if previous else {}
        merged = []
        for provider in providers:
            old = previous_providers.get(provider.provider)
            # Destination changes must never forward a retained key to a new host.
            if old is not None and (old.endpoint, old.transport, old.public_key) == (provider.endpoint, provider.transport, provider.public_key):
                provider = provider.model_copy(update={key: getattr(old, key) if getattr(provider, key) is None else getattr(provider, key) for key in ("api_key", "secret_key")})
            merged.append(provider)
        providers = tuple(merged)
        _validate_providers(providers)
        ciphertext = self.cipher.encrypt_text(json.dumps([_provider_payload(item) for item in providers]))
        try:
            revision = self.repository.save_profile(profile_id, name=name.strip(), providers_ciphertext=ciphertext, allowed_user_ids=sorted(set(allowed_user_ids)), expected_revision=expected_revision)
        except ProfileRevisionConflict:
            raise TracingConflictError("Tracing profile changed; reload before saving") from None
        return {"id": profile_id, "name": name.strip(), "revision": revision, "providers": [_public_provider(item) for item in providers], "allowed_user_ids": sorted(set(allowed_user_ids))}

    def set_binding(self, agent_name: str | None, user_id: str, *, mode: TracingMode, profile_id: str | None, expected_revision: int, is_admin: bool = False) -> dict:
        agent_name = canonical_agent_name(agent_name)
        state, _ = self._state(agent_name, user_id)
        if mode not in {"inherit", "disabled", "configured"} or expected_revision < 0 or (mode == "configured") != bool(profile_id):
            raise TracingInputError("Configured mode requires a profile; other modes require no profile")
        if mode != "inherit" and _operator_locked():
            raise TracingOperatorLockError("Monocle is enabled globally; per-Agent tracing overrides require an operator to disable it")
        if profile_id:
            profile = self.repository.get_profile(profile_id)
            if profile is None or not self._can_use(profile, user_id, is_admin):
                raise TracingAuthorizationError("Tracing profile is unavailable or not authorized")
            _validate_providers(self._decode_providers(profile))
        try:
            self.repository.save_binding(user_id, agent_name, mode=mode, profile_id=profile_id, expected_revision=expected_revision, agent_incarnation=state["agent_incarnation"], identity_resolver=self.identity_resolver)
        except ProfileRevisionConflict:
            raise TracingConflictError("Agent tracing configuration changed; reload before saving") from None
        return self.get_binding(agent_name, user_id, is_admin=is_admin)

    def _effective(self, binding: dict, profile: dict | None, user_id: str, *, is_admin: bool = False) -> tuple[tuple[ProviderConfig, ...], bool, str]:
        mode = binding["mode"]
        if mode != "inherit" and _operator_locked():
            raise TracingOperatorLockError("Monocle is enabled globally; per-Agent tracing overrides are locked")
        if mode == "inherit":
            providers, monocle = _inherited_providers()
            # Hash the full inherited configuration, including secret rotation,
            # without exposing any secret in the public effective revision.
            identity = json.dumps([[_provider_payload(item) for item in providers], monocle], sort_keys=True)
            return providers, monocle, f"inherit:{hashlib.sha256(identity.encode()).hexdigest()}"
        if mode == "disabled":
            return (), False, f"binding:{binding['revision']}:disabled"
        if profile is None or not self._can_use(profile, user_id, is_admin):
            raise TracingAuthorizationError("Tracing profile is unavailable or not authorized")
        providers = self._decode_providers(profile)
        _validate_providers(providers)
        return providers, False, f"binding:{binding['revision']}:profile:{profile['id']}:{profile['revision']}"

    def get_binding(self, agent_name: str | None, user_id: str, *, is_admin: bool = False) -> dict:
        binding, profile = self._state(canonical_agent_name(agent_name), user_id)
        result = {
            **{key: binding[key] for key in ("mode", "profile_id", "revision")},
            "effective_revision": "",
            "source": "global" if binding["mode"] == "inherit" else (binding["profile_id"] or "disabled"),
            "destinations": [],
            "status": "active",
            "error": None,
            "delivery_verified": False,
            "can_select": True,
        }
        try:
            providers, _, revision = self._effective(binding, profile, user_id, is_admin=is_admin)
            result.update(effective_revision=revision, destinations=[{key: getattr(item, key) for key in ("provider", "endpoint", "project", "space_id", "workspace_id")} for item in providers])
        except TracingControlError as exc:
            result.update(status="degraded", error=exc.code)
        if _operator_locked():
            result.update(can_select=False, error="tracing_operator_lock")
        return result

    def resolve_snapshot(self, agent_name: str | None, user_id: str, *, snapshot_id: str | None = None) -> RunTracingSnapshot:
        agent_name = canonical_agent_name(agent_name)
        if snapshot_id is not None:
            row = self.repository.get_snapshot(snapshot_id)
            if row is None:
                raise TracingUnavailableError("The admitted tracing snapshot is unavailable")
            if row["owner_user_id"] != user_id or row["agent_name"] != agent_name:
                raise TracingAuthorizationError("Tracing snapshot belongs to another execution scope")
            try:
                snapshot = RunTracingSnapshot.model_validate_json(self.cipher.decrypt_text(row["payload_ciphertext"]))
            except (CredentialsDecryptError, ValueError, TypeError):
                raise TracingUnavailableError("The admitted tracing snapshot cannot be decrypted") from None
            if snapshot.snapshot_id != snapshot_id or snapshot.owner_user_id != user_id or snapshot.agent_name != agent_name:
                raise TracingUnavailableError("The admitted tracing snapshot is invalid")
            current, _ = self._state(agent_name, user_id)
            if current["agent_incarnation"] != snapshot.agent_incarnation:
                raise TracingConflictError("The frozen run belongs to a deleted Agent incarnation")
            validate_snapshot_environment(snapshot)
            return snapshot
        binding, profile = self._state(agent_name, user_id)
        providers, monocle, revision = self._effective(binding, profile, user_id)
        snapshot = RunTracingSnapshot(
            snapshot_id=uuid4().hex,
            owner_user_id=user_id,
            agent_name=agent_name,
            mode=binding["mode"],
            revision=revision,
            providers=providers,
            monocle_enabled=monocle,
            monocle_fingerprint=current_monocle_fingerprint() if monocle else "",
            agent_incarnation=binding["agent_incarnation"],
        )
        payload = {**snapshot.model_dump(exclude={"providers"}), "providers": [_provider_payload(item) for item in providers]}
        self.repository.save_snapshot(
            snapshot.snapshot_id,
            user_id,
            agent_name,
            self.cipher.encrypt_text(json.dumps(payload)),
            mode=binding["mode"],
            binding_revision=binding["revision"],
            profile_id=binding["profile_id"],
            profile_revision=profile["revision"] if profile is not None else None,
            agent_incarnation=binding["agent_incarnation"],
        )
        return snapshot


def get_profile_service(*, app_config=None) -> TracingProfileService:
    from deerflow.config.app_config import get_app_config
    from deerflow.persistence.agents.sql import get_sync_sessionmaker
    from deerflow.persistence.tracing_profiles.identity import resolve_agent_incarnation

    try:
        config = app_config if app_config is not None else get_app_config()
        if config.database.backend not in {"sqlite", "postgres"}:
            raise TracingUnavailableError("Tracing profiles require SQLite on one node or shared PostgreSQL across replicas")
        return TracingProfileService(
            SqlTracingProfileRepository(get_sync_sessionmaker(config.database.app_sync_sqlalchemy_url)),
            get_credentials_cipher(),
            identity_resolver=lambda name, owner: resolve_agent_incarnation(name, owner, app_config=config),
        )
    except TracingControlError:
        raise
    except Exception:
        raise TracingUnavailableError("Tracing storage or the deployment credentials key is unavailable") from None


def resolve_run_snapshot(agent_name: str | None, user_id: str, *, snapshot_id: str | None = None, app_config=None) -> RunTracingSnapshot | None:
    from deerflow.config.app_config import get_app_config

    try:
        config = app_config if app_config is not None else get_app_config()
        if config.database.backend == "memory" and snapshot_id is None:
            return None
        return get_profile_service(app_config=config).resolve_snapshot(agent_name, user_id, snapshot_id=snapshot_id)
    except TracingControlError:
        raise
    except Exception:
        raise TracingUnavailableError("Tracing authority is unavailable; the run was not admitted") from None
