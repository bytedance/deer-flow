"""内存 模块 for DeerFlow.

This 模块 provides a global 内存 mechanism that:
- Stores 用户 context and conversation history in 内存.json
- Uses LLM to summarize and extract facts from conversations
- Injects relevant 内存 into 系统 prompts for personalized responses
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
from deerflow.agents.memory.updater import (
    MemoryUpdater,
    get_memory_data,
    reload_memory_data,
    update_memory_from_conversation,
)

__all__ = [
    #    提示词 utilities


    "MEMORY_UPDATE_PROMPT",
    "FACT_EXTRACTION_PROMPT",
    "format_memory_for_injection",
    "format_conversation_for_update",
    #    Queue


    "ConversationContext",
    "MemoryUpdateQueue",
    "get_memory_queue",
    "reset_memory_queue",
    #    Updater


    "MemoryUpdater",
    "get_memory_data",
    "reload_memory_data",
    "update_memory_from_conversation",
]
