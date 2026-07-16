"""Local-filesystem implementation of ``SkillStorage``."""

from __future__ import annotations

import asyncio
import errno
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from deerflow.config.runtime_paths import resolve_path
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.skills.permissions import make_skill_written_path_sandbox_readable
from deerflow.skills.storage.skill_storage import SKILL_MD_FILE, SkillStorage
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)

# Bound for the best-effort temp-dir cleanup so a stalled filesystem (e.g. NFS)
# cannot hold back the install outcome propagating out of the finally block.
_INSTALL_TMP_CLEANUP_TIMEOUT_SECONDS = 5.0


class LocalSkillStorage(SkillStorage):
    """Skill storage backed by the local filesystem.

    Layout::

        <root>/public/<name>/SKILL.md
        <root>/custom/<name>/SKILL.md
        <root>/custom/.history/<name>.jsonl
    """

    def __init__(
        self,
        host_path: str | None = None,
        container_path: str = DEFAULT_SKILLS_CONTAINER_PATH,
        app_config=None,
    ) -> None:
        super().__init__(container_path=container_path)
        if host_path is None:
            from deerflow.config import get_app_config

            config = app_config or get_app_config()
            self._app_config = config
            self._host_root: Path = config.skills.get_skills_path()
        else:
            # Keep app_config as-is (may be None). This host_path constructor is used by
            # tests and non-user-scoped storage; eagerly calling get_app_config() here would
            # break config-free environments (e.g. CI). The skill_scan.enabled kill switch is
            # resolved lazily at scan time by skill_scan_enabled(), which also picks up
            # hot-reloaded config, so a None here is honored, not ignored.
            self._app_config = app_config
            self._host_root = resolve_path(host_path)

    # ------------------------------------------------------------------
    # Abstract operation implementations
    # ------------------------------------------------------------------

    def get_skills_root_path(self) -> Path:
        return self._host_root

    def custom_skill_exists(self, name: str) -> bool:
        return self.get_custom_skill_file(name).exists()

    def public_skill_exists(self, name: str) -> bool:
        normalized_name = self.validate_skill_name(name)
        return (self._host_root / SkillCategory.PUBLIC.value / normalized_name / SKILL_MD_FILE).exists()

    def _iter_skill_files(self) -> Iterable[tuple[SkillCategory, Path, Path]]:
        if not self._host_root.exists():
            return
        for category in SkillCategory:
            category_path = self._host_root / category.value
            if not category_path.exists() or not category_path.is_dir():
                continue
            for current_root, dir_names, file_names in os.walk(category_path, followlinks=True):
                dir_names[:] = sorted(name for name in dir_names if not name.startswith("."))
                if SKILL_MD_FILE not in file_names:
                    continue
                # A directory containing SKILL.md is a package boundary. Any
                # nested SKILL.md files belong to that package's supporting
                # resources (for example eval fixtures), not to the runtime
                # skill registry. Namespace directories without SKILL.md still
                # recurse, preserving layouts such as public/team/helper.
                dir_names.clear()
                yield category, category_path, Path(current_root) / SKILL_MD_FILE

    def read_custom_skill(self, name: str) -> str:
        if not self.custom_skill_exists(name):
            raise FileNotFoundError(f"Custom skill '{name}' not found.")
        return (self.get_custom_skill_dir(name) / SKILL_MD_FILE).read_text(encoding="utf-8")

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        target = self.validate_relative_path(relative_path, self.get_custom_skill_dir(name))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            dir=str(target.parent),
        ) as tmp_file:
            tmp_file.write(content)
            tmp_path = Path(tmp_file.name)
        tmp_path.replace(target)
        make_skill_written_path_sandbox_readable(self.get_custom_skill_dir(name), target)

    async def ainstall_skill_from_archive(self, archive_path: str | Path) -> dict:
        from deerflow.skills.installer import _scan_skill_archive_contents_or_raise

        logger.info("Installing skill from %s", archive_path)
        path = Path(archive_path)
        custom_dir = self._host_root / "custom"

        # The per-file security scan is an async LLM call and must stay on the
        # event loop; every filesystem phase around it runs in a worker thread.
        tmp = await asyncio.to_thread(tempfile.mkdtemp)
        try:
            skill_dir, skill_name, target = await asyncio.to_thread(self._prepare_skill_archive, path, Path(tmp), custom_dir, archive_path)

            await _scan_skill_archive_contents_or_raise(skill_dir, skill_name, app_config=self._app_config)

            await asyncio.to_thread(self._commit_skill_install, skill_dir, skill_name, custom_dir, target)
            logger.info("Skill %r installed to %s", skill_name, target)
        finally:
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(self._cleanup_install_tmp, tmp),
                    timeout=_INSTALL_TMP_CLEANUP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning("Timed out cleaning up skill install temp dir %s", tmp)

        return {
            "success": True,
            "skill_name": skill_name,
            "message": f"Skill '{skill_name}' installed successfully",
        }

    @staticmethod
    def _cleanup_install_tmp(tmp: str) -> None:
        """Best-effort removal that never masks the install outcome, but leaves a trace."""
        try:
            shutil.rmtree(tmp)
        except OSError:
            logger.warning("Failed to clean up skill install temp dir %s", tmp, exc_info=True)

    def _prepare_skill_archive(self, path: Path, tmp_path: Path, custom_dir: Path, archive_path: str | Path) -> tuple[Path, str, Path]:
        """Extract and validate the archive (blocking; runs off the event loop)."""
        import zipfile

        from deerflow.skills.installer import (
            SkillAlreadyExistsError,
            resolve_skill_dir_from_archive,
            safe_extract_skill_archive,
            scan_archive_preflight_or_raise,
        )
        from deerflow.skills.validation import _validate_skill_frontmatter

        if not path.is_file():
            if not path.exists():
                raise FileNotFoundError(f"Skill file not found: {archive_path}")
            raise ValueError(f"Path is not a file: {archive_path}")
        if path.suffix != ".skill":
            raise ValueError("File must have .skill extension")

        custom_dir.mkdir(parents=True, exist_ok=True)

        try:
            zf = zipfile.ZipFile(path, "r")
        except FileNotFoundError:
            raise FileNotFoundError(f"Skill file not found: {archive_path}") from None
        except (zipfile.BadZipFile, IsADirectoryError):
            raise ValueError("File is not a valid ZIP archive") from None

        with zf:
            scan_archive_preflight_or_raise(path, app_config=self._app_config)
            safe_extract_skill_archive(zf, tmp_path)

        skill_dir = resolve_skill_dir_from_archive(tmp_path)

        is_valid, message, skill_name = _validate_skill_frontmatter(skill_dir)
        if not is_valid:
            raise ValueError(f"Invalid skill: {message}")
        if not skill_name or "/" in skill_name or "\\" in skill_name or ".." in skill_name:
            raise ValueError(f"Invalid skill name: {skill_name}")

        target = custom_dir / skill_name
        if target.exists():
            raise SkillAlreadyExistsError(f"Skill '{skill_name}' already exists")

        return skill_dir, skill_name, target

    def _commit_skill_install(self, skill_dir: Path, skill_name: str, custom_dir: Path, target: Path) -> None:
        """Stage and move the validated skill into place (blocking; runs off the event loop)."""
        from deerflow.skills.installer import _move_staged_skill_into_reserved_target

        with tempfile.TemporaryDirectory(prefix=f".installing-{skill_name}-", dir=custom_dir) as staging_root:
            staging_target = Path(staging_root) / skill_name
            shutil.copytree(skill_dir, staging_target)
            _move_staged_skill_into_reserved_target(staging_target, target)
        make_skill_written_path_sandbox_readable(custom_dir, target)

    def delete_custom_skill(self, name: str, *, history_meta: dict | None = None) -> None:
        self.validate_skill_name(name)
        self.ensure_custom_skill_is_editable(name)
        target = self.get_custom_skill_dir(name)
        if history_meta is not None:
            prev_content = self.read_custom_skill(name)
            try:
                self.append_history(name, {**history_meta, "prev_content": prev_content})
            except OSError as e:
                if not isinstance(e, PermissionError) and e.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
                    raise
                logger.warning(
                    "Skipping delete history write for custom skill %s due to readonly/permission failure; continuing with skill directory removal: %s",
                    name,
                    e,
                )
        if target.exists():
            shutil.rmtree(target)

    def append_history(self, name: str, record: dict) -> None:
        self.validate_skill_name(name)
        payload = {"ts": datetime.now(UTC).isoformat(), **record}
        history_path = self.get_skill_history_file(name)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        with history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.write("\n")

    def read_history(self, name: str) -> list[dict]:
        self.validate_skill_name(name)
        history_path = self.get_skill_history_file(name)
        if not history_path.exists():
            return []
        records: list[dict] = []
        for line in history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            records.append(json.loads(line))
        return records
