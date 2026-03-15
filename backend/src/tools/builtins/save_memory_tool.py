"""Tool for saving facts directly to long-term memory."""

import uuid
from datetime import datetime
from typing import Annotated

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState


@tool("save_memory_fact", parse_docstring=True)
def save_memory_fact_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    content: str,
    category: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
    confidence: float = 1.0,
) -> Command:
    """Save a specific fact to long-term memory for use in future conversations.

    Use this tool ONLY when the user explicitly asks to remember something or save
    information to memory. Do NOT use write_file to simulate memory saving.

    Args:
        content: The fact to remember as a clear declarative statement, e.g. "Lives in Thailand".
        category: Category - one of: preference, knowledge, context, behavior, goal.
        confidence: Confidence score 0.0 to 1.0 (default 1.0 for explicitly stated facts).
    """
    try:
        from src.agents.memory.updater import _save_memory_to_file, get_memory_data
        from src.config.memory_config import get_memory_config

        config = get_memory_config()
        if not config.enabled:
            return Command(
                update={"messages": [ToolMessage("Memory is disabled in configuration.", tool_call_id=tool_call_id)]},
            )

        valid_categories = {"preference", "knowledge", "context", "behavior", "goal"}
        if category not in valid_categories:
            category = "context"

        confidence = max(0.0, min(1.0, float(confidence)))

        thread_id = runtime.context.get("thread_id", "unknown")
        now = datetime.utcnow().isoformat() + "Z"

        memory_data = get_memory_data()

        if "facts" not in memory_data:
            memory_data["facts"] = []

        fact_entry = {
            "id": f"fact_{uuid.uuid4().hex[:8]}",
            "content": content,
            "category": category,
            "confidence": confidence,
            "createdAt": now,
            "source": thread_id,
        }

        memory_data["facts"].append(fact_entry)

        # Enforce max facts limit
        if len(memory_data["facts"]) > config.max_facts:
            memory_data["facts"] = sorted(
                memory_data["facts"],
                key=lambda f: f.get("confidence", 0),
                reverse=True,
            )[: config.max_facts]

        success = _save_memory_to_file(memory_data)

        if success:
            return Command(
                update={"messages": [ToolMessage(f"Saved to memory: {content}", tool_call_id=tool_call_id)]},
            )
        else:
            return Command(
                update={"messages": [ToolMessage("Failed to save to memory.", tool_call_id=tool_call_id)]},
            )
    except Exception as e:
        return Command(
            update={"messages": [ToolMessage(f"Error saving to memory: {e}", tool_call_id=tool_call_id)]},
        )
