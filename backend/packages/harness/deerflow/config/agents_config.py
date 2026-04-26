"""自定义代理配置和加载器

====================
设计思路说明
====================

**核心职责**：
1. 加载自定义代理的配置文件（config.yaml）
2. 读取代理的"灵魂"文档（SOUL.md）- 定义代理个性和行为准则
3. 扫描并列出所有可用的自定义代理

**为什么需要自定义代理**：
- 不同场景需要不同个性的AI助手（如客服、编程助手、写作助手）
- SOUL.md允许为代理注入独特的价值观和行为边界
- 工具分组允许不同代理访问不同的工具集

**设计原则**：
- 代理目录结构：agents/{name}/config.yaml + SOUL.md
- 名称验证：只允许字母、数字和连字符，防止路径遍历
- 向后兼容：自动过滤未知字段，支持旧配置格式

**SOUL.md的作用**：
- 定义代理的"个性"：说话风格、价值观、偏见
- 设置行为边界：什么该做、什么不该做
- 注入到系统提示词：影响代理的所有决策
"""

import logging
import re
from typing import Any

import yaml
from pydantic import BaseModel

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)

SOUL_FILENAME = "SOUL.md"
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentConfig(BaseModel):
    """自定义代理配置模型

    **为什么需要这些字段**：
    - name: 代理的唯一标识符
    - description: 代理功能说明，用于UI展示
    - model: 指定使用的LLM模型（覆盖默认配置）
    - tool_groups: 工具分组列表，控制代理能访问哪些工具

    **工具分组的设计理念**：
    - 不同的代理需要不同的工具集
    - 客服代理需要查询工具，编程代理需要代码执行工具
    - 通过分组实现最小权限原则
    """

    name: str
    description: str = ""
    model: str | None = None
    tool_groups: list[str] | None = None


def load_agent_config(name: str | None) -> AgentConfig | None:
    """从代理目录加载自定义或默认代理的配置

    **加载流程**：
    1. 验证代理名称格式（防止路径遍历攻击）
    2. 定位代理目录：agents/{name}/
    3. 解析config.yaml文件
    4. 过滤未知字段（保持向后兼容）
    5. 返回强类型配置对象

    **为什么需要名称验证**：
    - 防止目录遍历攻击（如../../../etc/passwd）
    - 确保文件系统安全性
    - 提供清晰的错误提示

    **为什么过滤未知字段**：
    - 配置格式会演进，旧文件可能包含废弃字段
    - Pydantic严格模式会拒绝未知字段
    - 过滤后保持向后兼容性

    Args:
        name: 代理名称，None表示使用默认代理

    Returns:
        AgentConfig实例，如果name为None则返回None

    Raises:
        FileNotFoundError: 代理目录或config.yaml不存在
        ValueError: 配置文件解析失败或名称格式无效
    """

    if name is None:
        return None

    if not AGENT_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid agent name '{name}'. Must match pattern: {AGENT_NAME_PATTERN.pattern}")
    agent_dir = get_paths().agent_dir(name)
    config_file = agent_dir / "config.yaml"

    if not agent_dir.exists():
        raise FileNotFoundError(f"Agent directory not found: {agent_dir}")

    if not config_file.exists():
        raise FileNotFoundError(f"Agent config not found: {config_file}")

    try:
        with open(config_file, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse agent config {config_file}: {e}") from e

    # Ensure name is set from directory name if not in file
    if "name" not in data:
        data["name"] = name

    # Strip unknown fields before passing to Pydantic (e.g. legacy prompt_file)
    known_fields = set(AgentConfig.model_fields.keys())
    data = {k: v for k, v in data.items() if k in known_fields}

    return AgentConfig(**data)


def load_agent_soul(agent_name: str | None) -> str | None:
    """读取自定义代理的SOUL.md文件（如果存在）

    **SOUL.md的作用**：
    - 定义代理的个性：说话风格、语气、态度
    - 设置价值观：什么重要、什么优先
    - 行为边界：什么该做、什么不该做
    - 注入到系统提示词，影响代理的所有决策

    **为什么使用SOUL.md而不是硬编码**：
    - 允许非技术人员通过自然语言定制代理行为
    - 版本控制友好，可以A/B测试不同的个性
    - 同一代码库支持多种代理个性

    **SOUL.md示例内容**：
    - "你是一个友善耐心的客服代表..."
    - "你是一个直率的编程专家，不喜欢废话..."
    - "你专注于安全，永远不会执行危险操作..."

    Args:
        agent_name: 代理名称，None表示使用默认代理

    Returns:
        SOUL.md内容字符串，如果文件不存在则返回None
    """
    agent_dir = get_paths().agent_dir(agent_name) if agent_name else get_paths().base_dir
    soul_path = agent_dir / SOUL_FILENAME
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    return content or None


def list_custom_agents() -> list[AgentConfig]:
    """扫描代理目录并返回所有有效的自定义代理

    **扫描逻辑**：
    1. 遍历agents目录下的所有子目录
    2. 检查每个子目录是否包含config.yaml
    3. 尝试加载并验证配置
    4. 跳过无效目录，记录警告日志

    **为什么跳过无效配置而不是抛出异常**：
    - 允许部分代理配置错误不影响整体系统
    - 开发过程中可能有未完成的代理目录
    - 提供更好的用户体验（部分功能可用）

    **使用场景**：
    - UI展示可用的代理列表
    - 配置验证和诊断
    - 动态加载新代理

    Returns:
        所有有效代理的AgentConfig列表，按名称排序
    """
    agents_dir = get_paths().agents_dir

    if not agents_dir.exists():
        return []

    agents: list[AgentConfig] = []

    for entry in sorted(agents_dir.iterdir()):
        if not entry.is_dir():
            continue

        config_file = entry / "config.yaml"
        if not config_file.exists():
            logger.debug(f"Skipping {entry.name}: no config.yaml")
            continue

        try:
            agent_cfg = load_agent_config(entry.name)
            agents.append(agent_cfg)
        except Exception as e:
            logger.warning(f"Skipping agent '{entry.name}': {e}")

    return agents
