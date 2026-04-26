"""技能(Skills)管理路由

===================
设计思路说明
===================

**核心职责**：
提供技能的完整生命周期管理API，包括：
1. 查询技能列表和详情
2. 启用/禁用技能
3. 从.skill文件安装新技能

**为什么需要这个模块**：
1. **技能发现**：前端需要展示所有可用技能供用户选择
2. **动态配置**：允许用户在运行时启用/禁用技能，无需重启
3. **扩展机制**：支持通过.skill文件分发和安装自定义技能

**设计决策**：
- RESTful风格：GET查询、PUT更新、POST安装，符合HTTP语义
- 配置持久化：修改extensions_config.json文件，确保重启后配置保留
- 热重载：修改配置后立即重新加载，无需重启服务
- 虚拟路径支持：使用虚拟路径定位.skill文件，增强安全性

**架构说明**：
- 公共技能：位于系统目录，由平台提供
- 自定义技能：位于用户目录，由用户创建
- 技能状态：存储在extensions_config.json中，包含enabled标志

**技能安装流程**：
1. 用户上传.skill文件（ZIP归档）到线程目录
2. 调用/api/skills/install，指定文件路径
3. 系统解压并验证技能
4. 安装到技能目录并更新配置
"""

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.gateway.path_utils import resolve_thread_virtual_path
from deerflow.config.extensions_config import ExtensionsConfig, SkillStateConfig, get_extensions_config, reload_extensions_config
from deerflow.skills import Skill, load_skills
from deerflow.skills.installer import SkillAlreadyExistsError, install_skill_from_archive

logger = logging.getLogger(__name__)

# 为什么使用prefix和tags：
# - prefix: 将所有技能相关端点放在/api路径下（/api/skills等）
# - tags: 用于API文档分组，便于在Swagger UI中浏览
router = APIRouter(prefix="/api", tags=["skills"])


class SkillResponse(BaseModel):
    """技能信息响应模型

    为什么这样设计：
    - 包含技能的基本元数据：名称、描述、许可证等
    - category区分公共技能和自定义技能
    - enabled字段反映当前状态，便于前端展示开关
    """
    name: str = Field(..., description="技能名称")
    description: str = Field(..., description="技能功能描述")
    license: str | None = Field(None, description="许可证信息")
    category: str = Field(..., description="技能类别（public或custom）")
    enabled: bool = Field(default=True, description="技能是否启用")


class SkillsListResponse(BaseModel):
    """技能列表响应模型

    为什么使用包装模型：
    - 便于扩展：未来可添加分页、总数等字段
    - 类型安全：明确返回的是技能列表而非其他数据
    """
    skills: list[SkillResponse]


class SkillUpdateRequest(BaseModel):
    """技能更新请求模型

    为什么只包含enabled字段：
    - 当前只支持启用/禁用操作
    - 未来可扩展添加其他配置项
    """
    enabled: bool = Field(..., description="是否启用技能")


class SkillInstallRequest(BaseModel):
    """技能安装请求模型

    为什么需要thread_id和path：
    - thread_id: 定位文件所在的线程上下文
    - path: 虚拟路径，增强安全性和灵活性

    设计考虑：
    - 使用虚拟路径而非直接上传：文件已通过其他API上传
    - 解耦设计：上传和安装分离，提高灵活性
    """
    thread_id: str = Field(..., description=".skill文件所在的线程ID")
    path: str = Field(..., description=".skill文件的虚拟路径（如mnt/user-data/outputs/my-skill.skill）")


class SkillInstallResponse(BaseModel):
    """技能安装响应模型

    为什么这样设计：
    - success: 明确指示操作结果
    - skill_name: 返回安装的技能名称，便于客户端确认
    - message: 提供详细的结果描述或错误信息
    """
    success: bool = Field(..., description="安装是否成功")
    skill_name: str = Field(..., description="已安装的技能名称")
    message: str = Field(..., description="安装结果消息")


def _skill_to_response(skill: Skill) -> SkillResponse:
    """将Skill对象转换为SkillResponse

    为什么需要转换函数：
    - 解耦领域模型和API模型
    - 便于未来修改Skill结构而不影响API
    - 统一转换逻辑，避免重复代码

    Args:
        skill: 技能领域模型对象

    Returns:
        SkillResponse: API响应模型
    """
    return SkillResponse(
        name=skill.name,
        description=skill.description,
        license=skill.license,
        category=skill.category,
        enabled=skill.enabled,
    )


@router.get(
    "/skills",
    response_model=SkillsListResponse,
    summary="列出所有技能",
    description="从公共和自定义目录检索所有可用技能列表",
)
async def list_skills() -> SkillsListResponse:
    """获取所有技能列表

    为什么enabled_only=False：
    - 显示所有技能，包括禁用的
    - 便于用户了解有哪些技能可用
    - 前端可以根据enabled字段控制UI

    Returns:
        SkillsListResponse: 包含所有技能的列表

    Raises:
        HTTPException: 加载技能失败时返回500
    """
    try:
        # 加载所有技能，包括禁用的
        skills = load_skills(enabled_only=False)
        return SkillsListResponse(skills=[_skill_to_response(skill) for skill in skills])
    except Exception as e:
        logger.error(f"Failed to load skills: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to load skills: {str(e)}")


@router.get(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="获取技能详情",
    description="根据名称检索特定技能的详细信息",
)
async def get_skill(skill_name: str) -> SkillResponse:
    """获取指定技能的详细信息

    Args:
        skill_name: 技能名称

    Returns:
        SkillResponse: 技能详细信息

    Raises:
        HTTPException: 技能不存在时返回404，其他错误返回500
    """
    try:
        skills = load_skills(enabled_only=False)
        # 使用next查找第一个匹配的技能
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        return _skill_to_response(skill)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get skill: {str(e)}")


@router.put(
    "/skills/{skill_name}",
    response_model=SkillResponse,
    summary="更新技能",
    description="通过修改extensions_config.json文件来更新技能的启用状态",
)
async def update_skill(skill_name: str, request: SkillUpdateRequest) -> SkillResponse:
    """更新技能的启用状态

    设计考虑：
    - 直接修改配置文件：确保持久化
    - 热重载：修改后立即生效，无需重启
    - 原子性：先写文件再重载，避免不一致

    为什么使用PUT而非PATCH：
    - PUT语义更明确：替换整个资源状态
    - 未来可能扩展：支持修改更多字段

    Args:
        skill_name: 技能名称
        request: 包含enabled字段的更新请求

    Returns:
        SkillResponse: 更新后的技能信息

    Raises:
        HTTPException: 技能不存在时返回404，更新失败时返回500
    """
    try:
        # 验证技能是否存在
        skills = load_skills(enabled_only=False)
        skill = next((s for s in skills if s.name == skill_name), None)

        if skill is None:
            raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

        # 解析或创建配置文件路径
        # 为什么需要这个逻辑：首次配置时可能没有配置文件
        config_path = ExtensionsConfig.resolve_config_path()
        if config_path is None:
            config_path = Path.cwd().parent / "extensions_config.json"
            logger.info(f"No existing extensions config found. Creating new config at: {config_path}")

        # 更新配置
        extensions_config = get_extensions_config()
        extensions_config.skills[skill_name] = SkillStateConfig(enabled=request.enabled)

        # 准备配置数据
        # 为什么需要转换：
        # 1. extensions_config包含复杂对象，需要序列化为字典
        # 2. 只序列化必要字段，避免存储过多内部数据
        config_data = {
            "mcpServers": {name: server.model_dump() for name, server in extensions_config.mcp_servers.items()},
            "skills": {name: {"enabled": skill_config.enabled} for name, skill_config in extensions_config.skills.items()},
        }

        # 写入配置文件
        # 为什么使用utf-8编码：支持国际化字符
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2)

        logger.info(f"Skills configuration updated and saved to: {config_path}")

        # 重新加载配置以使更改生效
        reload_extensions_config()

        # 重新加载技能以获取更新后的状态
        skills = load_skills(enabled_only=False)
        updated_skill = next((s for s in skills if s.name == skill_name), None)

        if updated_skill is None:
            raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_name}' after update")

        logger.info(f"Skill '{skill_name}' enabled status updated to {request.enabled}")
        return _skill_to_response(updated_skill)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update skill {skill_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update skill: {str(e)}")


@router.post(
    "/skills/install",
    response_model=SkillInstallResponse,
    summary="安装技能",
    description="从位于线程用户数据目录中的.skill文件（ZIP归档）安装技能",
)
async def install_skill(request: SkillInstallRequest) -> SkillInstallResponse:
    """从.skill文件安装新技能

    设计流程：
    1. 解析虚拟路径到实际文件路径
    2. 调用install_skill_from_archive解压并验证
    3. 安装到技能目录
    4. 返回安装结果

    错误处理：
    - 404: 文件不存在
    - 409: 技能已存在
    - 400: 文件格式错误
    - 500: 其他错误

    Args:
        request: 包含thread_id和path的安装请求

    Returns:
        SkillInstallResponse: 安装结果

    Raises:
        HTTPException: 各种安装失败情况
    """
    try:
        # 解析虚拟路径
        skill_file_path = resolve_thread_virtual_path(request.thread_id, request.path)
        # 安装技能
        result = install_skill_from_archive(skill_file_path)
        return SkillInstallResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except SkillAlreadyExistsError as e:
        # 使用409 Conflict表示资源冲突
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to install skill: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to install skill: {str(e)}")
