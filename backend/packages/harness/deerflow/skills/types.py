from dataclasses import dataclass
from pathlib import Path


@dataclass
class Skill:
    """Represents a skill with its metadata and 文件 路径"""

    name: str
    description: str
    license: str | None
    skill_dir: Path
    skill_file: Path
    relative_path: Path  #    Relative 路径 from category root to skill 目录


    category: str  #    'public' or 'custom'


    enabled: bool = False  #    Whether this skill is 已启用



    @property
    def skill_path(self) -> str:
        """Returns the relative 路径 from the category root (skills/{category}) to this skill's 目录"""
        path = self.relative_path.as_posix()
        return "" if path == "." else path

    def get_container_path(self, container_base_path: str = "/mnt/skills") -> str:
        """
        Get the full 路径 to this skill in the container.

        Args:
            container_base_path: Base 路径 where skills are mounted in the container

        Returns:
            Full container 路径 to the skill 目录
        """
        category_base = f"{container_base_path}/{self.category}"
        skill_path = self.skill_path
        if skill_path:
            return f"{category_base}/{skill_path}"
        return category_base

    def get_container_file_path(self, container_base_path: str = "/mnt/skills") -> str:
        """
        Get the full 路径 to this skill's main 文件 (SKILL.md) in the container.

        Args:
            container_base_path: Base 路径 where skills are mounted in the container

        Returns:
            Full container 路径 to the skill's SKILL.md 文件
        """
        return f"{self.get_container_path(container_base_path)}/SKILL.md"

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, description={self.description!r}, category={self.category!r})"
