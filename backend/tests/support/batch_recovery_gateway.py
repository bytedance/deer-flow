"""Offline Gateway fixture with a real native batch and a pre-result crash gate.

Only model answers and the fault barrier are scripted. Native graph/tool execution,
batch admission, leases, result writes, recovery and HTTP reads stay in production.
"""

import asyncio
import json
import os
import sqlite3
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool


@tool(return_direct=True)
def append_record() -> str:
    """Append one record to the isolated external system, without deduplication."""
    with sqlite3.connect(Path(os.environ["BATCH_RECOVERY_FIXTURE_DIR"]) / "external.sqlite") as db:
        db.execute("CREATE TABLE IF NOT EXISTS writes (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO writes (value) VALUES ('committed side effect')")
    return "External write committed"


class RecoveryModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "offline-batch-recovery"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        human = next(message for message in reversed(messages) if isinstance(message, HumanMessage))
        prompt = str(human.content)
        if any(isinstance(message, ToolMessage) for message in messages):
            answer = AIMessage(content="Batch submitted. The requested follow-up will run after completion.")
        elif "START_BATCH" in prompt:
            answer = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "batch_task",
                        "id": "submit-recovery-batch",
                        "args": {
                            "title": "Crash recovery fixture",
                            "subagent_type": "general-purpose",
                            "items": [
                                {"key": "write", "prompt": "WRITE_RECORD using append_record"},
                                {"key": "dependent", "prompt": "DEPENDENT_FINISHED", "depends_on": ["write"]},
                            ],
                            "max_running_items": 1,
                            "continuation": "FOLLOWUP_FINISHED",
                        },
                    }
                ],
            )
        elif "WRITE_RECORD" in prompt:
            answer = AIMessage(content="", tool_calls=[{"name": "append_record", "id": "external-write", "args": {}}])
        else:
            answer = AIMessage(content="DEPENDENT_FINISHED" if "DEPENDENT_FINISHED" in prompt else "FOLLOWUP_FINISHED")
        return ChatResult(generations=[ChatGeneration(message=answer)])


def install_crash_barrier():
    from deerflow.persistence.subagent_batches import SubagentBatchRepository

    original = SubagentBatchRepository.finalize_item
    root = Path(os.environ["BATCH_RECOVERY_FIXTURE_DIR"])

    async def finalize(self, item_id, **kwargs):
        if os.environ.get("BATCH_RECOVERY_HOLD_RESULT") == "1" and kwargs.get("succeeded"):

            def reached():
                (root / "before-result.json").write_text(json.dumps({"item_id": item_id, "result": kwargs.get("result")}), encoding="utf-8")

            await asyncio.to_thread(reached)
            # A hard process kill must leave this original call unexecuted.
            await asyncio.Event().wait()
        return await original(self, item_id, **kwargs)

    SubagentBatchRepository.finalize_item = finalize


if __name__ == "__main__":
    import sys

    import uvicorn

    install_crash_barrier()
    uvicorn.run("app.gateway.app:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
