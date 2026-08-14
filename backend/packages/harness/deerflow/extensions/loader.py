"""Config-driven extension loading.

Entry points are named as `module.path:install`, resolved through the same
`resolve_variable` helper the guardrails provider already uses. Load order is
the config list order — explicit and reproducible, which matters because the
middleware stack is position-sensitive.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from deerflow_extension_api import API_VERSION
from pydantic import BaseModel, ConfigDict, Field

from deerflow.extensions.registry import ExtensionRegistry, LoadedExtensions
from deerflow.reflection import resolve_variable

logger = logging.getLogger(__name__)

DiagnosticLevel = Literal["debug", "info", "warning", "error"]


class ExtensionSpec(BaseModel):
    """One entry of the `plugins:` list in config.yaml."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        default=True,
        description="When false, skip the extension without resolving or importing it",
    )
    name: str | None = Field(
        default=None,
        description="Stable operator-facing name recorded by the extension manager",
    )
    package: str | None = Field(
        default=None,
        description="Installed Python distribution recorded by the extension manager",
    )
    use: str = Field(description="Entry point path, e.g. 'my_extension:install'")
    config: dict[str, Any] = Field(
        default_factory=dict,
        description="Extension-private configuration, passed to install() verbatim",
    )
    required: bool = Field(
        default=False,
        description="When true, a load failure aborts startup instead of being skipped",
    )


@dataclass(frozen=True)
class Diagnostic:
    """A load- or run-time problem attributed to a specific extension.

    The repository has no structured diagnostics channel today; this is a
    deliberately minimal one whose only job is keeping failures attributable.
    """

    level: DiagnosticLevel
    source: str
    message: str

    @classmethod
    def error(cls, source: str, message: str) -> Diagnostic:
        return cls("error", source, message)

    @classmethod
    def warning(cls, source: str, message: str) -> Diagnostic:
        return cls("warning", source, message)

    @classmethod
    def info(cls, source: str, message: str) -> Diagnostic:
        return cls("info", source, message)

    @classmethod
    def debug(cls, source: str, message: str) -> Diagnostic:
        return cls("debug", source, message)


class ExtensionLoadError(RuntimeError):
    """Raised when an extension marked `required: true` fails to load."""


def _parse_version(version: object) -> tuple[int, ...] | None:
    if not isinstance(version, str):
        return None
    try:
        return tuple(int(part) for part in str.split(version, "."))
    except ValueError:
        return None


def _compatible(declared: str, current: str) -> bool:
    """One-directional, with the semver window for the contract's life stage.

    Pre-1.0 minors may break, so the window is same major.minor with patches
    additive: host >= declared.
    From 1.0 on contracts only grow within a major, so a newer host stays
    compatible with older extensions while an extension written against a
    newer minor is refused — it would reach for contract additions the host
    does not implement. Unparseable versions are refused, not waved through."""
    declared_parts = _parse_version(declared)
    current_parts = _parse_version(current)
    if not declared_parts or not current_parts:
        return False
    width = max(len(declared_parts), len(current_parts), 2)
    declared_padded = declared_parts + (0,) * (width - len(declared_parts))
    current_padded = current_parts + (0,) * (width - len(current_parts))
    if declared_padded[0] != current_padded[0]:
        return False
    if declared_padded[0] == 0 and declared_padded[1] != current_padded[1]:
        return False
    return current_padded >= declared_padded


def _range_for(declared: str) -> str:
    """The pip window matching ``_compatible``'s rules, for the actionable
    refusal message. Falls back to an exact request when the declared version
    is unparseable — the message must survive the version that caused it."""
    parts = _parse_version(declared)
    if not parts:
        return f"=={declared}"
    if parts[0] == 0:
        minor = parts[1] if len(parts) > 1 else 0
        return f">={declared},<0.{minor + 1}"
    return f">={declared},<{parts[0] + 1}.0"


def load_extensions(specs: Sequence[ExtensionSpec]) -> tuple[LoadedExtensions, list[Diagnostic]]:
    """Resolve and install every configured extension.

    Fail-open by default: a broken extension is skipped with a diagnostic so
    the Gateway still starts. `required: true` flips that to fail-closed for
    extensions whose absence changes behaviour rather than just observability.
    """
    registry = ExtensionRegistry()
    diagnostics: list[Diagnostic] = []
    loaded_sources: list[str] = []

    for spec in specs:
        if not spec.enabled:
            continue

        try:
            install = resolve_variable(spec.use)
        except Exception as exc:
            message = f"could not resolve extension entry point: {exc}"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.error("Extension %s: %s", spec.use, message)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} failed to load") from exc
            continue

        if not callable(install):
            message = f"extension entry point is not callable: {type(install).__name__}"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.error("Extension %s: %s", spec.use, message)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} is not callable")
            continue

        try:
            declared = getattr(install, "__deerflow_api__", None)
        except Exception as exc:
            message = f"could not inspect extension-api version marker: {type(exc).__name__}"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.error("Extension %s: %s", spec.use, message)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} could not inspect api marker") from exc
            continue
        if declared is not None and _parse_version(declared) is None:
            message = f"extension declares invalid extension-api version marker of type {type(declared).__name__}; expected a dotted numeric string such as '0.1'"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.error("Extension %s: %s", spec.use, message)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} declares invalid api marker")
            continue
        if declared is not None:
            # ``isinstance(..., str)`` also accepts subclasses whose
            # ``__str__``/``__format__`` methods can execute plugin code while
            # we build an incompatibility diagnostic. Normalize with the base
            # implementation before compatibility checks and rendering.
            declared = str.__str__(declared)
        if declared is not None and not _compatible(declared, API_VERSION):
            message = f"extension requires extension-api {declared}, host provides {API_VERSION}. Install a matching version: pip install 'deerflow-extension-api{_range_for(declared)}'"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.error("Extension %s: %s", spec.use, message)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} declares incompatible api {declared}")
            continue

        # Positional rollback, not registry.discard(spec.use): two specs may
        # legitimately share the same `use` with different config, and
        # discard-by-source would also erase an earlier, successfully
        # installed instance that happens to share this spec's `use`.
        mark = registry.mark()
        try:
            with registry.attributed_to(spec.use):
                install(registry, _frozen_config(spec.config))
        except Exception as exc:
            registry.rollback_to(mark)
            message = f"install() failed: {exc}"
            diagnostics.append(Diagnostic.error(spec.use, message))
            logger.exception("Extension %s: install() failed", spec.use)
            if spec.required:
                raise ExtensionLoadError(f"required extension {spec.use} failed to install") from exc
            continue

        loaded_sources.append(spec.use)

    # Loading third-party code is exactly the event an operator needs positive
    # confirmation of, and every other branch here is failure-only — so without
    # this line a fully successful load is indistinguishable from a `plugins:`
    # block the host never read. The x/y count names the difference between
    # "all loaded" and "some were skipped" without repeating the per-failure
    # errors already logged above.
    if specs:
        logger.info("Extensions loaded: %d/%d (%s)", len(loaded_sources), len(specs), ", ".join(loaded_sources) or "none")
    else:
        # Debug, not info: no configured plugins is the default state for almost
        # every deployment, and an unconditional line would be pure boot noise.
        logger.debug("No extensions configured")

    return registry.build(), diagnostics


def _frozen_config(config: dict[str, Any]) -> Mapping[str, Any]:
    """Hand extensions a shallow copy of their config block.

    This is a shallow copy: it stops an extension from reassigning
    top-level keys on another extension's (or the caller's) config dict, but
    nested structures (lists, dicts) are still shared by reference and can be
    mutated in place. Use plain, top-level config values if this guarantee
    matters to you.
    """
    return dict(config)
