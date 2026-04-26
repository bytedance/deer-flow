"""
记忆模块初始化文件

===================
设计思路说明
===================

**为什么需要这个模块**：
1. 作为记忆系统的统一入口，导出所有公共API
2. 组织记忆系统的功能模块（提示词、队列、存储、更新器）
3. 提供清晰的模块结构和导入接口

**核心设计模式**：
- 门面模式：提供统一的导入接口
- 模块化组织：按功能划分子模块
- 单一职责：每个子模块负责特定功能

**为什么这样设计**：
- **易于使用**：从一个位置导入所有记忆功能
- **清晰结构**：明确每个模块的职责
- **便于维护**：功能模块独立，便于修改和测试

**模块结构**：
- prompt.py：提示词模板和格式化函数
- queue.py：记忆更新队列和防抖机制
- storage.py：记忆存储抽象和文件存储实现
- updater.py：记忆更新逻辑和数据管理

**公共API说明**：
- MEMORY_UPDATE_PROMPT：记忆更新提示词模板
- FACT_EXTRACTION_PROMPT：事实提取提示词模板
- format_memory_for_injection：格式化记忆用于注入
- format_conversation_for_update：格式化对话用于更新
- ConversationContext：对话上下文数据类
- MemoryUpdateQueue：记忆更新队列
- MemoryStorage：记忆存储抽象
- FileMemoryStorage：文件存储实现
- MemoryUpdater：记忆更新器
- 各种工具函数：get_*、reload_*、update_*等
"""

from deerflow.agents.memory.prompt import (
    FACT_EXTRACTION_PROMPT,
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
    format_memory_for_injection,
)
from deerflow.agents.memory.queue import (
    ConversationContext,
    MemoryUpdateQueue,
    get_memory_queue,
    reset_memory_queue,
)
from deerflow.agents.memory.storage import (
    FileMemoryStorage,
    MemoryStorage,
    get_memory_storage,
)
from deerflow.agents.memory.updater import (
    MemoryUpdater,
    clear_memory_data,
    delete_memory_fact,
    get_memory_data,
    reload_memory_data,
    update_memory_from_conversation,
)

__all__ = [
    # 提示词工具
    "MEMORY_UPDATE_PROMPT",
    "FACT_EXTRACTION_PROMPT",
    "format_memory_for_injection",
    "format_conversation_for_update",
    # 队列
    "ConversationContext",
    "MemoryUpdateQueue",
    "get_memory_queue",
    "reset_memory_queue",
    # 存储
    "MemoryStorage",
    "FileMemoryStorage",
    "get_memory_storage",
    # 更新器
    "MemoryUpdater",
    "clear_memory_data",
    "delete_memory_fact",
    "get_memory_data",
    "reload_memory_data",
    "update_memory_from_conversation",
]
