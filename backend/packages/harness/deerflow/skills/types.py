from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """Represents a skill with its metadata and file path"""

    name: str
    description: str
    license: str | None
    skill_dir: Path
    skill_file: Path
    relative_path: Path  # Relative path from category root to skill directory
    category: str  # 'public' or 'custom'
    enabled: bool = False  # Whether this skill is enabled

    @property
    def skill_path(self) -> str:
        """Returns the relative path from the category root (skills/{category}) to this skill's directory"""
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def get_container_path(self, container_base_path: str = "/mnt/skills") -> str:
        """
        Get the full path to this skill in the container.

        Args:
            container_base_path: Base path where skills are mounted in the container

        Returns:
            Full container path to the skill directory
        """
        category_base = f"{container_base_path}/{self.category}"
        skill_path = self.skill_path
        if skill_path:
            return f"{category_base}/{skill_path}"
        return category_base

    def get_container_file_path(self, container_base_path: str = "/mnt/skills") -> str:
        """
        Get the full path to this skill's main file (SKILL.md) in the container.

        Args:
            container_base_path: Base path where skills are mounted in the container

        Returns:
            Full container path to the skill's SKILL.md file
        """
        return f"{self.get_container_path(container_base_path)}/SKILL.md"

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, description={self.description!r}, category={self.category!r})"
