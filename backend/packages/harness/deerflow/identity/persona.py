"""PersonaLoader — loads and merges layered persona files for agent personalization.

Persona files are loaded from multiple directory levels (global → dept → user → agent),
with two merge strategies:

  Override files (IDENTITY, SOUL, USER, AGENTS):
    The most specific level's file wins; earlier levels are discarded entirely.

  Append files (BOOTSTRAP, HEARTBEAT, TOOLS, WORKFLOW_AUTO, ERRORS, LESSONS):
    All existing levels are concatenated, separated by "---" dividers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity

# ── File name constants ──────────────────────────────────────────────────────

_OVERRIDE_FILES = ("IDENTITY.md", "SOUL.md", "USER.md", "AGENTS.md")
_APPEND_FILES = (
    "BOOTSTRAP.md",
    "HEARTBEAT.md",
    "TOOLS.md",
    "WORKFLOW_AUTO.md",
    "ERRORS.md",
    "LESSONS.md",
)

_DIVIDER = "\n\n---\n\n"


# ── PersonaContext ────────────────────────────────────────────────────────────


@dataclass
class PersonaContext:
    """Merged persona context ready for injection into the system prompt."""

    # Override fields — single-value, most-specific level wins
    identity: str | None = field(default=None)
    soul: str | None = field(default=None)
    user_context: str | None = field(default=None)
    team_context: str | None = field(default=None)  # from AGENTS.md

    # Append fields — concatenated across levels
    bootstrap: str | None = field(default=None)
    heartbeat: str | None = field(default=None)
    tools_guidance: str | None = field(default=None)
    workflow: str | None = field(default=None)
    error_patterns: str | None = field(default=None)
    lessons: str | None = field(default=None)

    @property
    def is_empty(self) -> bool:
        return all(v is None for v in self.__dict__.values())


# ── PersonaLoader ─────────────────────────────────────────────────────────────


class PersonaLoader:
    """Loads and merges persona files from a layered directory hierarchy."""

    def load(self, identity: "AgentIdentity", base_dir: Path | None = None) -> PersonaContext:
        """Load and merge persona files for the given identity.

        Args:
            identity: Three-tier identity (dept / user / agent).
            base_dir: Override for the DEER_FLOW_HOME base directory (useful in tests).

        Returns:
            Merged PersonaContext.
        """
        from deerflow.config.paths import get_paths

        paths = get_paths()
        if base_dir is not None:
            from deerflow.config.paths import Paths
            paths = Paths(base_dir)

        dirs = paths.identity_persona_dirs(identity)
        return self._merge(dirs)

    def load_global(self, base_dir: Path | None = None) -> PersonaContext:
        """Load only global-level persona files (backward-compat, no identity)."""
        from deerflow.config.paths import get_paths, Paths

        if base_dir is not None:
            paths = Paths(base_dir)
        else:
            paths = get_paths()

        return self._merge([paths.base_dir])

    # ── Internal ──────────────────────────────────────────────────────────────

    def _merge(self, dirs: list[Path]) -> PersonaContext:
        ctx = PersonaContext()

        # Override files: iterate dirs in order; last found wins
        override_map = {
            "IDENTITY.md": "identity",
            "SOUL.md": "soul",
            "USER.md": "user_context",
            "AGENTS.md": "team_context",
        }
        for fname, attr in override_map.items():
            for d in dirs:
                content = _read_file(d / fname)
                if content is not None:
                    setattr(ctx, attr, content)

        # Append files: gather all non-None levels and join
        append_map = {
            "BOOTSTRAP.md": "bootstrap",
            "HEARTBEAT.md": "heartbeat",
            "TOOLS.md": "tools_guidance",
            "WORKFLOW_AUTO.md": "workflow",
            "ERRORS.md": "error_patterns",
            "LESSONS.md": "lessons",
        }
        for fname, attr in append_map.items():
            parts: list[str] = []
            for d in dirs:
                content = _read_file(d / fname)
                if content is not None:
                    parts.append(content)
            if parts:
                setattr(ctx, attr, _DIVIDER.join(parts))

        return ctx


# ── Helpers ───────────────────────────────────────────────────────────────────


def _read_file(path: Path) -> str | None:
    """Read a text file, returning None if it does not exist or is empty."""
    try:
        content = path.read_text(encoding="utf-8").strip()
        return content if content else None
    except FileNotFoundError:
        return None
    except OSError:
        return None
