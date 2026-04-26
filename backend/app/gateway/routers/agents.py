"""
自定义代理 CRUD API 路由模块

===================
设计思路说明
===================

**为什么需要这个模块**：
1. **动态代理管理**：允许用户创建、配置和管理自定义AI代理
2. **配置持久化**：将代理配置存储到文件系统，支持重启后恢复
3. **个性化定制**：通过SOUL.md为代理注入个性和行为约束

**核心设计模式**：
- MVC模式：路由层负责HTTP处理，配置层负责业务逻辑
- RESTful API：使用标准HTTP方法（GET/POST/PUT/DELETE）操作资源
- 仓库模式：通过 agent_dir() 管理代理配置的存储位置

**为什么这样设计**：
- **分层架构**：路由层与配置层分离，便于测试和维护
- **名称规范化**：代理名称强制转为小写，避免大小写冲突
- **验证前置**：创建/更新前验证名称格式，提供快速失败反馈

**关键概念**：
- **自定义代理（Custom Agent）**：用户定义的AI代理，具有特定配置
- **SOUL.md**：定义代理个性和行为约束的Markdown文件
- **USER.md**：全局用户配置文件，注入到所有自定义代理中
- **工具组白名单**：限制代理只能使用指定的工具组

**安全考虑**：
1. **名称验证**：只允许字母、数字和连字符，防止注入攻击
2. **路径限制**：代理目录使用规范化的名称，避免路径遍历
3. **原子操作**：创建失败时清理已创建的文件，保持一致性
"""

import logging
import re
import shutil

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deerflow.config.agents_config import AgentConfig, list_custom_agents, load_agent_config, load_agent_soul
from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["agents"])

# 代理名称的正则表达式模式
# 为什么这样限制：
# 1. 只包含字母、数字和连字符，避免特殊字符引起的问题
# 2. 与DNS和文件系统命名规范一致
# 3. 防止路径遍历和注入攻击
# 4. 便于在URL中使用，无需额外编码
AGENT_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")


class AgentResponse(BaseModel):
    """
    自定义代理的响应模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    定义返回给客户端的代理数据结构，包含所有可序列化的代理属性。

    **为什么这样设计**：
    - **字段可选性**：大部分字段有默认值，便于部分更新
    - **描述性字段**：使用 Field 的 description 参数提供API文档
    - **SOUL条件包含**：soul字段仅在明确请求时包含，减少传输数据量

    **字段说明**：
    - name: 代理名称（kebab-case格式，如 my-agent）
    - description: 代理描述，说明其用途和特点
    - model: 可选的模型覆盖，指定使用的LLM模型
    - tool_groups: 可选的工具组白名单，限制代理可用的工具
    - soul: SOUL.md内容，定义代理的个性和行为约束
    """

    name: str = Field(..., description="Agent name (hyphen-case)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    soul: str | None = Field(default=None, description="SOUL.md content (included on GET /{name})")


class AgentsListResponse(BaseModel):
    """
    列出所有自定义代理的响应模型

    **为什么这样设计**：
    - 包装列表：为未来扩展（如分页、总数统计）预留空间
    - 简洁命名：直接使用 agents 而非 items，提高可读性
    """

    agents: list[AgentResponse]


class AgentCreateRequest(BaseModel):
    """
    创建自定义代理的请求模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    验证客户端提交的创建代理请求，确保数据完整性。

    **为什么这样设计**：
    - **name 必填**：代理名称是核心标识，必须提供
    - **其他字段可选**：允许创建最小化配置的代理
    - **soul 默认为空字符串**：确保总是有值，便于处理

    **验证规则**：
    - name: 必须匹配 ^[A-Za-z0-9-]+$ 正则表达式
    - 所有字段在创建后会被规范化（如 name 转为小写）
    """

    name: str = Field(..., description="Agent name (must match ^[A-Za-z0-9-]+$, stored as lowercase)")
    description: str = Field(default="", description="Agent description")
    model: str | None = Field(default=None, description="Optional model override")
    tool_groups: list[str] | None = Field(default=None, description="Optional tool group whitelist")
    soul: str = Field(default="", description="SOUL.md content — agent personality and behavioral guardrails")


class AgentUpdateRequest(BaseModel):
    """
    更新自定义代理的请求模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    支持部分更新代理配置，只更新提供的字段。

    **为什么这样设计**：
    - **所有字段可选**：允许部分更新，不需要提供完整配置
    - **None 表示不更新**：与空字符串区分，空字符串是有效值
    - **灵活更新**：可以只更新描述、模型或SOUL中的任意组合

    **使用场景**：
    - 只更新描述：{"description": "新的描述"}
    - 只更新SOUL：{"soul": "新的个性内容"}
    - 同时更新多个：{"description": "...", "model": "..."}
    """

    description: str | None = Field(default=None, description="Updated description")
    model: str | None = Field(default=None, description="Updated model override")
    tool_groups: list[str] | None = Field(default=None, description="Updated tool group whitelist")
    soul: str | None = Field(default=None, description="Updated SOUL.md content")


def _validate_agent_name(name: str) -> None:
    """
    验证代理名称是否符合允许的模式

    ===================
    设计思路说明
    ===================

    **核心职责**：
    在创建或操作代理前验证名称格式，提供快速失败反馈。

    **为什么这样设计**：
    - **前置验证**：在文件系统操作前验证，避免部分创建
    - **明确错误**：返回详细的错误信息，说明允许的格式
    - **HTTP 422**：使用语义状态码表示验证错误

    **验证规则**：
    - 只允许字母（大小写）、数字和连字符
    - 不允许空字符串
    - 不允许特殊字符（包括下划线、空格等）

    **为什么禁止下划线**：
    - 统一使用 kebab-case（连字符）命名风格
    - 避免与 snake_case（下划线）混淆
    - 与URL和DNS命名习惯一致

    **参数说明**：
    - name: 待验证的代理名称

    **异常**：
    - HTTPException(422): 当名称不符合模式时抛出
    """

    if not AGENT_NAME_PATTERN.match(name):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid agent name '{name}'. Must match ^[A-Za-z0-9-]+$ (letters, digits, and hyphens only).",
        )


def _normalize_agent_name(name: str) -> str:
    """
    将代理名称规范化为小写用于文件系统存储

    ===================
    设计思路说明
    ===================

    **核心职责**：
    确保代理名称在文件系统中的统一表示，避免大小写冲突。

    **为什么这样设计**：
    - **大小写不敏感**：文件系统可能大小写不敏感，统一小写避免冲突
    - **URL友好**：小写名称在URL中更规范
    - **一致性**：所有代理使用相同的命名约定

    **为什么只转小写而不做其他处理**：
    - 名称已在 _validate_agent_name 中验证格式
    - 避免意外改变名称（如删除连字符）
    - 保持用户输入的语义，只改变大小写

    **参数说明**：
    - name: 原始代理名称

    **返回值**：
    - 小写的代理名称
    """

    return name.lower()


def _agent_config_to_response(agent_cfg: AgentConfig, include_soul: bool = False) -> AgentResponse:
    """
    将 AgentConfig 对象转换为 AgentResponse 响应模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    在内部配置对象和API响应模型之间进行转换。

    **为什么这样设计**：
    - **关注点分离**：配置对象包含内部逻辑，响应模型面向客户端
    - **条件加载**：soul 文件较大，按需加载提高性能
    - **统一转换**：避免在多个端点中重复转换逻辑

    **性能考虑**：
    - soul 文件I/O是昂贵的操作，只在 include_soul=True 时执行
    - 默认情况下不包含 soul，减少列表端点的响应时间

    **参数说明**：
    - agent_cfg: 从文件加载的代理配置对象
    - include_soul: 是否包含 SOUL.md 内容（默认False）

    **返回值**：
    - AgentResponse 对象，准备好序列化为JSON
    """

    soul: str | None = None
    if include_soul:
        # 只在需要时加载 soul 文件
        soul = load_agent_soul(agent_cfg.name) or ""

    return AgentResponse(
        name=agent_cfg.name,
        description=agent_cfg.description,
        model=agent_cfg.model,
        tool_groups=agent_cfg.tool_groups,
        soul=soul,
    )


@router.get(
    "/agents",
    response_model=AgentsListResponse,
    summary="List Custom Agents",
    description="List all custom agents available in the agents directory.",
)
async def list_agents() -> AgentsListResponse:
    """
    列出所有自定义代理

    ===================
    设计思路说明
    ===================

    **核心职责**：
    返回系统中所有可用的自定义代理的摘要信息。

    **为什么这样设计**：
    - **轻量级响应**：不包含 soul 内容，减少数据传输
    - **快速加载**：只读取配置文件，不读取额外的 Markdown 文件
    - **错误处理**：捕获异常并返回友好的错误消息

    **使用场景**：
    - 代理选择器：让用户选择要使用的代理
    - 代理管理：显示已配置的所有代理
    - 状态检查：验证代理配置是否正确加载

    **性能考虑**：
    - 假设代理数量不会特别多（通常 < 100），一次性加载是可接受的
    - 如果代理数量增长，可能需要添加分页支持

    **返回值**：
    - AgentsListResponse，包含所有代理的列表（不含 soul）
    """

    try:
        agents = list_custom_agents()
        return AgentsListResponse(agents=[_agent_config_to_response(a) for a in agents])
    except Exception as e:
        logger.error(f"Failed to list agents: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list agents: {str(e)}")


@router.get(
    "/agents/check",
    summary="Check Agent Name",
    description="Validate an agent name and check if it is available (case-insensitive).",
)
async def check_agent_name(name: str) -> dict:
    """
    检查代理名称是否有效且可用

    ===================
    设计思路说明
    ===================

    **核心职责**：
    在创建代理前验证名称并提供可用性检查。

    **为什么这样设计**：
    - **前置验证**：允许客户端在提交创建请求前验证名称
    - **即时反馈**：提供更好的用户体验，避免提交后才发现错误
    - **大小写不敏感**：规范化后检查，避免大小写变体冲突

    **使用场景**：
    - 表单验证：用户输入名称时实时检查
    - 冲突检测：创建前检查名称是否已被使用
    - 规范化提示：返回规范化后的名称供客户端使用

    **返回值**：
    - available (bool): 名称是否可用（未被占用）
    - name (str): 规范化后的名称（小写）

    **异常**：
    - HTTPException(422): 名称格式无效时
    """

    _validate_agent_name(name)
    normalized = _normalize_agent_name(name)
    # 检查代理目录是否已存在
    available = not get_paths().agent_dir(normalized).exists()
    return {"available": available, "name": normalized}


@router.get(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Get Custom Agent",
    description="Retrieve details and SOUL.md content for a specific custom agent.",
)
async def get_agent(name: str) -> AgentResponse:
    """
    获取指定自定义代理的详细信息

    ===================
    设计思路说明
    ===================

    **核心职责**：
    返回单个代理的完整配置，包括 SOUL.md 内容。

    **为什么这样设计**：
    - **包含 soul**：与列表端点不同，这里包含完整的 soul 内容
    - **规范化名称**：确保名称大小写不影响查找
    - **404 响应**：代理不存在时返回明确的错误

    **使用场景**：
    - 代理详情页：显示代理的完整配置
    - 编辑表单：加载代理的当前配置供编辑
    - 配置查看：检查代理的 SOUL.md 内容

    **参数说明**：
    - name: 代理名称（会自动规范化为小写）

    **返回值**：
    - AgentResponse，包含代理的所有信息（包括 soul）

    **异常**：
    - HTTPException(404): 代理不存在时
    - HTTPException(500): 读取配置失败时
    """

    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    try:
        agent_cfg = load_agent_config(name)
        return _agent_config_to_response(agent_cfg, include_soul=True)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error(f"Failed to get agent '{name}": {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get agent: {str(e)}")


@router.post(
    "/agents",
    response_model=AgentResponse,
    status_code=201,
    summary="Create Custom Agent",
    description="Create a new custom agent with its config and SOUL.md.",
)
async def create_agent_endpoint(request: AgentCreateRequest) -> AgentResponse:
    """
    创建新的自定义代理

    ===================
    设计思路说明
    ===================

    **核心职责**：
    根据客户端提供的配置创建新的自定义代理。

    **为什么这样设计**：
    - **原子性**：创建失败时清理已创建的文件，保持一致性
    - **201 状态码**：使用标准的 Created 状态码
    - **冲突检测**：代理已存在时返回 409 Conflict

    **创建流程**：
    1. 验证名称格式
    2. 规范化名称（转小写）
    3. 检查是否已存在
    4. 创建代理目录
    5. 写入 config.yaml
    6. 写入 SOUL.md
    7. 重新加载并返回配置

    **为什么创建失败时需要清理**：
    - 避免留下不完整的配置目录
    - 防止客户端看到部分创建的代理
    - 简化重试逻辑（可以直接重试，无需先清理）

    **参数说明**：
    - request: 包含代理配置的创建请求

    **返回值**：
    - AgentResponse，包含创建的代理信息（包括 soul）

    **异常**：
    - HTTPException(409): 代理已存在
    - HTTPException(422): 名称格式无效
    - HTTPException(500): 创建失败（已清理）
    """

    _validate_agent_name(request.name)
    normalized_name = _normalize_agent_name(request.name)

    agent_dir = get_paths().agent_dir(normalized_name)

    if agent_dir.exists():
        raise HTTPException(status_code=409, detail=f"Agent '{normalized_name}' already exists")

    try:
        # 创建代理目录（包括父目录）
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 准备配置数据：只包含非空字段
        config_data: dict = {"name": normalized_name}
        if request.description:
            config_data["description"] = request.description
        if request.model is not None:
            config_data["model"] = request.model
        if request.tool_groups is not None:
            config_data["tool_groups"] = request.tool_groups

        # 写入 config.yaml
        # 为什么使用 yaml.dump：
        # - 人类可读的格式
        # - 支持注释
        # - 便于手动编辑
        config_file = agent_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

        # 写入 SOUL.md
        soul_file = agent_dir / "SOUL.md"
        soul_file.write_text(request.soul, encoding="utf-8")

        logger.info(f"Created agent '{normalized_name}' at {agent_dir}")

        # 重新加载配置以验证和返回
        agent_cfg = load_agent_config(normalized_name)
        return _agent_config_to_response(agent_cfg, include_soul=True)

    except HTTPException:
        raise
    except Exception as e:
        # 清理失败时创建的文件
        # 为什么需要清理：
        # 1. 避免留下不完整的配置
        # 2. 防止客户端误认为创建成功
        # 3. 简化重试逻辑
        if agent_dir.exists():
            shutil.rmtree(agent_dir)
        logger.error(f"Failed to create agent '{request.name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create agent: {str(e)}")


@router.put(
    "/agents/{name}",
    response_model=AgentResponse,
    summary="Update Custom Agent",
    description="Update an existing custom agent's config and/or SOUL.md.",
)
async def update_agent(name: str, request: AgentUpdateRequest) -> AgentResponse:
    """
    更新现有自定义代理的配置

    ===================
    设计思路说明
    ===================

    **核心职责**：
    部分或完全更新代理的配置和 SOUL.md 内容。

    **为什么这样设计**：
    - **部分更新**：只更新提供的字段，未提供的保持不变
    - **区分 None 和空值**：None 表示不更新，空字符串表示清空
    - **原子性**：配置和 soul 的更新在同一事务中

    **更新流程**：
    1. 验证并规范化名称
    2. 加载现有配置
    3. 检查哪些字段需要更新
    4. 更新 config.yaml（如果有配置变更）
    5. 更新 SOUL.md（如果提供）
    6. 重新加载并返回更新后的配置

    **为什么需要重新加载配置**：
    - 确保返回的配置反映文件系统中的实际状态
    - 验证写入操作是否成功
    - 获取任何可能由写入操作触发的默认值

    **参数说明**：
    - name: 代理名称
    - request: 更新请求（所有字段都是可选的）

    **返回值**：
    - 更新后的 AgentResponse

    **异常**：
    - HTTPException(404): 代理不存在
    - HTTPException(500): 更新失败
    """

    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    try:
        agent_cfg = load_agent_config(name)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    agent_dir = get_paths().agent_dir(name)

    try:
        # 检查是否有配置字段需要更新
        # 使用 is not None 而不是简单的 truthy 检查
        # 这样可以区分"未提供"（None）和"设置为空值"（空字符串）
        config_changed = any(v is not None for v in [request.description, request.model, request.tool_groups])

        if config_changed:
            # 构建更新后的配置
            updated: dict = {
                "name": agent_cfg.name,
                "description": request.description if request.description is not None else agent_cfg.description,
            }
            # 模型字段特殊处理：None 可能表示移除覆盖
            new_model = request.model if request.model is not None else agent_cfg.model
            if new_model is not None:
                updated["model"] = new_model

            # 工具组字段特殊处理：None 可能表示移除白名单
            new_tool_groups = request.tool_groups if request.tool_groups is not None else agent_cfg.tool_groups
            if new_tool_groups is not None:
                updated["tool_groups"] = new_tool_groups

            # 写入更新后的配置
            config_file = agent_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(updated, f, default_flow_style=False, allow_unicode=True)

        # 如果提供了新的 soul 内容，更新 SOUL.md
        if request.soul is not None:
            soul_path = agent_dir / "SOUL.md"
            soul_path.write_text(request.soul, encoding="utf-8")

        logger.info(f"Updated agent '{name}'")

        # 重新加载配置以验证并返回
        refreshed_cfg = load_agent_config(name)
        return _agent_config_to_response(refreshed_cfg, include_soul=True)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update agent: {str(e)}")


class UserProfileResponse(BaseModel):
    """
    全局用户配置（USER.md）的响应模型

    ===================
    设计思路说明
    ===================

    **核心职责**：
    定义用户配置文件的响应结构。

    **为什么这样设计**：
    - **content 可为 None**：表示文件尚未创建，而非内容为空
    - **语义区分**：None（不存在）和空字符串（已创建但无内容）有不同含义

    **使用场景**：
    - 用户设置页面：加载和编辑用户配置
    - 代理初始化：将用户配置注入到代理上下文中
    """

    content: str | None = Field(default=None, description="USER.md content, or null if not yet created")


class UserProfileUpdateRequest(BaseModel):
    """
    更新全局用户配置的请求模型

    **核心职责**：
    定义更新用户配置的请求结构。

    **为什么使用空字符串作为默认值**：
    - 允许用户清空配置（写入空文件）
    - 与 None（不更新）区分
    """

    content: str = Field(default="", description="USER.md content — describes the user's background and preferences")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Get User Profile",
    description="Read the global USER.md file that is injected into all custom agents.",
)
async def get_user_profile() -> UserProfileResponse:
    """
    获取全局用户配置文件内容

    ===================
    设计思路说明
    ===================

    **核心职责**：
    读取注入到所有自定义代理的全局用户配置。

    **为什么这样设计**：
    - **不存在时返回 None**：区分"未创建"和"空内容"
    - **去除空白**：使用 strip() 避免返回纯空白内容
    - **全局配置**：所有代理共享此配置，避免重复设置

    **使用场景**：
    - 代理上下文注入：代理启动时加载用户背景信息
    - 用户设置页面：显示和编辑全局配置
    - 个性化定制：根据用户偏好调整代理行为

    **返回值**：
    - UserProfileResponse，content 为文件内容或 None（如果不存在）
    """

    try:
        user_md_path = get_paths().user_md_file
        if not user_md_path.exists():
            return UserProfileResponse(content=None)
        raw = user_md_path.read_text(encoding="utf-8").strip()
        # 空字符串也转换为 None，保持一致性
        return UserProfileResponse(content=raw or None)
    except Exception as e:
        logger.error(f"Failed to read user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read user profile: {str(e)}")


@router.put(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="Update User Profile",
    description="Write the global USER.md file that is injected into all custom agents.",
)
async def update_user_profile(request: UserProfileUpdateRequest) -> UserProfileResponse:
    """
    创建或更新全局用户配置文件

    ===================
    设计思路说明
    ===================

    **核心职责**：
    写入全局用户配置，该配置会被注入到所有自定义代理中。

    **为什么这样设计**：
    - **覆盖式写入**：每次更新完全覆盖，不保留历史
    - **自动创建目录**：确保目录存在，避免路径错误
    - **规范化处理**：空字符串存储为空文件

    **使用场景**：
    - 用户首次设置：创建初始配置
    - 更新用户信息：修改背景或偏好
    - 配置重置：清空现有配置

    **参数说明**：
    - request: 包含新用户配置的请求

    **返回值**：
    - 更新后的 UserProfileResponse

    **异常**：
    - HTTPException(500): 写入失败
    """

    try:
        paths = get_paths()
        # 确保基础目录存在
        paths.base_dir.mkdir(parents=True, exist_ok=True)
        paths.user_md_file.write_text(request.content, encoding="utf-8")
        logger.info(f"Updated USER.md at {paths.user_md_file}")
        return UserProfileResponse(content=request.content or None)
    except Exception as e:
        logger.error(f"Failed to update user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update user profile: {str(e)}")


@router.delete(
    "/agents/{name}",
    status_code=204,
    summary="Delete Custom Agent",
    description="Delete a custom agent and all its files (config, SOUL.md, memory).",
)
async def delete_agent(name: str) -> None:
    """
    删除自定义代理及其所有文件

    ===================
    设计思路说明
    ===================

    **核心职责**：
    永久删除代理及其所有相关文件。

    **为什么这样设计**：
    - **204 状态码**：表示成功但无返回内容
    - **递归删除**：删除整个代理目录，包括配置、SOUL 和内存
    - **不可逆操作**：删除后无法恢复，需要明确确认

    **安全考虑**：
    - 验证名称格式，防止路径遍历
    - 检查目录存在性，避免误删
    - 完整删除，不留残留文件

    **删除的内容**：
    - config.yaml：代理配置
    - SOUL.md：代理个性定义
    - 内存文件：代理的对话历史和记忆

    **参数说明**：
    - name: 要删除的代理名称

    **异常**：
    - HTTPException(404): 代理不存在
    - HTTPException(500): 删除失败
    """

    _validate_agent_name(name)
    name = _normalize_agent_name(name)

    agent_dir = get_paths().agent_dir(name)

    if not agent_dir.exists():
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        # 递归删除整个代理目录
        shutil.rmtree(agent_dir)
        logger.info(f"Deleted agent '{name}' from {agent_dir}")
    except Exception as e:
        logger.error(f"Failed to delete agent '{name}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete agent: {str(e)}")
