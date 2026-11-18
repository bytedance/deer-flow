"""Model/tool boundaries for the real Gateway batch-owner recovery test."""

import json
import os
import time
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _record(name, item, runtime):
    record = {"tool": name, "item": item, "role": runtime.context.get("user_role"), "user_id": runtime.context.get("user_id"), "pid": os.getpid()}
    path = Path(os.environ["BATCH_OWNER_PROBE_DIR"]) / "calls.jsonl"
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(record) + "\n")
    return "Completed " + name


@tool
def owner_normal(item: str, runtime: ToolRuntime) -> str:
    """Record an operation available to every configured role."""
    return _record("normal", item, runtime)


@tool
def owner_admin(item: str, runtime: ToolRuntime) -> str:
    """Record an operation restricted by the host RBAC policy to administrators."""
    return _record("admin", item, runtime)


class OwnerModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-batch-owner"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content="Done")
        elif any(isinstance(message, HumanMessage) and "OWNER_CHILD" in str(message.content) for message in messages):
            root = Path(os.environ["BATCH_OWNER_PROBE_DIR"])
            item = "first" if any("OWNER_CHILD:first" in str(message.content) for message in messages) else "second"
            (root / f"reached-{item}").write_text(str(os.getpid()), encoding="utf-8")
            deadline = time.monotonic() + 60
            while item == "first" and (root / "hold").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Batch owner test barrier not released")
                time.sleep(0.02)
            answer = AIMessage(content="", tool_calls=[{"name": name, "args": {"item": item}, "id": name, "type": "tool_call"} for name in ("owner_admin", "owner_normal")])
        else:
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "batch_task",
                        "args": {"title": "Owner recovery", "subagent_type": "general-purpose", "items": [{"key": key, "prompt": f"OWNER_CHILD:{key}: run both configured observations"} for key in ("first", "second")]},
                        "id": "batch",
                        "type": "tool_call",
                    }
                ],
            )
        return ChatResult(generations=[ChatGeneration(message=answer)])
