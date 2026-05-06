"""Abstract SkillStorage base class with template-method flows."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from deerflow.skills.types import SKILL_MD_FILE, Skill, SkillCategory  # noqa: F401

logger = logging.getLogger(__name__)

_SKILL_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class SkillStorage(ABC):
    """Abstract base for skill storage backends.

    Subclasses implement a small set of storage-medium-specific atomic
    operations; this base class provides final template-method flows
    (load_skills, history serialisation, path helpers, validation) that
    compose them with protocol-level helpers.
    """

    def __init__(self, container_path: str = "/mnt/skills") -> None:
        self._container_root = container_path

    # ------------------------------------------------------------------
    # Static protocol helpers (not storage-specific)
    # ------------------------------------------------------------------

    @staticmethod
    def validate_skill_name(name: str) -> str:
        """Validate and normalise a skill name; return the normalised form."""
        normalized = name.strip()
        if not _SKILL_NAME_PATTERN.fullmatch(normalized):
            raise ValueError("Skill name must be hyphen-case using lowercase letters, digits, and hyphens only.")
        if len(normalized) > 64:
            raise ValueError("Skill name must be 64 characters or fewer.")
        return normalized

    @staticmethod
    def validate_relative_path(relative_path: str, base_dir: Path) -> Path:
        """Validate *relative_path* against *base_dir* and return the resolved target.

        Checks that *relative_path* is non-empty, then joins it with *base_dir*
        and resolves the result (following symlinks).  Raises ``ValueError`` if
        the resolved target does not lie within *base_dir*.
        """
        if not relative_path:
            raise ValueError("relative_path must not be empty.")
        resolved_base = base_dir.resolve()
        target = (resolved_base / relative_path).resolve()
        try:
            target.relative_to(resolved_base)
        except ValueError as exc:
            raise ValueError("relative_path must resolve within the skill directory.") from exc
        return target

    @staticmethod
    def validate_skill_markdown_content(name: str, content: str) -> None:
        """Validate SKILL.md content: parse frontmatter and check name matches."""
        import tempfile

        from deerflow.skills.validation import _validate_skill_frontmatter

        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_skill_dir = Path(tmp_dir) / SkillStorage.validate_skill_name(name)
            temp_skill_dir.mkdir(parents=True, exist_ok=True)
            (temp_skill_dir / SKILL_MD_FILE).write_text(content, encoding="utf-8")
            is_valid, message, parsed_name = _validate_skill_frontmatter(temp_skill_dir)
            if not is_valid:
                raise ValueError(message)
            if parsed_name != name:
                raise ValueError(f"Frontmatter name '{parsed_name}' must match requested skill name '{name}'.")

    def ensure_safe_support_path(self, name: str, relative_path: str) -> Path:
        """Validate and return the resolved absolute path for a support file."""
        _ALLOWED_SUPPORT_SUBDIRS = {"references", "templates", "scripts", "assets"}
        skill_dir = self.get_custom_skill_dir(self.validate_skill_name(name)).resolve()
        if not relative_path or relative_path.endswith("/"):
            raise ValueError("Supporting file path must include a filename.")
        relative = Path(relative_path)
        if relative.is_absolute():
            raise ValueError("Supporting file path must be relative.")
        if any(part in {"..", ""} for part in relative.parts):
            raise ValueError("Supporting file path must not contain parent-directory traversal.")
        top_level = relative.parts[0] if relative.parts else ""
        if top_level not in _ALLOWED_SUPPORT_SUBDIRS:
            raise ValueError(f"Supporting files must live under one of: {', '.join(sorted(_ALLOWED_SUPPORT_SUBDIRS))}.")
        target = (skill_dir / relative).resolve()
        allowed_root = (skill_dir / top_level).resolve()
        try:
            target.relative_to(allowed_root)
        except ValueError as exc:
            raise ValueError("Supporting file path must stay within the selected support directory.") from exc
        return target

    # ------------------------------------------------------------------
    # Abstract atomic operations (storage-medium specific)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_skills_root_path(self) -> Path:
        """Absolute host path to the skills root, used for sandbox mounts.

        Origin: ``deerflow.skills.loader.get_skills_root_path``.
        """

    @abstractmethod
    def _iter_skill_files(self) -> Iterable[tuple[SkillCategory, Path, Path]]:
        """Yield ``(category, category_root, skill_md_path)`` for every SKILL.md.

        Origin: extracted from directory-walk logic inside
        ``deerflow.skills.loader.load_skills``.
        """

    @abstractmethod
    def read_custom_skill(self, name: str) -> str:
        """Read SKILL.md content for a custom skill.

        Origin: ``deerflow.skills.manager.read_custom_skill_content``.
        """

    @abstractmethod
    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        """Atomically write a text file under ``custom/<name>/<relative_path>``.

        Origin: ``deerflow.skills.manager.atomic_write``.
        """

    @abstractmethod
    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        """Async install of a skill from a ``.skill`` ZIP archive.

        Origin: ``deerflow.skills.installer.ainstall_skill_from_archive``.
        """

    def install_skill_from_archive(self, archive_path: str | Path) -> dict:
        """Sync wrapper — delegates to :meth:`ainstall_skill_from_archive`."""
        from deerflow.skills.installer import _run_async_install

        return _run_async_install(self.ainstall_skill_from_archive(archive_path))

    @abstractmethod
    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        """Delete a custom skill (validation + optional history + directory removal).

        Origin: ``app.gateway.routers.skills.delete_custom_skill`` + ``skill_manage_tool``.
        """

    @abstractmethod
    def custom_skill_exists(self, name: str) -> bool:
        """Origin: ``deerflow.skills.manager.custom_skill_exists``."""

    @abstractmethod
    def public_skill_exists(self, name: str) -> bool:
        """Origin: ``deerflow.skills.manager.public_skill_exists``."""

    @abstractmethod
    def append_history(self, name: str, record: dict) -> None:
        """Append a JSONL history entry for ``name``.

        Origin: ``deerflow.skills.manager.append_history``.
        """

    @abstractmethod
    def read_history(self, name: str) -> list[dict]:
        """Return all history records for ``name``, oldest first.

        Origin: ``deerflow.skills.manager.read_history``.
        """

    # ------------------------------------------------------------------
    # Concrete path helpers (layout is part of the SKILL.md protocol)
    # ------------------------------------------------------------------

    def get_container_root(self) -> str:
        """Origin: ``deerflow.config.skills_config.SkillsConfig.container_path`` accessor."""
        return self._container_root

    def get_custom_skill_dir(self, name: str) -> Path:
        """Path to ``custom/<name>``. Does not create the directory.

        Origin: ``deerflow.skills.manager.get_custom_skill_dir``.
        """
        normalized_name = self.validate_skill_name(name)
        return self.get_skills_root_path() / SkillCategory.CUSTOM.value / normalized_name

    def get_custom_skill_file(self, name: str) -> Path:
        """Path to ``custom/<name>/SKILL.md``.

        Origin: ``deerflow.skills.manager.get_custom_skill_file``.
        """
        normalized_name = self.validate_skill_name(name)
        return self.get_custom_skill_dir(normalized_name) / SKILL_MD_FILE

    def get_skill_history_file(self, name: str) -> Path:
        """Path to ``custom/.history/<name>.jsonl``. Does not create parents.

        Origin: ``deerflow.skills.manager.get_skill_history_file``.
        """
        normalized_name = self.validate_skill_name(name)
        return self.get_skills_root_path() / SkillCategory.CUSTOM.value / ".history" / f"{normalized_name}.jsonl"

    # ------------------------------------------------------------------
    # Final template-method flows
    # ------------------------------------------------------------------

    def load_skills(self, *, enabled_only: bool = False) -> list[Skill]:
        """Discover all skills, merge enabled state, sort and optionally filter.

        Origin: ``deerflow.skills.loader.load_skills``.
        """
        from deerflow.skills.parser import parse_skill_file

        skills_by_name: dict[str, Skill] = {}
        for category, category_root, md_path in self._iter_skill_files():
            skill = parse_skill_file(
                md_path,
                category=category,
                relative_path=md_path.parent.relative_to(category_root),
            )
            if skill:
                skills_by_name[skill.name] = skill

        skills = list(skills_by_name.values())

        # Merge enabled state from extensions config (re-read every call so
        # changes made by another process are picked up immediately).
        try:
            from deerflow.config.extensions_config import ExtensionsConfig

            extensions_config = ExtensionsConfig.from_file()
            for skill in skills:
                skill.enabled = extensions_config.is_skill_enabled(skill.name, skill.category)
        except Exception as e:
            logger.warning("Failed to load extensions config: %s", e)

        if enabled_only:
            skills = [s for s in skills if s.enabled]

        skills.sort(key=lambda s: s.name)
        return skills

    def ensure_custom_skill_is_editable(self, name: str) -> None:
        """Origin: ``deerflow.skills.manager.ensure_custom_skill_is_editable``."""
        if self.custom_skill_exists(name):
            return
        if self.public_skill_exists(name):
            raise ValueError(f"'{name}' is a built-in skill. To customise it, create a new skill with the same name under skills/custom/.")
        raise FileNotFoundError(f"Custom skill '{name}' not found.")
