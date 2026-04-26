"""智能建议生成路由

===================
设计思路说明
===================

**核心职责**：
基于对话历史自动生成后续问题建议，提升用户体验：
1. 分析对话上下文
2. 生成相关的后续问题
3. 支持多语言输出

**为什么需要这个模块**：
1. **用户体验**：帮助用户继续对话，减少思考成本
2. **引导探索**：推荐相关问题，帮助用户发现功能
3. **智能化**：使用AI理解上下文，生成高质量建议

**设计决策**：
- 使用LLM生成：比模板更灵活，能理解对话语义
- JSON格式输出：结构化数据便于前端处理
- 多语言支持：根据用户语言生成相应建议
- 错误降级：生成失败时返回空列表，不影响主流程

**架构说明**：
- 输入：最近的消息历史
- 输出：简短的后续问题列表
- 模型：使用配置的默认模型，支持覆盖

**提示工程要点**：
- 明确要求JSON数组格式
- 限制问题数量
- 保持简洁（≤20词或≤40汉字）
- 匹配用户语言
"""

import json
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)

# 为什么使用prefix和tags：
# - prefix: 将建议相关端点放在/api路径下
# - tags: 用于API文档分组
router = APIRouter(prefix="/api", tags=["suggestions"])


class SuggestionMessage(BaseModel):
    """建议消息模型

    为什么这样设计：
    - role: 消息角色，区分用户和助手
    - content: 消息内容，纯文本格式

    设计考虑：
    - 支持多种role格式：user/human、assistant/ai
    - 简化处理：不处理复杂的内容块
    """
    role: str = Field(..., description="消息角色：user|assistant")
    content: str = Field(..., description="消息内容（纯文本）")


class SuggestionsRequest(BaseModel):
    """建议生成请求模型

    为什么这样设计：
    - messages: 对话历史，用于理解上下文
    - n: 生成数量，限制在1-5之间避免过多
    - model_name: 可选模型覆盖，支持使用不同模型

    设计考虑：
    - n限制在1-5：平衡选择丰富度和UI展示空间
    - 使用list而非dict：保持消息顺序
    """
    messages: list[SuggestionMessage] = Field(..., description="最近的对话消息")
    n: int = Field(default=3, ge=1, le=5, description="生成建议的数量")
    model_name: str | None = Field(default=None, description="可选的模型覆盖")


class SuggestionsResponse(BaseModel):
    """建议响应模型

    为什么使用包装模型：
    - 便于扩展：未来可添加元数据
    - 类型安全：明确返回的是建议列表
    """
    suggestions: list[str] = Field(default_factory=list, description="建议的后续问题")


def _strip_markdown_code_fence(text: str) -> str:
    """移除Markdown代码块标记

    为什么需要这个函数：
    - LLM可能返回```json...```格式
    - 需要提取纯JSON内容
    - 处理边缘情况（无代码块、单行等）

    Args:
        text: 可能包含Markdown代码块的文本

    Returns:
        str: 移除代码块标记后的文本
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    # 检查是否有完整的代码块
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_json_string_list(text: str) -> list[str] | None:
    """从文本中解析JSON字符串列表

    为什么需要复杂的解析逻辑：
    - LLM可能返回带有额外文本的响应
    - 需要提取JSON数组部分
    - 验证并清理数据

    设计考虑：
    - 查找最外层的[和]
    - 验证解析结果是否为列表
    - 过滤空字符串和无效项

    Args:
        text: 可能包含JSON数组的文本

    Returns:
        list[str] | None: 解析成功的字符串列表，失败返回None
    """
    candidate = _strip_markdown_code_fence(text)
    # 查找JSON数组的边界
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    # 验证是否为列表
    if not isinstance(data, list):
        return None
    # 清理数据：只保留非空字符串
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        out.append(s)
    return out


def _extract_response_text(content: object) -> str:
    """从响应内容中提取文本

    为什么需要这个函数：
    - LLM响应可能是字符串、列表或字典
    - 需要统一处理不同格式
    - 提取实际的文本内容

    Args:
        content: 响应内容，可能是多种类型

    Returns:
        str: 提取的文本内容
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # 处理内容块列表
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else ""
    if content is None:
        return ""
    return str(content)


def _format_conversation(messages: list[SuggestionMessage]) -> str:
    """将消息列表格式化为对话文本

    为什么这样设计：
    - 转换为易读的对话格式
    - 统一role名称（user/human->User，assistant/ai->Assistant）
    - 去除多余空格

    设计考虑：
    - 支持多种role格式
    - 保持简洁，只包含必要信息
    - 每条消息一行，便于LLM理解

    Args:
        messages: 消息列表

    Returns:
        str: 格式化的对话文本
    """
    parts: list[str] = []
    for m in messages:
        role = m.role.strip().lower()
        # 统一role名称
        if role in ("user", "human"):
            parts.append(f"User: {m.content.strip()}")
        elif role in ("assistant", "ai"):
            parts.append(f"Assistant: {m.content.strip()}")
        else:
            parts.append(f"{m.role}: {m.content.strip()}")
    return "\n".join(parts).strip()


@router.post(
    "/threads/{thread_id}/suggestions",
    response_model=SuggestionsResponse,
    summary="生成后续问题",
    description="基于最近的对话上下文生成用户可能询问的后续问题",
)
async def generate_suggestions(thread_id: str, request: SuggestionsRequest) -> SuggestionsResponse:
    """生成后续问题建议

    设计流程：
    1. 验证输入：检查消息列表
    2. 格式化对话：转换为LLM易读的格式
    3. 构建提示：明确要求JSON数组格式
    4. 调用模型：生成建议
    5. 解析结果：提取JSON数组
    6. 清理数据：移除换行符，限制数量

    错误处理：
    - 空消息列表：返回空建议
    - 解析失败：返回空建议（不报错）
    - 模型错误：记录日志，返回空建议

    为什么这样设计错误处理：
    - 建议是辅助功能，不应影响主流程
    - 降级策略：失败时返回空列表，前端可以处理
    - 日志记录：便于排查问题

    Args:
        thread_id: 线程ID（用于日志记录）
        request: 包含对话历史和生成参数的请求

    Returns:
        SuggestionsResponse: 生成的建议列表
    """
    # 边界情况：无消息时返回空列表
    if not request.messages:
        return SuggestionsResponse(suggestions=[])

    n = request.n
    conversation = _format_conversation(request.messages)
    if not conversation:
        return SuggestionsResponse(suggestions=[])

    # 构建提示
    # 为什么这样设计提示：
    # 1. 明确角色：帮助用户继续对话
    # 2. 明确数量：EXACTLY n个问题
    # 3. 质量要求：相关、简洁、同语言
    # 4. 格式要求：JSON数组，无额外文本
    prompt = (
        "You are generating follow-up questions to help the user continue the conversation.\n"
        f"Based on the conversation below, produce EXACTLY {n} short questions the user might ask next.\n"
        "Requirements:\n"
        "- Questions must be relevant to the conversation.\n"
        "- Questions must be written in the same language as the user.\n"
        "- Keep each question concise (ideally <= 20 words / <= 40 Chinese characters).\n"
        "- Do NOT include numbering, markdown, or any extra text.\n"
        "- Output MUST be a JSON array of strings only.\n\n"
        "Conversation:\n"
        f"{conversation}\n"
    )

    try:
        # 创建模型（禁用思考模式以提高速度）
        model = create_chat_model(name=request.model_name, thinking_enabled=False)
        response = model.invoke(prompt)
        raw = _extract_response_text(response.content)
        # 解析JSON数组
        suggestions = _parse_json_string_list(raw) or []
        # 清理数据：移除换行符，限制数量
        cleaned = [s.replace("\n", " ").strip() for s in suggestions if s.strip()]
        cleaned = cleaned[:n]
        return SuggestionsResponse(suggestions=cleaned)
    except Exception as exc:
        # 记录错误但不抛异常，返回空建议
        logger.exception("Failed to generate suggestions: thread_id=%s err=%s", thread_id, exc)
        return SuggestionsResponse(suggestions=[])
