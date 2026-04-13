"""Memory module for DeerFlow.

This module provides a global memory mechanism that:
- Stores user context and conversation history in memory.json
- Uses LLM to summarize and extract facts from conversations
- Injects relevant memory into system prompts for personalized responses
"""

from deerflow.agents.memory.metrics import (
    RetrievalMetrics,
    compute_retrieval_metrics,
)
from deerflow.agents.memory.prompt import (
    FACT_EXTRACTION_PROMPT,
    MEMORY_UPDATE_PROMPT,
    build_memory_injection_result,
    format_conversation_for_update,
    format_memory_for_injection,
)
from deerflow.agents.memory.queue import (
    ConversationContext,
    MemoryUpdateQueue,
    get_memory_queue,
    reset_memory_queue,
)
from deerflow.agents.memory.retrieval_trace import (
    InjectionResult,
    RetrievalTrace,
    emit_retrieval_trace,
    resolve_trace_path,
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
    # Prompt utilities
    "MEMORY_UPDATE_PROMPT",
    "FACT_EXTRACTION_PROMPT",
    "build_memory_injection_result",
    "format_memory_for_injection",
    "format_conversation_for_update",
    "InjectionResult",
    "RetrievalTrace",
    "emit_retrieval_trace",
    "resolve_trace_path",
    # Metrics
    "RetrievalMetrics",
    "compute_retrieval_metrics",
    # Queue
    "ConversationContext",
    "MemoryUpdateQueue",
    "get_memory_queue",
    "reset_memory_queue",
    # Storage
    "MemoryStorage",
    "FileMemoryStorage",
    "get_memory_storage",
    # Updater
    "MemoryUpdater",
    "clear_memory_data",
    "delete_memory_fact",
    "get_memory_data",
    "reload_memory_data",
    "update_memory_from_conversation",
]
