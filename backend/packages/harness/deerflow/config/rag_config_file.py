"""API-writable RAG functional-model configuration (``rag_config.json``).

The RAG subsystem's roles (embedding / rerank / caption VLM / graph extraction / eval
judge / ASR / MinerU parsing) used to be editable only in the operator's ``config.yaml``
plus environment variables for the secrets (spec 2026-09-10 rag functional-model config
§2).
This module is that block's API-writable counterpart, in the same shape as
:mod:`deerflow.config.models_config`: a *separate* runtime-writable file whose declared
fields override ``config.yaml``'s ``rag:`` block at load time, so the settings UI can
configure the roles without touching the operator-trusted file.

Secrets live here as *values* (``*_api_key`` / ``mineru_api_token``). The read API masks
them behind :data:`MASKED_SECRET`, a submitted sentinel means "keep the stored value",
the file is gitignored, and the support bundle redacts it. Environment variables remain
the fallback, so env-only deployments keep working unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from deerflow.config.models_config import MASKED_API_KEY
from deerflow.config.runtime_paths import existing_project_file, project_root

logger = logging.getLogger(__name__)

#: Sentinel echoed by read endpoints in place of a real secret, and accepted on write
#: to mean "keep the stored value unchanged". Same convention and value as the model
#: keys, so the UI can share one constant.
MASKED_SECRET = MASKED_API_KEY

#: Environment variable backing each secret when ``rag_config.json`` declares none. The
#: ingestion clients import these names as their fallback, so the name the admin API
#: reports as the current source and the name the client actually reads cannot drift.
SECRET_ENV_VARS: dict[str, str] = {
    "embedding_api_key": "DASHSCOPE_EMBEDDING_API_KEY",
    "rerank_api_key": "DASHSCOPE_RERANK_API_KEY",
    "mineru_api_token": "MINERU_API_TOKEN",
}

#: Keys retired by a later contract, with the reason the load warning reports. Their files
#: must keep loading (the module's promise: an existing ``rag_config.json`` keeps working),
#: but the value cannot be carried across — ``parse_backend``'s ``vlm`` / ``hybrid`` have no
#: 4.x equivalent (the backend choice moved to the service's own startup flags, spec
#: 2026-09-24 D2), and the caption endpoint/key now come from the ``models:`` entry the role
#: names (spec 2026-09-23 D10.3/R18). Dropped with a warning rather than silently
#: reinterpreted as another field's meaning.
_RETIRED_KEYS: dict[str, str] = {
    "parse_backend": "the local MinerU leg speaks the 4.x contract now (use parse_tier)",
    "vlm_base_url": "the caption endpoint now comes from the configured model entry",
    "vlm_api_key": "the caption key now comes from the configured model entry",
}

#: The same handling one level down: the nested ``video`` block forbids extras too, and its
#: own caption override retired with the rest (video now follows ``rag.vlm_model``).
_RETIRED_VIDEO_KEYS: dict[str, str] = {
    "caption_model": "the video caption leg follows rag.vlm_model now",
}

#: The fields that name a ``config.yaml`` ``models:`` entry rather than carrying a value.
#: A *blank* declaration in any of them is not a name — it is the absence of one, which is
#: why they share one validator (spec 2026-09-23 default model D2). ``_prune_empty()`` only
#: drops ``None`` / ``""``, so without this the whitespace spelling would be written to the
#: file, reported as ``ui`` by ``sources`` and echoed back by GET.
MODEL_REFERENCE_FIELDS = ("default_model", "extract_model", "judge_model", "vlm_model", "wiki_model", "synthesis_model")


def _blank_to_none(value: Any) -> Any:
    """Whitespace-only strings mean "not declared"; every other value passes through."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _drop_retired_keys(raw: dict[str, Any], keys: dict[str, str], *, path: Path, prefix: str = "") -> None:
    """Strip retired keys in place, warning per key.

    Runs before validation because both models forbid extras: without this a stored file that
    still carries a retired key would fail to load instead of losing just that field. Only the
    key's path is logged — the values here are addresses and keys, so they never enter a log
    line. Nothing is written back: the next legitimate whole-object write is what clears the
    file.
    """
    for key, reason in keys.items():
        if key not in raw:
            continue
        raw.pop(key)
        logger.warning("Dropped retired key %r from %s: %s.", f"{prefix}{key}", path, reason)


class RagVideoFileConfig(BaseModel):
    """The video-ingestion fields the settings UI may override.

    Deliberately narrower than :class:`~deerflow.config.app_config.RagVideoConfig`:
    the master gate / size ceiling / card mode stay operator-only switches in
    ``config.yaml`` (spec §Out of Scope), while the model choices are UI-editable.
    """

    model_config = ConfigDict(extra="forbid")

    asr_provider: Literal["funasr", "whisper", "openai-audio", "dashscope"] | None = Field(default=None, description="ASR backend: an in-process engine (funasr / whisper) or a transcription service (openai-audio / dashscope).")
    asr_model: str | None = Field(default=None, description="ASR model name for the chosen provider.")


class RagConfigFile(BaseModel):
    """The UI-managed RAG functional-model set persisted in ``rag_config.json``.

    Every field is optional: ``None`` (or an absent key) means "not declared here", so
    the value from ``config.yaml`` stands. ``extra="forbid"`` keeps a typo loud instead
    of silently writing a field nothing reads.
    """

    model_config = ConfigDict(extra="forbid")

    qdrant_url: str | None = Field(default=None, description="Qdrant server URL.")
    embedding_model: str | None = Field(default=None, description="DashScope embedding model (dense+sparse).")
    embedding_api_key: str | None = Field(default=None, description="Embedding API key; masked on read, env is the fallback.")
    rerank_model: str | None = Field(default=None, description="DashScope rerank model.")
    rerank_api_key: str | None = Field(default=None, description="Rerank API key; masked on read, env is the fallback.")
    vlm_model: str | None = Field(default=None, description="Name of a config `models:` entry used for captioning; None follows the RAG default, then the first configured model.")
    extract_model: str | None = Field(default=None, description="Name of a config `models:` entry used for graph extraction.")
    judge_model: str | None = Field(default=None, description="Name of a config `models:` entry used as the ragas eval judge; None uses the config primary model.")
    default_model: str | None = Field(default=None, description="Name of a config `models:` entry used by every RAG role that declares none of its own; None uses the first configured model.")
    wiki_model: str | None = Field(default=None, description="Name of a config `models:` entry used to write wiki entries; None uses the first configured model.")
    synthesis_model: str | None = Field(default=None, description="Name of a config `models:` entry used to synthesize eval questions; None uses the first configured model.")
    # Follow-chat thinking toggles (spec 2026-10-03 leg-thinking-follow-chat D1=甲). The
    # three-state rule applies: None means "not declared here" and config.yaml's value stands.
    extract_thinking: bool | None = Field(default=None, description="Graph-extraction leg follows chat's thinking treatment; None uses config.yaml.")
    wiki_thinking: bool | None = Field(default=None, description="Wiki-writing leg follows chat's thinking treatment; None uses config.yaml.")
    judge_thinking: bool | None = Field(default=None, description="Ragas judge leg follows chat's thinking treatment; None uses config.yaml.")
    synthesis_thinking: bool | None = Field(default=None, description="Eval-question synthesis leg follows chat's thinking treatment; None uses config.yaml.")
    vlm_thinking: bool | None = Field(default=None, description="Caption legs follow chat's thinking treatment (output budget rises to at least 4096 while on); None uses config.yaml.")
    mineru_api_token: str | None = Field(default=None, description="MinerU parsing token; masked on read, env is the fallback.")
    # Provider dimension (spec 2026-09-14 rag model provider adaptation §4.1). Ids are
    # validated against `deerflow.knowledge.providers.PROVIDER_ALLOWLIST`; every field is
    # optional, so an existing file that only sets the models keeps loading unchanged.
    embedding_provider: Literal["dashscope", "volcengine-ark", "openai-compatible"] | None = Field(default=None, description="Embedding provider id; None uses config.yaml.")
    embedding_base_url: str | None = Field(default=None, description="Embedding endpoint; None uses the provider's own default.")
    embedding_dimension: int | None = Field(default=None, ge=1, description="Dense dimension override; None means 1024 (the historical width). Changing it rebuilds every collection into a new generation before the switch.")
    embedding_sparse_source: Literal["provider", "external", "bm25"] | None = Field(default=None, description="Where the sparse vectors come from; None uses config.yaml.")
    sparse_provider: Literal["tei-sparse"] | None = Field(default=None, description="Sparse service provider id; used when embedding_sparse_source=external.")
    sparse_base_url: str | None = Field(default=None, description="Sparse service endpoint; used when embedding_sparse_source=external.")
    sparse_model: str | None = Field(default=None, description="Sparse model name; used when embedding_sparse_source=external.")
    sparse_api_key: str | None = Field(default=None, description="Sparse service API key; masked on read, env is the fallback.")
    rerank_provider: Literal["dashscope", "generic-rerank", "tei-rerank"] | None = Field(default=None, description="Rerank provider id; None uses config.yaml.")
    rerank_base_url: str | None = Field(default=None, description="Rerank endpoint; None uses the provider's own default.")
    parse_provider: Literal["mineru-cloud", "mineru-local"] | None = Field(default=None, description="Document-parsing provider; None uses config.yaml.")
    parse_base_url: str | None = Field(default=None, description="Parsing service address; None uses config.yaml (whose empty value means the official MinerU cloud endpoint).")
    parse_tier: Literal["flash", "basic", "standard", "advanced"] | None = Field(default=None, description="Optional tier for the local MinerU 4.x service; None lets the service decide.")
    parse_language: Literal["ch", "ch_server", "en", "japan", "korean", "chinese_cht", "ta", "te", "ka", "el", "th", "latin", "arabic", "cyrillic", "east_slavic", "devanagari"] | None = Field(
        default=None, description="MinerU cloud document language pack; None uses config.yaml."
    )
    parse_model_version: Literal["pipeline", "vlm"] | None = Field(default=None, description="MinerU model version for the cloud leg; None uses config.yaml.")

    asr_base_url: str | None = Field(default=None, description="Transcription service endpoint; the service rows need one, the in-process engines take none.")
    asr_api_key: str | None = Field(default=None, description="Transcription service API key; masked on read, env is the fallback.")
    video: RagVideoFileConfig | None = Field(default=None, description="Video-ingestion model choices.")

    @field_validator(*MODEL_REFERENCE_FIELDS, mode="before")
    @classmethod
    def _blank_model_reference_is_undeclared(cls, value: Any) -> Any:
        """One implementation for all six model-reference fields (spec 2026-09-23 D2).

        Applied *before* ``_prune_empty()`` sees the payload, which is what makes a cleared
        field mean "withdraw the override" instead of "declare an empty name".
        """
        return _blank_to_none(value)

    @classmethod
    def resolve_config_path(cls, config_path: str | None = None) -> Path | None:
        """Resolve the rag config file path.

        Priority: explicit argument, then ``DEER_FLOW_RAG_CONFIG_PATH``, then a
        project-root / legacy search. An explicit argument or set env var is an
        operator assertion, so a missing file there raises ``FileNotFoundError``; the
        fallback search returns ``None`` (the file is optional — most deployments
        configure RAG only in ``config.yaml``).
        """
        if config_path:
            path = Path(config_path)
            if not path.exists():
                raise FileNotFoundError(f"Rag config file specified by param `config_path` not found at {path}")
            return path
        elif env_path := os.getenv("DEER_FLOW_RAG_CONFIG_PATH"):
            path = Path(env_path)
            if not path.exists():
                raise FileNotFoundError(f"Rag config file specified by environment variable `DEER_FLOW_RAG_CONFIG_PATH` not found at {path}")
            return path
        else:
            project_config = existing_project_file(("rag_config.json",))
            if project_config is not None:
                return project_config

            backend_dir = Path(__file__).resolve().parents[4]
            repo_root = backend_dir.parent
            for candidate in (backend_dir / "rag_config.json", repo_root / "rag_config.json"):
                if candidate.exists():
                    return candidate
            return None

    @classmethod
    def from_file(cls, config_path: str | None = None) -> RagConfigFile:
        """Load the UI-managed RAG config.

        Returns an empty config when the file does not exist (optional). Raises a clear
        ``ValueError`` for malformed JSON or an unknown field, so a bad write surfaces
        at load rather than as a silently ignored setting.

        Values are taken literally: unlike the models file there is no ``$ENV``
        resolution, because these fields are secrets the UI stores verbatim (the env
        vars themselves remain the documented fallback).
        """
        resolved_path = cls.resolve_config_path(config_path)
        if resolved_path is None:
            return cls()
        try:
            with open(resolved_path, encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Rag config file at {resolved_path} is not valid JSON: {e}") from e
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise ValueError(f"Rag config file at {resolved_path} must be a JSON object")
        _drop_retired_keys(raw, _RETIRED_KEYS, path=resolved_path)
        video = raw.get("video")
        if isinstance(video, dict):
            _drop_retired_keys(video, _RETIRED_VIDEO_KEYS, path=resolved_path, prefix="video.")
        try:
            return cls.model_validate(raw)
        except Exception as e:
            raise ValueError(f"Rag config file at {resolved_path} is invalid: {e}") from e


def merge_rag_config(yaml_rag: dict | None, ui: RagConfigFile) -> dict:
    """Overlay the UI-managed fields onto ``config.yaml``'s ``rag:`` block.

    Field-level: only what the file declares wins, so an operator's untouched knobs
    survive. The nested ``video`` block merges key by key too — replacing it wholesale
    would silently drop the operator's gates the moment the UI sets one ASR model.
    """
    merged: dict[str, Any] = dict(yaml_rag or {})
    for key, value in ui.model_dump(exclude_none=True).items():
        if key == "video" and isinstance(value, dict):
            merged["video"] = {**(merged.get("video") or {}), **value}
        else:
            merged[key] = value
    return merged


def preserve_secret(submitted: str, stored: str) -> str:
    """Resolve a submitted secret against the stored one, honoring the masking sentinel."""
    return stored if submitted == MASKED_SECRET else submitted


def configured_rag_secret(field: str) -> str | None:
    """Read one secret field from the merged config, or ``None`` when unset.

    Goes through ``get_app_config()`` so a hot-reloaded ``rag_config.json`` applies on
    the next call. A config that cannot be resolved degrades to ``None`` instead of
    raising: this is the *credential* path, and failing here would break env-only
    callers in environments that have no config file at all (the documented fallback is
    the environment).
    """
    try:
        from deerflow.config.app_config import get_app_config

        rag = get_app_config().rag
    except Exception:
        logger.debug("RAG config unavailable while resolving %s; falling back to the environment", field, exc_info=True)
        return None
    value = getattr(rag, field, None)
    return value or None


def _fsync_directory_best_effort(directory: Path) -> None:
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        logger.debug("Could not fsync rag config directory: %s", directory, exc_info=True)
    finally:
        try:
            os.close(directory_fd)
        except OSError:
            logger.debug("Could not close rag config directory fd: %s", directory, exc_info=True)


def write_rag_config(data: dict[str, Any]) -> Path:
    """Replace the API-writable RAG config file, atomically and under the module's lock.

    Two writers share this one policy (spec 2026-09-26 D5-7): the settings save, and the
    dimension migration's switch — the latter lands *after* the new vector generation is
    complete, which is what makes "the switch is one atomic file replace" true.
    """
    target_path = RagConfigFile.resolve_config_path() or (project_root() / "rag_config.json")
    with rag_config_write_lock:
        atomic_write_rag_config(target_path, data)
    return target_path


def atomic_write_rag_config(path: Path, data: dict[str, Any]) -> None:
    """Write the rag config without exposing a truncated or partial file.

    Mirrors ``atomic_write_models_config`` (temp file in the target directory, fsync,
    ``os.replace``, best-effort directory fsync, temp cleanup on failure) — plus the
    bounded replace retry (spec 2026-10-05 ③), which the models twin does not have yet.
    """
    path = Path(path)
    target_path = path.resolve(strict=False) if path.is_symlink() else path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    existing_mode: int | None = None
    try:
        existing_mode = stat.S_IMODE(target_path.stat().st_mode)
    except FileNotFoundError:
        pass

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, indent=2)
            if existing_mode is not None:
                temporary_path.chmod(existing_mode)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        _replace_with_retry(temporary_path, target_path)
        _fsync_directory_best_effort(target_path.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not remove temporary rag config file: %s", temporary_path, exc_info=True)


#: Bounded retries for the replace step only (spec 2026-10-05 ③). A Python reader — the
#: config load or the hot-reload signature check — holds the target open without
#: ``FILE_SHARE_DELETE``, so Windows answers the replace with EACCES for the length of
#: that read: transient by construction, but unbounded retry would turn a reader that
#: never closes into a hung writer.
_REPLACE_RETRIES = 3
_REPLACE_RETRY_SLEEP = 0.05


def _replace_with_retry(temporary_path: Path, target_path: Path) -> None:
    for attempt in range(_REPLACE_RETRIES + 1):
        try:
            os.replace(temporary_path, target_path)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES:
                raise
            logger.info("rag config replace collided with a reader (attempt %d/%d); retrying", attempt + 1, _REPLACE_RETRIES)
            time.sleep(_REPLACE_RETRY_SLEEP)


#: Serializes read-modify-write cycles on ``rag_config.json`` across writers (the rag
#: config management API). Same rationale as ``models_config_write_lock``: a
#: ``threading.Lock`` owned inside the worker performing the RMW, so it stays held
#: across the write and reload and has no event-loop affinity.
rag_config_write_lock = threading.Lock()
