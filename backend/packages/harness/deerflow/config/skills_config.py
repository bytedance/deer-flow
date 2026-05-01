import os
from pathlib import Path

from pydantic import BaseModel, Field

from deerflow.config.runtime_paths import project_root, resolve_path


class SkillsConfig(BaseModel):
    """Configuration for skills system"""

    use: str = Field(
        default="deerflow.skills.storage.local_skill_storage:LocalSkillStorage",
        description="Class path of the SkillStorage implementation.",
    )
    path: str | None = Field(
        default=None,
        description="Path to skills directory. If not specified, defaults to skills under the caller project root.",
    )
    container_path: str = Field(
        default="/mnt/skills",
        description="Path where skills are mounted in the sandbox container",
    )

    def get_skills_path(self) -> Path:
        """
        Get the resolved skills directory path.

        Returns:
            Path to the skills directory
        """
        if self.path:
            # Use configured path (can be absolute or relative to project root)
            return resolve_path(self.path)
        if env_path := os.getenv("DEER_FLOW_SKILLS_PATH"):
            return resolve_path(env_path)
        return project_root() / "skills"

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
