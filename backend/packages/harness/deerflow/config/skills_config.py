from pathlib import Path

from pydantic import BaseModel, Field


class SkillsConfig(BaseModel):
    """Configuration for skills 系统"""

    path: str | None = Field(
        default=None,
        description="Path to skills directory. If not specified, defaults to ../skills relative to backend directory",
    )
    container_path: str = Field(
        default="/mnt/skills",
        description="Path where skills are mounted in the sandbox container",
    )

    def get_skills_path(self) -> Path:
        """
        Get the resolved skills 目录 路径.

        Returns:
            Path to the skills 目录
        """
        if self.path:
            #    Use configured 路径 (can be absolute or relative)


            path = Path(self.path)
            if not path.is_absolute():
                #    If relative, resolve from 当前 working 目录


                path = Path.cwd() / path
            return path.resolve()
        else:
            #    Default: ../skills relative to 后端 目录


            from deerflow.skills.loader import get_skills_root_path

            return get_skills_root_path()

    def get_skill_container_path(self, skill_name: str, category: str = "public") -> str:
        """
        Get the full container 路径 for a specific skill.

        Args:
            skill_name: Name of the skill (目录 名称)
            category: Category of the skill (public or custom)

        Returns:
            Full 路径 to the skill in the container
        """
        return f"{self.container_path}/{category}/{skill_name}"
