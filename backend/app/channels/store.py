"""
频道存储 — 将IM对话映射持久化到DeerFlow线程

===================
设计思路说明
===================

**为什么需要持久化存储**：
1. IM平台使用chat_id标识对话，DeerFlow使用thread_id标识线程
2. 需要维护这两者之间的映射关系，确保同一IM对话复用同一DeerFlow线程
3. 持久化后重启服务仍能保持会话连续性

**核心设计模式**：
- 单例模式：全局共享一个存储实例
- 线程安全：使用threading.Lock保证并发安全
- 原子写入：通过临时文件+重命名保证写入不损坏数据

**为什么使用JSON文件存储**：
- 简单可靠：无需额外依赖，易于调试
- 原子性：通过tempfile+replace实现原子写入
- 可扩展：生产环境可轻松替换为数据库

**数据结构设计**：
- 键格式："{channel_name}:{chat_id}" 或 "{channel_name}:{chat_id}:{topic_id}"
- topic_id用于支持群聊中的多线程（如Slack的thread功能）
"""

from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ChannelStore:
    """
    IM对话到DeerFlow线程映射的持久化存储

    ===================
    设计思路说明
    ===================

    **核心职责**：
    维护IM平台对话与DeerFlow线程之间的映射关系，支持：
    - 私聊：每个chat_id对应一个thread_id
    - 群聊：每个topic_id（子线程）对应一个thread_id

    **为什么这样设计**：
    1. **分层键设计**：channel:chat_id 或 channel:chat_id:topic_id
       - 支持不同频道的隔离
       - 支持群聊中的多线程
    2. **保留创建时间**：created_at字段不更新，便于追踪会话起源
    3. **原子写入**：使用tempfile+replace保证数据完整性

    **数据布局（磁盘）**::
        {
            "<channel_name>:<chat_id>": {
                "thread_id": "<uuid>",
                "user_id": "<platform_user>",
                "created_at": 1700000000.0,
                "updated_at": 1700000000.0
            },
            "<channel_name>:<chat_id>:<topic_id>": {
                ...
            }
        }

    **为什么记录user_id**：
    - 便于追踪哪个用户创建了会话
    - 支持按用户维度的统计和管理
    - 未来可扩展为用户级别的权限控制

    **生产环境升级路径**：
    当并发量增大时，可替换为：
    - SQLite：轻量级关系数据库
    - Redis：高性能KV存储
    - PostgreSQL：企业级关系数据库
    """

    def __init__(self, path: str | Path | None = None) -> None:
        """
        初始化频道存储

        **参数说明**：
        - path: 存储文件路径，默认为{base_dir}/channels/store.json

        **为什么这样设计**：
        - 自动创建父目录：简化部署流程
        - 默认路径标准化：遵循项目目录结构
        - 立即加载数据：启动时恢复所有映射关系
        """
        if path is None:
            from deerflow.config.paths import get_paths

            path = Path(get_paths().base_dir) / "channels" / "store.json"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = self._load()
        self._lock = threading.Lock()

    # -- 持久化操作 ---------------------------------------------------------

    def _load(self) -> dict[str, dict[str, Any]]:
        """
        从磁盘加载数据

        **为什么需要错误处理**：
        - JSON损坏时不应该导致服务崩溃
        - 给出警告后重新开始是合理的降级策略

        **返回值**：
        - 成功：返回解析后的字典
        - 失败：返回空字典，重新开始
        """
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("Corrupt channel store at %s, starting fresh", self._path)
        return {}

    def _save(self) -> None:
        """
        原子性地保存数据到磁盘

        **为什么使用临时文件+重命名**：
        1. **原子性**：文件系统保证rename是原子操作
        2. **防止损坏**：写入过程中不会影响原文件
        3. **异常安全**：任何异常都会清理临时文件

        **实现细节**：
        - 使用tempfile创建临时文件
        - 写入完成后用replace()原子替换原文件
        - 任何异常都会清理临时文件
        """
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
        )
        try:
            json.dump(self._data, fd, indent=2)
            fd.close()
            Path(fd.name).replace(self._path)
        except BaseException:
            fd.close()
            Path(fd.name).unlink(missing_ok=True)
            raise

    # -- 键管理辅助方法 -----------------------------------------------------

    @staticmethod
    def _key(channel_name: str, chat_id: str, topic_id: str | None = None) -> str:
        """
        生成存储键

        **为什么这样设计键格式**：
        1. **冒号分隔**：简单且易于解析
        2. **分层结构**：channel -> chat -> topic
        3. **可选topic**：私聊不需要topic_id

        **参数说明**：
        - channel_name: 频道名称（feishu/slack/telegram）
        - chat_id: IM平台的对话ID
        - topic_id: 可选，群聊中的子线程ID

        **返回值**：
        - 私聊："channel:chat_id"
        - 群聊："channel:chat_id:topic_id"
        """
        if topic_id:
            return f"{channel_name}:{chat_id}:{topic_id}"
        return f"{channel_name}:{chat_id}"

    # -- 公共API ------------------------------------------------------------

    def get_thread_id(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> str | None:
        """
        查找给定IM对话/主题的DeerFlow thread_id

        **为什么需要topic_id参数**：
        - 在群聊中，不同的thread可能需要不同的DeerFlow线程
        - 例如Slack的thread功能，每个thread是一个独立对话

        **参数说明**：
        - channel_name: 频道名称
        - chat_id: IM平台的对话ID
        - topic_id: 可选，群聊中的子线程ID

        **返回值**：
        - 找到：返回thread_id
        - 未找到：返回None
        """
        entry = self._data.get(self._key(channel_name, chat_id, topic_id))
        return entry["thread_id"] if entry else None

    def set_thread_id(
        self,
        channel_name: str,
        chat_id: str,
        thread_id: str,
        *,
        topic_id: str | None = None,
        user_id: str = "",
    ) -> None:
        """
        创建或更新IM对话/主题的映射

        **为什么保留created_at**：
        - created_at表示会话首次创建时间
        - updated_at表示最后更新时间
        - 两者分离便于追踪会话历史

        **为什么需要线程锁**：
        - 防止并发写入导致数据竞争
        - 保证保存操作的原子性

        **参数说明**：
        - channel_name: 频道名称
        - chat_id: IM平台的对话ID
        - thread_id: DeerFlow的线程ID
        - topic_id: 可选，群聊中的子线程ID
        - user_id: 可选，创建此映射的用户ID

        **实现细节**：
        - 如果映射已存在，保留原created_at
        - 每次更新都刷新updated_at时间戳
        """
        with self._lock:
            key = self._key(channel_name, chat_id, topic_id)
            now = time.time()
            existing = self._data.get(key)
            self._data[key] = {
                "thread_id": thread_id,
                "user_id": user_id,
                "created_at": existing["created_at"] if existing else now,
                "updated_at": now,
            }
            self._save()

    def remove(self, channel_name: str, chat_id: str, topic_id: str | None = None) -> bool:
        """
        删除映射

        **为什么提供两种删除模式**：
        1. **精确删除**：topic_id指定时，只删除该thread的映射
        2. **批量删除**：topic_id为空时，删除该chat_id的所有映射

        **使用场景**：
        - 精确删除：用户删除某个特定thread
        - 批量删除：用户离开群聊，删除所有相关映射

        **参数说明**：
        - channel_name: 频道名称
        - chat_id: IM平台的对话ID
        - topic_id: 可选，指定要删除的子线程ID

        **返回值**：
        - True: 至少删除了一个映射
        - False: 没有找到匹配的映射
        """
        with self._lock:
            # 精确删除：删除特定的conversation/topic映射
            if topic_id is not None:
                key = self._key(channel_name, chat_id, topic_id)
                if key in self._data:
                    del self._data[key]
                    self._save()
                    return True
                return False

            # 批量删除：删除该channel/chat_id的所有映射
            # 包括基础映射和所有topic特定的映射
            prefix = self._key(channel_name, chat_id)
            keys_to_delete = [k for k in self._data if k == prefix or k.startswith(prefix + ":")]
            if not keys_to_delete:
                return False

            for k in keys_to_delete:
                del self._data[k]
            self._save()
            return True

    def list_entries(self, channel_name: str | None = None) -> list[dict[str, Any]]:
        """
        列出所有存储的映射，可选择按频道过滤

        **为什么需要这个方法**：
        - 调试时查看所有映射关系
        - 管理工具中展示会话列表
        - 数据迁移时的导出功能

        **参数说明**：
        - channel_name: 可选，按频道名称过滤

        **返回值**：
        - 映射条目列表，每项包含channel_name, chat_id, thread_id等
        """
        results = []
        for key, entry in self._data.items():
            parts = key.split(":", 2)
            ch = parts[0]
            chat = parts[1] if len(parts) > 1 else ""
            topic = parts[2] if len(parts) > 2 else None
            if channel_name and ch != channel_name:
                continue
            item: dict[str, Any] = {"channel_name": ch, "chat_id": chat, **entry}
            if topic is not None:
                item["topic_id"] = topic
            results.append(item)
        return results
