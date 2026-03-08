import os
from pathlib import Path

from pydantic import BaseModel, Field


class SkillsConfig(BaseModel):
    """Configuration for skills system"""

    path: str | None = Field(
        default=None,
        description="Path to skills directory. If not specified, defaults to ../skills relative to backend directory",
    )
    container_path: str = Field(
        default="/mnt/skills",
        description="Path where skills are mounted in the sandbox container",
    )

    @staticmethod
    def _resolve_relative_base_dir() -> Path:
        config_env_path = os.getenv("DEER_FLOW_CONFIG_PATH")
        if config_env_path:
            config_path = Path(config_env_path).expanduser()
            if not config_path.is_absolute():
                config_path = (Path.cwd() / config_path).resolve()
            return config_path.parent

        cwd = Path.cwd()
        if (cwd / "config.yaml").exists():
            return cwd

        if (cwd.parent / "config.yaml").exists():
            return cwd.parent

        return cwd

    def get_skills_path(self) -> Path:
        """
        Get the resolved skills directory path.

        Returns:
            Path to the skills directory
        """
        if self.path:
            path = Path(self.path)
            if not path.is_absolute():
                path = self._resolve_relative_base_dir() / path
            return path.resolve()
        else:
            from src.skills.loader import get_skills_root_path

            return get_skills_root_path()

    def get_skill_container_path(self, skill_name: str, category: str = "public") -> str:
        """
        Get the full container path for a specific skill.

        Args:
            skill_name: Name of the skill (directory name)
            category: Category of the skill (public or custom)

        Returns:
            Full path to the skill in the container
        """
        return f"{self.container_path}/{category}/{skill_name}"
