"""
技能系统配置模块

====================
设计思路说明
====================

**核心职责**：
1. 定义技能目录路径配置
2. 管理主机与容器间的路径映射
3. 提供技能路径解析功能

**什么是技能（Skills）**：
- 预定义的工具集合
- 封装特定功能的代码
- 可被AI代理调用
- 支持公共和自定义技能

**为什么需要技能系统**：
- 扩展AI能力边界
- 代码复用和模块化
- 社区共享生态
- 简化复杂任务

**技能目录结构**：
```
skills/
├── public/           # 公共技能（社区贡献）
│   ├── web_search/
│   ├── file_ops/
│   └── ...
└── custom/           # 自定义技能（用户编写）
    ├── my_tool/
    └── ...
```

**为什么需要容器路径映射**：
- 沙箱容器内需要访问技能
- 主机路径在容器内不同
- 统一的挂载点简化配置
"""

from pathlib import Path

from pydantic import BaseModel, Field


class SkillsConfig(BaseModel):
    """技能系统配置

    **path字段**：
    - 技能目录的主机路径
    - None使用默认位置（backend/../skills）
    - 支持绝对路径和相对路径

    **container_path字段**：
    - 技能在容器内的挂载点
    - 默认：/mnt/skills
    - 所有技能统一挂载点

    **路径解析逻辑**：
    1. 配置了path：使用配置路径
    2. path是相对路径：从当前工作目录解析
    3. path未配置：使用默认路径（相对于backend目录）
    """

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
        获取解析后的技能目录路径

        **解析逻辑**：
        1. 如果配置了path：
           - 绝对路径：直接使用
           - 相对路径：从当前工作目录解析
        2. 如果未配置path：
           - 使用默认路径（相对于backend目录）

        **为什么支持相对路径**：
        - 配置文件可移植
        - 不同环境使用相同配置
        - 简化开发环境设置

        Returns:
            技能目录的绝对路径
        """
        if self.path:
            # Use configured path (can be absolute or relative)
            path = Path(self.path)
            if not path.is_absolute():
                # If relative, resolve from current working directory
                path = Path.cwd() / path
            return path.resolve()
        else:
            # Default: ../skills relative to backend directory
            from deerflow.skills.loader import get_skills_root_path

            return get_skills_root_path()

    def get_skill_container_path(self, skill_name: str, category: str = "public") -> str:
        """
        获取特定技能的完整容器路径

        **路径格式**：{container_path}/{category}/{skill_name}

        **category参数**：
        - public: 公共技能（社区贡献）
        - custom: 自定义技能（用户编写）

        **使用场景**：
        - 构建技能的容器内路径
        - 挂载特定技能到沙箱
        - 验证技能是否存在

        Args:
            skill_name: 技能名称（目录名）
            category: 技能类别（public或custom）

        Returns:
            容器内技能的完整路径
        """
        return f"{self.container_path}/{category}/{skill_name}"
