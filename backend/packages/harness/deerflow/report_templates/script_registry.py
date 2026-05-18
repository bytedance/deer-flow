"""Script Registry — discovers report scripts contributed by enabled skills.

Implements §9 of the design. Each skill may optionally provide a
``report_scripts.yaml`` at its root declaring scripts the platform can execute
from a DSL template. Scripts are namespaced ``<skill_name>/<script_name>``.

This module purposely does **not** execute scripts; it only inventories them
and exposes structured descriptors that the DSL validator and (Phase 4)
data-runner consume.

Public API:
    load_registry(force: bool = False) -> ScriptRegistry
    get_registry() -> ScriptRegistry        # cached
    reset_registry() -> None                # cache invalidation (tests, skill toggles)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

REPORT_SCRIPTS_FILE = "report_scripts.yaml"
REGISTRY_SCHEMA_VERSION = "1"

ScriptKind = Literal["form_options", "data_step", "transform", "export"]


# ---------------------------------------------------------------------------
# Pydantic schema for ``report_scripts.yaml``
# ---------------------------------------------------------------------------


class ArgSpec(BaseModel):
    """One argument descriptor inside a script's ``args_schema``."""

    model_config = ConfigDict(extra="allow")

    type: str
    required: bool = False
    default: Any | None = None
    values: list[Any] | None = None
    min: float | None = None
    max: float | None = None
    items: dict[str, Any] | None = None
    max_items: int | None = None
    max_length: int | None = None
    pattern: str | None = None


class OutputFile(BaseModel):
    """A declared output file for the script."""

    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    description: str = ""


class ScriptDescriptorYaml(BaseModel):
    """Schema for a single script entry inside ``report_scripts.yaml``."""

    model_config = ConfigDict(extra="forbid")

    entry: str
    kind: list[ScriptKind] = Field(min_length=1)
    description: str = ""
    args_schema: dict[str, ArgSpec] = Field(default_factory=dict)
    args_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    outputs_schema: dict[str, Any] | None = None
    output_files: list[OutputFile] = Field(default_factory=list)
    timeout_seconds: int = Field(default=60, gt=0, le=3600)
    max_output_bytes: int = Field(default=10 * 1024 * 1024, gt=0)


class ReportScriptsYaml(BaseModel):
    """Schema for ``<skill>/report_scripts.yaml``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    scripts: dict[str, ScriptDescriptorYaml]


# ---------------------------------------------------------------------------
# Runtime descriptor — what callers actually see
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScriptDescriptor:
    """Fully-namespaced runtime view of a registered report script."""

    qualified_name: str  # "skill_name/script_name"
    skill_name: str
    script_name: str
    skill_dir: Path
    entry: str
    kinds: tuple[ScriptKind, ...]
    description: str
    args_schema: dict[str, ArgSpec]
    args_aliases: dict[str, dict[str, str]]
    outputs_schema: dict[str, Any] | None
    output_files: tuple[OutputFile, ...]
    timeout_seconds: int
    max_output_bytes: int

    @property
    def entry_path(self) -> Path:
        """Resolve the entry file path relative to the skill directory."""
        return (self.skill_dir / self.entry).resolve()


@dataclass(frozen=True)
class ScriptRegistry:
    """Snapshot of all loaded scripts, keyed by qualified name."""

    scripts: dict[str, ScriptDescriptor] = field(default_factory=dict)

    def get(self, qualified_name: str) -> ScriptDescriptor | None:
        return self.scripts.get(qualified_name)

    def require(self, qualified_name: str) -> ScriptDescriptor:
        desc = self.scripts.get(qualified_name)
        if desc is None:
            raise UnknownScriptError(qualified_name, available=list(self.scripts.keys()))
        return desc

    def list_by_skill(self, skill_name: str) -> list[ScriptDescriptor]:
        return [d for d in self.scripts.values() if d.skill_name == skill_name]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RegistryError(Exception):
    """Base class for registry-related errors."""


class RegistryLoadError(RegistryError):
    """Raised when a skill's ``report_scripts.yaml`` is malformed."""

    def __init__(self, skill_name: str, message: str) -> None:
        self.skill_name = skill_name
        super().__init__(f"skill {skill_name!r}: {message}")


class RegistryConflictError(RegistryError):
    """Raised when two skills declare the same qualified script name."""

    def __init__(self, qualified_name: str, first: str, second: str) -> None:
        self.qualified_name = qualified_name
        super().__init__(
            f"duplicate script {qualified_name!r}: first declared by {first!r}, also in {second!r}"
        )


class UnknownScriptError(RegistryError):
    """Raised by ``ScriptRegistry.require`` when a name is not registered."""

    def __init__(self, qualified_name: str, *, available: list[str]) -> None:
        self.qualified_name = qualified_name
        self.available = available
        super().__init__(f"unknown script {qualified_name!r}; registered: {sorted(available)}")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_registry(*, enabled_only: bool = True) -> ScriptRegistry:
    """Walk all skills and build a fresh ScriptRegistry snapshot.

    Args:
        enabled_only: When True (default), only enabled skills contribute scripts.
            Tests can pass ``enabled_only=False`` to include everything.

    Raises:
        RegistryLoadError: A ``report_scripts.yaml`` failed validation.
        RegistryConflictError: Two skills declared the same qualified name.
    """
    return _build_registry_from_skills(_discover_skills(enabled_only=enabled_only))


def _discover_skills(*, enabled_only: bool) -> list[tuple[str, Path, bool]]:
    """Return ``[(skill_name, skill_dir, enabled), ...]``. Isolated for testability."""
    try:
        from deerflow.skills.storage import get_or_new_skill_storage
    except Exception as e:  # noqa: BLE001
        logger.warning("skill storage unavailable: %s", e)
        return []

    storage = get_or_new_skill_storage()
    skills = storage.load_skills(enabled_only=enabled_only)
    return [(s.name, s.skill_dir, s.enabled) for s in skills]


def _build_registry_from_skills(
    skills: list[tuple[str, Path, bool]],
) -> ScriptRegistry:
    descriptors: dict[str, ScriptDescriptor] = {}
    owner_of: dict[str, str] = {}

    for skill_name, skill_dir, _enabled in skills:
        manifest_path = skill_dir / REPORT_SCRIPTS_FILE
        if not manifest_path.exists():
            continue

        try:
            raw_text = manifest_path.read_text(encoding="utf-8")
            raw_data = yaml.safe_load(raw_text) or {}
        except (OSError, yaml.YAMLError) as e:
            _emit_skill_unavailable(skill_name, "registry_load_failed")
            raise RegistryLoadError(skill_name, f"cannot read {REPORT_SCRIPTS_FILE}: {e}") from e

        try:
            manifest = ReportScriptsYaml.model_validate(raw_data)
        except ValidationError as e:
            _emit_skill_unavailable(skill_name, "registry_load_failed")
            raise RegistryLoadError(
                skill_name, f"invalid {REPORT_SCRIPTS_FILE}: {e}"
            ) from e

        if manifest.schema_version != REGISTRY_SCHEMA_VERSION:
            _emit_skill_unavailable(skill_name, "registry_load_failed")
            raise RegistryLoadError(
                skill_name,
                f"unsupported schema_version {manifest.schema_version!r}; expected {REGISTRY_SCHEMA_VERSION!r}",
            )

        for script_name, spec in manifest.scripts.items():
            qualified = f"{skill_name}/{script_name}"
            if qualified in owner_of:
                raise RegistryConflictError(qualified, owner_of[qualified], skill_name)
            owner_of[qualified] = skill_name

            descriptors[qualified] = ScriptDescriptor(
                qualified_name=qualified,
                skill_name=skill_name,
                script_name=script_name,
                skill_dir=skill_dir,
                entry=spec.entry,
                kinds=tuple(spec.kind),
                description=spec.description,
                args_schema=dict(spec.args_schema),
                args_aliases={k: dict(v) for k, v in spec.args_aliases.items()},
                outputs_schema=spec.outputs_schema,
                output_files=tuple(spec.output_files),
                timeout_seconds=spec.timeout_seconds,
                max_output_bytes=spec.max_output_bytes,
            )

    return ScriptRegistry(scripts=descriptors)


# ---------------------------------------------------------------------------
# Cached accessor
# ---------------------------------------------------------------------------

_cache_lock = threading.Lock()
_cached_registry: ScriptRegistry | None = None


def get_registry() -> ScriptRegistry:
    """Return the cached registry, building it on first call."""
    global _cached_registry
    with _cache_lock:
        if _cached_registry is None:
            _cached_registry = load_registry()
    return _cached_registry


def reset_registry() -> None:
    """Drop the cached registry — call after skill enable/disable or in tests."""
    global _cached_registry
    with _cache_lock:
        _cached_registry = None


def _emit_skill_unavailable(skill_name: str, action: str) -> None:
    """Fire a Phase 7 ``skill_unavailable`` event. Never raises."""
    try:
        from deerflow.report_templates.telemetry import get_telemetry

        get_telemetry().record_skill_unavailable(skill_name=skill_name, action=action)
    except Exception:  # noqa: BLE001
        logger.debug("skill_unavailable telemetry failed", exc_info=True)
