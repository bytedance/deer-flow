"""Test-only Gateway entrypoint: real host, deterministic model and fault barriers.

Never deployed or imported by production. Barriers only delay real calls; they do
not replace auth, AgentRuns, run admission, checkpointing, Redis or workflow storage.
"""

import asyncio
import json
import os
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

EVIDENCE = "immutable acceptance evidence\n版本一\n"


class AcceptanceModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "workflow-acceptance-synthetic"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        human = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
        if "HOLD_MODEL" in str(human.content):
            import time

            while (Path(os.environ["WORKFLOW_FAULT_DIR"]) / "hold_model").exists():
                time.sleep(0.02)
        if "CREATE_EVIDENCE" in str(human.content) and not any(isinstance(m, ToolMessage) for m in messages):
            answer = AIMessage(content="", tool_calls=[{"name": "write_file", "args": {"path": "/mnt/user-data/outputs/evidence.txt", "content": EVIDENCE}, "id": "evidence-write", "type": "tool_call"}])
        elif "CREATE_EVIDENCE" in str(human.content) and not any(isinstance(m, ToolMessage) and m.name == "present_files" for m in messages):
            answer = AIMessage(content="", tool_calls=[{"name": "present_files", "args": {"filepaths": ["/mnt/user-data/outputs/evidence.txt"]}, "id": "evidence-present", "type": "tool_call"}])
        else:
            content = str(human.content)
            if "--- BEGIN USER INPUT ---\n" in content:
                content = content.split("--- BEGIN USER INPUT ---\n", 1)[1].split("\n--- END USER INPUT ---", 1)[0]
            answer = AIMessage(content=json.dumps({"echo": content}))
        return ChatResult(generations=[ChatGeneration(message=answer)])


async def barrier(boundary, record=None):
    root = Path(os.environ["WORKFLOW_FAULT_DIR"])

    def armed():
        arm = root / "arm.json"
        if not arm.exists():
            return False
        data = json.loads(arm.read_text())
        if data["boundary"] != boundary:
            return False
        arm.unlink()
        (root / "reached.json").write_text(json.dumps({"boundary": boundary, "run_id": record.get("id") if record else None}))
        return True

    if await asyncio.to_thread(armed):
        while not await asyncio.to_thread((root / "release").exists):
            await asyncio.sleep(0.02)


def install_barriers():
    from deerflow_extension_workflows.postgres import PostgresStore

    from app.gateway.extension_agent_runs import _BoundAgentRuns

    original_put = PostgresStore.put

    def put(self, owner, record):
        if any(s["status"] == "completed" for s in record["steps"]):
            asyncio.run(barrier("result_before", record))
        result = original_put(self, owner, record)
        boundary = None
        if any(s["status"] == "completed" for s in record["steps"]):
            boundary = "result"
        if any(c["status"] == "approved" for c in record["checkpoints"]):
            boundary = "approval"
        if record["status"] == "cancelling":
            boundary = "cancelling"
        if boundary:
            asyncio.run(barrier(boundary, record))
        return result

    PostgresStore.put = put
    original_capture = PostgresStore.capture_artifact

    def capture(self, *args, **kwargs):
        asyncio.run(barrier("capture"))
        try:
            return original_capture(self, *args, **kwargs)
        except Exception as exc:
            (Path(os.environ["WORKFLOW_FAULT_DIR"]) / "capture_error").write_text(type(exc).__name__)
            raise

    PostgresStore.capture_artifact = capture
    original_start = _BoundAgentRuns.start

    async def start(self, **kwargs):
        await barrier("before_admission")
        try:
            result = await original_start(self, **kwargs)
        except Exception as exc:
            await asyncio.to_thread((Path(os.environ["WORKFLOW_FAULT_DIR"]) / "admission_error").write_text, type(exc).__name__)
            raise
        await barrier("admission")
        return result

    _BoundAgentRuns.start = start


if __name__ == "__main__":
    import sys

    import uvicorn

    install_barriers()
    uvicorn.run("app.gateway.app:app", host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
