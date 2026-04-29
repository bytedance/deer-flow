"""Local-filesystem implementation of ``SkillStorage``."""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from deerflow.skills.storage.skill_storage import SKILL_MD_FILE, SkillStorage
from deerflow.skills.types import SkillCategory

logger = logging.getLogger(__name__)

DEFAULT_SKILLS_CONTAINER_PATH = "/mnt/skills"


def _default_repo_root() -> Path:
    """Resolve the repo root without relying on the current working directory."""
    return Path(__file__).resolve().parents[7]


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
    ) -> None:
        super().__init__(container_path=container_path)
        if host_path is None:
            from deerflow.config import get_app_config

            self._host_root: Path = get_app_config().skills.get_skills_path()
        else:
            path = Path(host_path)
            if not path.is_absolute():
                path = _default_repo_root() / path
            self._host_root = path.resolve()

    # ------------------------------------------------------------------
    # Abstract operation implementations
    # ------------------------------------------------------------------

    def get_skills_root_path(self) -> Path:
        return self._host_root

    def custom_skill_exists(self, name: str) -> bool:
        return self.get_custom_skill_file(name).exists()

    def public_skill_exists(self, name: str) -> bool:
        return (self._host_root / SkillCategory.PUBLIC.value / name / SKILL_MD_FILE).exists()

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
                yield category, category_path, Path(current_root) / SKILL_MD_FILE

    def read_custom_skill(self, name: str) -> str:
        if not self.custom_skill_exists(name):
            raise FileNotFoundError(f"Custom skill '{name}' not found.")
        return (self.get_custom_skill_dir(name) / SKILL_MD_FILE).read_text(encoding="utf-8")

    def write_custom_skill(self, name: str, relative_path: str, content: str) -> None:
        target = self.get_custom_skill_dir(name) / relative_path
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

    def install_skill_from_archive(self, archive_path: str | Path) -> dict:
        from deerflow.skills.installer import (
            _run_async_install,
            ainstall_skill_from_archive,
        )

        return _run_async_install(ainstall_skill_from_archive(archive_path))

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
