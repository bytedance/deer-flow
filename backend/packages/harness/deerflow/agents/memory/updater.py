"""记忆更新器 - 用于读取、写入和更新记忆数据

===================
设计思路说明
===================

**核心职责**：
提供记忆数据的CRUD操作和基于对话的自动更新：
1. 手动操作：创建、删除、更新记忆事实
2. 自动更新：基于对话内容使用LLM更新记忆
3. 数据清洗：移除会话相关的上传文件引用

**为什么需要这个模块**：
1. **记忆持久化**：将对话中的重要信息长期保存
2. **智能更新**：使用LLM从对话中提取和更新记忆
3. **数据一致性**：确保存储的数据符合格式标准
4. **去重优化**：避免重复的事实，限制最大数量

**设计决策**：
- 使用LLM进行智能更新：比规则更灵活，能理解上下文
- 置信度阈值过滤：只保留高可信度的事实
- 自动清洗上传引用：上传文件是会话作用域的，不应持久化
- 支持per-agent记忆：不同代理可以有独立的记忆

**架构说明**：
- 存储层抽象：通过get_memory_storage()支持不同存储后端
- 事务性操作：读取-修改-写入的原子性
- 错误处理：失败时返回False，不中断主流程
"""

import json
import logging
import math
import re
import uuid
from datetime import datetime
from typing import Any

from deerflow.agents.memory.prompt import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
)
from deerflow.agents.memory.storage import create_empty_memory, get_memory_storage
from deerflow.config.memory_config import get_memory_config
from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)


def _create_empty_memory() -> dict[str, Any]:
    """创建空记忆结构的向后兼容包装器

    为什么需要包装器：
    - 提供统一的API入口
    - 隔离存储层变化
    - 便于未来切换存储实现

    Returns:
        空的记忆数据结构
    """
    return create_empty_memory()


def _save_memory_to_file(memory_data: dict[str, Any], agent_name: str | None = None) -> bool:
    """保存记忆数据到配置的存储路径的向后兼容包装器

    为什么使用包装器：
    - 统一保存逻辑
    - 支持per-agent记忆
    - 隔离存储实现细节

    Args:
        memory_data: 要保存的记忆数据
        agent_name: 如果提供，保存到per-agent记忆

    Returns:
        保存是否成功
    """
    return get_memory_storage().save(memory_data, agent_name)


def get_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """通过存储提供者获取当前记忆数据

    为什么需要这个函数：
    - 统一的读取入口
    - 支持per-agent记忆隔离
    - 便于缓存和性能优化

    Args:
        agent_name: 如果提供，读取per-agent记忆

    Returns:
        当前记忆数据
    """
    return get_memory_storage().load(agent_name)


def reload_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """通过存储提供者重新加载记忆数据

    为什么需要重新加载：
    - 刷新缓存数据
    - 获取外部修改
    - 强制同步最新状态

    Args:
        agent_name: 如果提供，重新加载per-agent记忆

    Returns:
        重新加载的记忆数据
    """
    return get_memory_storage().reload(agent_name)


def import_memory_data(memory_data: dict[str, Any], agent_name: str | None = None) -> dict[str, Any]:
    """持久化导入的记忆数据

    为什么需要导入功能：
    - 支持批量导入
    - 便于数据迁移
    - 允许手动编辑后导入

    Args:
        memory_data: 要持久化的完整记忆负载
        agent_name: 如果提供，导入到per-agent记忆

    Returns:
        存储规范化后保存的记忆数据

    Raises:
        OSError: 如果持久化导入记忆失败
    """
    storage = get_memory_storage()
    if not storage.save(memory_data, agent_name):
        raise OSError("Failed to save imported memory data")
    return storage.load(agent_name)


def clear_memory_data(agent_name: str | None = None) -> dict[str, Any]:
    """清除所有存储的记忆数据并持久化空结构

    为什么需要清除功能：
    - 用户隐私保护
    - 重置记忆状态
    - 测试和调试

    Args:
        agent_name: 如果提供，清除per-agent记忆

    Returns:
        空的记忆数据结构

    Raises:
        OSError: 如果保存清除后的记忆数据失败
    """
    cleared_memory = create_empty_memory()
    if not _save_memory_to_file(cleared_memory, agent_name):
        raise OSError("Failed to save cleared memory data")
    return cleared_memory


def _validate_confidence(confidence: float) -> float:
    """验证持久化事实的置信度，确保存储的JSON保持标准兼容

    为什么需要验证：
    - 确保数据在有效范围内
    - 防止NaN/Infinity导致JSON序列化失败
    - 维护数据质量

    Args:
        confidence: 要验证的置信度值

    Returns:
        验证后的置信度值

    Raises:
        ValueError: 如果置信度无效
    """
    if not math.isfinite(confidence) or confidence < 0 or confidence > 1:
        raise ValueError("confidence")
    return confidence


def create_memory_fact(
    content: str,
    category: str = "context",
    confidence: float = 0.5,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """创建新事实并持久化更新后的记忆数据

    设计考虑：
    - 内容归一化：去除首尾空格
    - 默认类别：使用"context"作为后备
    - 时间戳：使用UTC时间
    - 唯一ID：使用UUID生成

    Args:
        content: 事实内容
        category: 事实类别（默认"context"）
        confidence: 置信度0-1（默认0.5）
        agent_name: 如果提供，添加到per-agent记忆

    Returns:
        更新后的记忆数据

    Raises:
        ValueError: 如果内容为空
        OSError: 如果保存失败
    """
    normalized_content = content.strip()
    if not normalized_content:
        raise ValueError("content")

    normalized_category = category.strip() or "context"
    validated_confidence = _validate_confidence(confidence)
    now = datetime.utcnow().isoformat() + "Z"
    memory_data = get_memory_data(agent_name)
    updated_memory = dict(memory_data)
    facts = list(memory_data.get("facts", []))
    facts.append(
        {
            "id": f"fact_{uuid.uuid4().hex[:8]}",
            "content": normalized_content,
            "category": normalized_category,
            "confidence": validated_confidence,
            "createdAt": now,
            "source": "manual",
        }
    )
    updated_memory["facts"] = facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError("Failed to save memory data after creating fact")

    return updated_memory


def delete_memory_fact(fact_id: str, agent_name: str | None = None) -> dict[str, Any]:
    """通过ID删除事实并持久化更新后的记忆数据

    设计考虑：
    - 检查是否存在：删除前验证事实存在
    - 不可变更新：创建新列表而非修改原列表
    - 原子操作：删除和保存在同一事务中

    Args:
        fact_id: 要删除的事实ID
        agent_name: 如果提供，从per-agent记忆删除

    Returns:
        更新后的记忆数据

    Raises:
        KeyError: 如果事实不存在
        OSError: 如果保存失败
    """
    memory_data = get_memory_data(agent_name)
    facts = memory_data.get("facts", [])
    updated_facts = [fact for fact in facts if fact.get("id") != fact_id]
    if len(updated_facts) == len(facts):
        raise KeyError(fact_id)

    updated_memory = dict(memory_data)
    updated_memory["facts"] = updated_facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError(f"Failed to save memory data after deleting fact '{fact_id}'")

    return updated_memory


def update_memory_fact(
    fact_id: str,
    content: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
    agent_name: str | None = None,
) -> dict[str, Any]:
    """更新现有事实并持久化更新后的记忆数据

    设计考虑：
    - 部分更新：只更新提供的字段
    - 验证输入：更新前验证新值
    - 保持ID：不修改事实ID

    Args:
        fact_id: 要更新的事实ID
        content: 新内容（可选）
        category: 新类别（可选）
        confidence: 新置信度（可选）
        agent_name: 如果提供，更新per-agent记忆

    Returns:
        更新后的记忆数据

    Raises:
        KeyError: 如果事实不存在
        ValueError: 如果新值无效
        OSError: 如果保存失败
    """
    memory_data = get_memory_data(agent_name)
    updated_memory = dict(memory_data)
    updated_facts: list[dict[str, Any]] = []
    found = False

    for fact in memory_data.get("facts", []):
        if fact.get("id") == fact_id:
            found = True
            updated_fact = dict(fact)
            if content is not None:
                normalized_content = content.strip()
                if not normalized_content:
                    raise ValueError("content")
                updated_fact["content"] = normalized_content
            if category is not None:
                updated_fact["category"] = category.strip() or "context"
            if confidence is not None:
                updated_fact["confidence"] = _validate_confidence(confidence)
            updated_facts.append(updated_fact)
        else:
            updated_facts.append(fact)

    if not found:
        raise KeyError(fact_id)

    updated_memory["facts"] = updated_facts

    if not _save_memory_to_file(updated_memory, agent_name):
        raise OSError(f"Failed to save memory data after updating fact '{fact_id}'")

    return updated_memory


def _extract_text(content: Any) -> str:
    """从LLM响应内容中提取纯文本（支持字符串或内容块列表）

    为什么需要这个函数：
    - 现代LLM可能返回结构化内容（列表格式）
    - 直接使用str()会生成Python repr而非实际文本
    - 破坏下游的JSON解析

    设计考虑：
    - 字符串块：无分隔符连接，避免破坏分块JSON
    - 字典块：作为完整文本块处理，用换行符连接
    - 兼容性：同时支持旧式字符串和新式列表格式

    Args:
        content: LLM响应内容（字符串或列表）

    Returns:
        提取的纯文本
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces: list[str] = []
        pending_str_parts: list[str] = []

        def flush_pending_str_parts() -> None:
            """刷新待处理的字符串部分"""
            if pending_str_parts:
                pieces.append("".join(pending_str_parts))
                pending_str_parts.clear()

        for block in content:
            if isinstance(block, str):
                pending_str_parts.append(block)
            elif isinstance(block, dict):
                flush_pending_str_parts()
                text_val = block.get("text")
                if isinstance(text_val, str):
                    pieces.append(text_val)

        flush_pending_str_parts()
        return "\n".join(pieces)
    return str(content)


# 匹配描述文件上传*事件*而非一般文件相关工作的句子
# 故意保持狭窄，避免删除合法事实，如"用户使用CSV文件"或"偏好PDF导出"
_UPLOAD_SENTENCE_RE = re.compile(
    r"[^.!?]*\b(?:"
    r"upload(?:ed|ing)?(?:\s+\w+){0,3}\s+(?:file|files?|document|documents?|attachment|attachments?)"
    r"|file\s+upload"
    r"|/mnt/user-data/uploads/"
    r"|<uploaded_files>"
    r")[^.!?]*[.!?]?\s*",
    re.IGNORECASE,
)


def _strip_upload_mentions_from_memory(memory_data: dict[str, Any]) -> dict[str, Any]:
    """从所有记忆摘要和事实中删除关于文件上传的句子

    为什么需要这个函数：
    - 上传的文件是会话作用域的
    - 在长期记忆中持久化上传事件会导致代理在未来会话中搜索不存在的文件
    - 避免记忆污染和误导

    设计考虑：
    - 精确匹配：只匹配明确的上传事件
    - 保留合法事实：不删除一般性的文件工作描述
    - 全局清理：处理摘要和事实两部分

    Args:
        memory_data: 记忆数据

    Returns:
        清理后的记忆数据
    """
    # 清理user/history部分的摘要
    for section in ("user", "history"):
        section_data = memory_data.get(section, {})
        for _key, val in section_data.items():
            if isinstance(val, dict) and "summary" in val:
                cleaned = _UPLOAD_SENTENCE_RE.sub("", val["summary"]).strip()
                cleaned = re.sub(r"  +", " ", cleaned)
                val["summary"] = cleaned

    # 同时删除描述上传事件的任何事实
    facts = memory_data.get("facts", [])
    if facts:
        memory_data["facts"] = [f for f in facts if not _UPLOAD_SENTENCE_RE.search(f.get("content", ""))]

    return memory_data


def _fact_content_key(content: Any) -> str | None:
    """生成事实内容的规范化键，用于去重

    为什么需要这个函数：
    - 提供一致的内容比较方式
    - 处理空值和空格
    - 支持高效的去重检查

    Args:
        content: 事实内容

    Returns:
        规范化的内容键，如果内容无效则返回None
    """
    if not isinstance(content, str):
        return None
    stripped = content.strip()
    if not stripped:
        return None
    return stripped


class MemoryUpdater:
    """使用LLM基于对话上下文更新记忆

    设计思路：
    - LLM驱动：比规则更灵活，能理解上下文
    - 结构化输出：使用JSON格式确保可解析
    - 事务性：要么全部成功，要么全部失败
    - 智能过滤：根据置信度和去重决定是否添加
    """

    def __init__(self, model_name: str | None = None):
        """初始化记忆更新器

        Args:
            model_name: 可选的模型名称。如果为None，使用配置或默认值
        """
        self._model_name = model_name

    def _get_model(self):
        """获取用于记忆更新的模型

        为什么禁用思考模式：
        - 记忆更新不需要复杂推理
        - 提高响应速度
        - 节省token成本

        Returns:
            配置的聊天模型实例
        """
        config = get_memory_config()
        model_name = self._model_name or config.model_name
        return create_chat_model(name=model_name, thinking_enabled=False)

    def update_memory(self, messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
        """基于对话消息更新记忆

        工作流程：
        1. 检查配置和消息
        2. 格式化对话为文本
        3. 构建提示词
        4. 调用LLM生成更新
        5. 解析JSON响应
        6. 应用更新
        7. 清洗上传引用
        8. 持久化结果

        Args:
            messages: 对话消息列表
            thread_id: 可选的线程ID用于跟踪来源
            agent_name: 如果提供，更新per-agent记忆

        Returns:
            更新是否成功
        """
        config = get_memory_config()
        if not config.enabled:
            return False

        if not messages:
            return False

        try:
            # 获取当前记忆
            current_memory = get_memory_data(agent_name)

            # 格式化对话用于提示
            conversation_text = format_conversation_for_update(messages)

            if not conversation_text.strip():
                return False

            # 构建提示
            prompt = MEMORY_UPDATE_PROMPT.format(
                current_memory=json.dumps(current_memory, indent=2),
                conversation=conversation_text,
            )

            # 调用LLM
            model = self._get_model()
            response = model.invoke(prompt)
            response_text = _extract_text(response.content).strip()

            # 解析响应
            # 如果存在，删除markdown代码块
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            update_data = json.loads(response_text)

            # 应用更新
            updated_memory = self._apply_updates(current_memory, update_data, thread_id)

            # 在保存前从所有摘要中删除文件上传提及
            # 上传的文件是会话作用域的，在未来会话中不存在
            # 因此在长期记忆中记录上传事件会导致代理在后续对话中
            # 尝试（并失败）定位这些文件
            updated_memory = _strip_upload_mentions_from_memory(updated_memory)

            # 保存
            return get_memory_storage().save(updated_memory, agent_name)

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse LLM response for memory update: %s", e)
            return False
        except Exception as e:
            logger.exception("Memory update failed: %s", e)
            return False

    def _apply_updates(
        self,
        current_memory: dict[str, Any],
        update_data: dict[str, Any],
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """将LLM生成的更新应用到记忆

        更新策略：
        1. 更新用户部分：workContext, personalContext, topOfMind
        2. 更新历史部分：recentMonths, earlierContext, longTermBackground
        3. 删除标记的事实
        4. 添加新事实（带去重和置信度过滤）
        5. 强制执行最大事实限制

        Args:
            current_memory: 当前记忆数据
            update_data: 来自LLM的更新
            thread_id: 可选的线程ID用于跟踪

        Returns:
            更新后的记忆数据
        """
        config = get_memory_config()
        now = datetime.utcnow().isoformat() + "Z"

        # 更新用户部分
        user_updates = update_data.get("user", {})
        for section in ["workContext", "personalContext", "topOfMind"]:
            section_data = user_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["user"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # 更新历史部分
        history_updates = update_data.get("history", {})
        for section in ["recentMonths", "earlierContext", "longTermBackground"]:
            section_data = history_updates.get(section, {})
            if section_data.get("shouldUpdate") and section_data.get("summary"):
                current_memory["history"][section] = {
                    "summary": section_data["summary"],
                    "updatedAt": now,
                }

        # 删除事实
        facts_to_remove = set(update_data.get("factsToRemove", []))
        if facts_to_remove:
            current_memory["facts"] = [f for f in current_memory.get("facts", []) if f.get("id") not in facts_to_remove]

        # 添加新事实
        existing_fact_keys = {fact_key for fact_key in (_fact_content_key(fact.get("content")) for fact in current_memory.get("facts", [])) if fact_key is not None}
        new_facts = update_data.get("newFacts", [])
        for fact in new_facts:
            confidence = fact.get("confidence", 0.5)
            if confidence >= config.fact_confidence_threshold:
                raw_content = fact.get("content", "")
                normalized_content = raw_content.strip()
                fact_key = _fact_content_key(normalized_content)
                if fact_key is not None and fact_key in existing_fact_keys:
                    continue

                fact_entry = {
                    "id": f"fact_{uuid.uuid4().hex[:8]}",
                    "content": normalized_content,
                    "category": fact.get("category", "context"),
                    "confidence": confidence,
                    "createdAt": now,
                    "source": thread_id or "unknown",
                }
                current_memory["facts"].append(fact_entry)
                if fact_key is not None:
                    existing_fact_keys.add(fact_key)

        # 强制执行最大事实限制
        if len(current_memory["facts"]) > config.max_facts:
            # 按置信度排序并保留顶部
            current_memory["facts"] = sorted(
                current_memory["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        return current_memory


def update_memory_from_conversation(messages: list[Any], thread_id: str | None = None, agent_name: str | None = None) -> bool:
    """从对话更新记忆的便利函数

    为什么需要这个函数：
    - 简化调用接口
    - 隐藏MemoryUpdater实例化
    - 提供更简洁的API

    Args:
        messages: 对话消息列表
        thread_id: 可选的线程ID
        agent_name: 如果提供，更新per-agent记忆

    Returns:
        成功返回True，否则返回False
    """
    updater = MemoryUpdater()
    return updater.update_memory(messages, thread_id, agent_name)
