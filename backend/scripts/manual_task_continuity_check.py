"""Manual live-model recovery check using production middleware and tools.

Run from backend with --endpoints /path/to/private.json --output /tmp/check.json.
The private file contains llm_base, llm_model and optional llm_key. No network
calls occur on import. Uses synthetic history only; no endpoint or response body
is retained in the public result. This is a controlled integration check, not a
production success-rate benchmark. The summary prompt intentionally omits codes
so successful recovery must exercise source recall.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver

from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware
from deerflow.agents.middlewares.summarization_middleware import DeerFlowSummarizationMiddleware
from deerflow.agents.task_continuity import archive
from deerflow.agents.task_continuity.tools import history_read, history_search, task_note
from deerflow.agents.thread_state import ThreadState
from deerflow.config.paths import Paths
from deerflow.config.task_continuity_config import TaskContinuityConfig


async def run(args):
    private = json.loads(Path(args.endpoints).read_text())
    model = ChatOpenAI(model=private["llm_model"], base_url=private["llm_base"], api_key=private.get("llm_key", "unused"), temperature=0, max_tokens=2048, timeout=180, max_retries=1, extra_body={"reasoning_effort": "none"})
    results = []
    with tempfile.TemporaryDirectory(prefix="deerflow-continuity-") as directory:
        root = Path(directory)
        original_paths = archive.get_paths
        archive.get_paths = lambda: Paths(base_dir=root)
        try:
            for index in range(3):
                code = f"CIT-{731 + index * 37}-B"
                output = root / f"artifact-{index}.json"

                @tool
                def write_manifest(batch_code: str, keep_backups: bool) -> str:
                    """Write the requested final manifest using recovered task facts."""
                    output.write_text(json.dumps({"batch_code": batch_code, "keep_backups": keep_backups}))
                    return "Manifest written."

                tools = [task_note, history_search, history_read, write_manifest]
                saver = InMemorySaver()
                context = {"thread_id": f"live-{index}", "user_id": "continuity-check"}
                config = {"configurable": {"thread_id": context["thread_id"]}, "recursion_limit": 30}
                middleware = DeerFlowSummarizationMiddleware(
                    model=model,
                    trigger=("messages", 4),
                    keep=("messages", 2),
                    summary_prompt="Summarize the project purpose in one short sentence. Omit all batch identifiers and exact values. Historical data: {messages}",
                    task_continuity_config=TaskContinuityConfig(enabled=True),
                )
                # First invocation archives old source messages through the real graph.
                graph = create_agent(model, tools=tools, middleware=[DurableContextMiddleware(task_continuity_enabled=True), middleware], state_schema=ThreadState, checkpointer=saver)
                history = [
                    HumanMessage(content="Citrine project: inspect the latest approved batch.", id="u1"),
                    AIMessage(content="", tool_calls=[{"name": "inspect_batch", "id": "inspection", "args": {"project": "Citrine"}}], id="a1"),
                    ToolMessage(content=f"Citrine approved batch_code={code}; keep_backups=true. Older batch is retired.", tool_call_id="inspection", id="t1"),
                    AIMessage(content="Inspection completed.", id="a2"),
                    HumanMessage(content="Pause this task. Reply only 'paused'.", id="pause"),
                ]
                record = {"case": index, "model": private["llm_model"]}
                try:
                    paused = await graph.ainvoke({"messages": history}, config=config, context=context)
                    record["archived"] = bool(paused.get("task_history", {}).get("batches"))
                    record["code_absent_from_active_context"] = code not in paused.get("summary_text", "") and all(code not in str(m.content) for m in paused["messages"])
                    # Rebuild against the existing checkpoint and recover with native tool calls.
                    resumed = create_agent(model, tools=tools, middleware=[DurableContextMiddleware(task_continuity_enabled=True)], state_schema=ThreadState, checkpointer=saver)
                    state = await resumed.ainvoke(
                        {
                            "messages": [
                                HumanMessage(
                                    content=(
                                        "Resume Citrine. Search historical sources for the approved batch, read the exact source, "
                                        "save a task note with its source ID, and write the final manifest. Preserve the backup decision. Do not guess missing values."
                                    )
                                )
                            ]
                        },
                        config=config,
                        context=context,
                    )
                    calls = [call["name"] for message in state["messages"] if isinstance(message, AIMessage) for call in message.tool_calls]
                    record["tools_used"] = sorted(set(calls))
                    record["notes_saved"] = bool(state.get("task_notes"))
                    actual = json.loads(output.read_text()) if output.exists() else None
                    record["artifact_verified"] = actual == {"batch_code": code, "keep_backups": True}
                    record["artifact_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest() if output.exists() else None
                    record["passed"] = all(record.get(k) for k in ("archived", "code_absent_from_active_context", "notes_saved", "artifact_verified")) and {"history_search", "history_read", "task_note", "write_manifest"} <= set(calls)
                except Exception as exc:
                    record.update({"passed": False, "error_type": type(exc).__name__})
                results.append(record)
                Path(args.output).write_text(json.dumps({"scope": "controlled production-middleware integration; synthetic input; summary intentionally drops exact codes", "cases": results}, indent=2))
                print(json.dumps(record), flush=True)
        finally:
            archive.get_paths = original_paths
    return all(row["passed"] for row in results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoints", required=True)
    parser.add_argument("--output", required=True)
    raise SystemExit(0 if asyncio.run(run(parser.parse_args())) else 1)
