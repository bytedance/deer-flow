"""Loopback test gateway: real plugin, host ACL/artifacts and SQLite checkpoints.

Synthetic header identities and a deterministic state-only graph replace login
and model execution. Never mount this app in the production Gateway. Only the
command-line preview imports the example source rather than an installed wheel.
"""

import asyncio
import base64
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import uvicorn
from deerflow_extension_api.auth import (
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
)
from fastapi import FastAPI, Request
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore
from langgraph.types import Overwrite

from app.gateway import services
from app.gateway.routers.artifacts import router as artifacts_router
from app.gateway.routers.plugins import router as plugins_router
from deerflow.config.paths import Paths
from deerflow.extensions.loader import ExtensionSpec, load_extensions
from deerflow.persistence.thread_meta.memory import MemoryThreadMetaStore
from deerflow.runtime.user_context import reset_current_user, set_current_user

THREAD = "00000000-0000-0000-0000-000000000001"
OTHER_THREAD = "00000000-0000-0000-0000-000000000002"
CHILD_THREAD = "00000000-0000-0000-0000-000000000003"
TIMING_THREAD = "00000000-0000-0000-0000-000000000004"
TOOL_FINDINGS_THREAD = "00000000-0000-0000-0000-000000000006"
TIMING_THRESHOLDS = {"model": 1000, "tool": 10, "tool:timed_timeout": 1000}
IMAGE_PATH = "/mnt/user-data/uploads/image_1.png"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII="
)
LONG_RESULT = "TOOL-RESULT-BEGIN " + "durable evidence " * 400 + " TOOL-RESULT-END"


async def seed_subagent_history(
    app, mode="full", *, persist_parent_run_id=False, repeat_in_run=False
):
    """Real nested graphs write child namespaces and parent checkpoint lineage."""
    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    from deerflow.agents.thread_state import get_thread_state_schema

    schema = get_thread_state_schema(mode, 3)

    def echo_child(value: str) -> str:
        """Return deterministic tool evidence."""
        return "CHILD-TOOL-BEGIN " + value * 4200 + " CHILD-TOOL-END"

    builder = StateGraph(schema)
    builder.add_node(
        "plan",
        lambda state: {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "internal-call",
                            "name": "echo_child",
                            "args": {"value": state["messages"][0].content},
                        }
                    ],
                )
            ]
        },
    )
    builder.add_node("tools", ToolNode([echo_child]))
    # More than one history page, with no repeated visible messages.
    for index in range(26):
        builder.add_node(f"idle{index}", lambda state: {})
        builder.add_edge("tools" if index == 0 else f"idle{index - 1}", f"idle{index}")
    builder.add_node(
        "finish",
        lambda state: {
            "messages": [
                AIMessage(content="CHILD-FINAL " + state["messages"][0].content)
            ]
        },
    )
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "tools")
    builder.add_edge("idle25", "finish")
    builder.add_edge("finish", END)
    child_builder = builder

    async def delegate(state, config, runtime: Runtime):
        run_id = runtime.context["run_id"]

        async def execute(call):
            child = child_builder.compile(checkpointer=app.state.checkpointer)
            execution_id = run_id + "-" + call["id"] + "-" + state["messages"][-1].id
            child_config = {
                **config,
                "configurable": {
                    **config["configurable"],
                    "checkpoint_ns": config["configurable"]["checkpoint_ns"]
                    + "|deerflow_subagent:"
                    + execution_id,
                },
                "metadata": {
                    **config["metadata"],
                    "deerflow_subagent_execution_id": execution_id,
                    "deerflow_subagent_name": "bash",
                    "deerflow_parent_run_id": run_id,
                    "deerflow_subagent_tool_call_id": call["id"],
                },
            }
            await child.ainvoke(
                {"messages": [HumanMessage(content=execution_id)]}, child_config
            )
            return ToolMessage(
                content="delegated result", tool_call_id=call["id"], name="task"
            )

        return {
            "messages": await asyncio.gather(
                *(execute(call) for call in state["messages"][-1].tool_calls)
            )
        }

    builder = StateGraph(schema, context_schema=dict)

    def plan(state):
        return {
            "messages": [
                AIMessage(
                    content="Delegate two children",
                    tool_calls=[
                        {
                            "id": "outer-shared",
                            "name": "task",
                            "args": {"subagent_type": "bash", "prompt": "first"},
                        },
                        {
                            "id": "outer-second",
                            "name": "task",
                            "args": {"subagent_type": "bash", "prompt": "second"},
                        },
                    ],
                )
            ]
        }

    builder.add_node("plan", plan)
    builder.add_node("tools", delegate)
    builder.add_edge(START, "plan")
    builder.add_edge("plan", "tools")
    if repeat_in_run:
        builder.add_node("plan_again", plan)
        builder.add_node("tools_again", delegate)
        builder.add_edge("tools", "plan_again")
        builder.add_edge("plan_again", "tools_again")
        builder.add_edge("tools_again", END)
    else:
        builder.add_edge("tools", END)
    graph = builder.compile(checkpointer=app.state.checkpointer)
    for run_id in ["parent-one", "parent-two"]:
        # Gateway carries run identity in runtime context, not parent metadata.
        await graph.ainvoke(
            {"messages": [HumanMessage(content="DELEGATE-TURN " + run_id)]},
            {
                "configurable": {"thread_id": CHILD_THREAD},
                "metadata": {"run_id": run_id} if persist_parent_run_id else {},
            },
            context={"run_id": run_id},
        )


def state_accessor(app, thread=THREAD, checkpoint_id=None, node="seed"):
    request = Request({"type": "http", "app": app, "headers": []})
    return services.build_checkpoint_state_mutation_accessor(
        request, thread_id=thread, as_node=node, checkpoint_id=checkpoint_id
    )


async def seed_history(app):
    accessor, config = state_accessor(app)
    messages = [HumanMessage(id="u1", content="FIRST-TURN: research the example")]

    async def save():
        return await accessor.aupdate(
            config, {"messages": Overwrite(list(messages))}, as_node="seed"
        )

    app.state.first_checkpoint = await save()
    messages.append(
        AIMessage(
            id="a1",
            content="",
            tool_calls=[
                {"id": "call1", "name": "read_file", "args": {"path": "/example.txt"}}
            ],
        )
    )
    await save()
    messages.append(
        ToolMessage(
            id="t1", tool_call_id="call1", name="read_file", content=LONG_RESULT
        )
    )
    await save()
    messages.append(AIMessage(id="a2", content="FIRST-ANSWER: source inspected"))
    await save()
    # More than one page; unchanged snapshots exercise deduplication.
    for _ in range(26):
        await save()
    app.state.before_compaction = await save()
    compact, compact_config = state_accessor(app, node="manual_compaction")
    await compact.aupdate(
        compact_config,
        {
            "messages": Overwrite([messages[-1]]),
            "summary_text": "COMPACTED: first turn researched",
        },
        as_node="manual_compaction",
    )
    messages = [
        messages[-1],
        HumanMessage(
            id="u2",
            content=f"LATEST-TURN: inspect picture\n<current_uploads>\n- image_1.png (1 KB)\n  Path: {IMAGE_PATH}\n</current_uploads>",
        ),
    ]
    await save()
    messages.append(AIMessage(id="a3", content="LATEST-ANSWER: picture inspected"))
    await save()
    other, other_config = state_accessor(app, OTHER_THREAD)
    await other.aupdate(
        other_config,
        {"messages": [HumanMessage(id="bob", content="BOB-PRIVATE")]},
        as_node="seed",
    )


async def seed_timing_history(app, paths):
    """Store representative output timings and a timeout with no output."""
    from deerflow_extension_trajectory.timing import KEY, TimingRepository

    accessor, config = state_accessor(app, TIMING_THREAD)

    def recorded(operation, name, duration_ms, *, outcome="completed"):
        return {
            KEY: {
                "span_id": f"{name}-{duration_ms}",
                "operation": operation,
                "name": name,
                "duration_ms": duration_ms,
                "outcome": outcome,
            }
        }

    batches = [
        [
            HumanMessage(id="legacy-user", content="OLD-UNMEASURED"),
            AIMessage(id="legacy-ai", content="LEGACY-ANSWER"),
        ],
        [HumanMessage(id="measured-user", content="MEASURED-TURN")],
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"id": name, "name": name, "args": {}}
                    for name in ("timed_echo", "timed_timeout")
                ],
                additional_kwargs=recorded("model", "fixture-model", 80),
            ),
        ],
        [
            ToolMessage(
                name="timed_echo",
                tool_call_id="timed_echo",
                content="TIMED-TOOL-RESULT",
                additional_kwargs=recorded("tool", "timed_echo", 20),
            ),
            ToolMessage(
                name="timed_timeout",
                tool_call_id="timed_timeout",
                content="Error: fixture timeout",
                status="error",
                additional_kwargs=recorded(
                    "tool", "timed_timeout", 12, outcome="timeout"
                ),
            ),
        ],
        [
            AIMessage(
                content="TIMED-FINAL-ANSWER",
                additional_kwargs=recorded("model", "fixture-model", 40),
            ),
        ],
        [HumanMessage(id="timeout-user", content="MODEL-TIMEOUT")],
    ]
    for messages in batches:
        saved = await accessor.aupdate(config, {"messages": messages}, as_node="seed")
    repository = TimingRepository(
        paths.base_dir / "extensions/trajectory/timings.sqlite"
    )
    await repository.aappend(
        {
            **recorded("model", "fixture-model", 15, outcome="timeout")[KEY],
            "user_id": "alice",
            "thread_id": TIMING_THREAD,
            "anchor_id": "timeout-user",
            "parent_checkpoint_id": saved["configurable"]["checkpoint_id"],
            "ended_at": "2026-01-01T00:00:00Z",
            "error_type": "APITimeoutError",
        }
    )


async def seed_tool_findings_history(app):
    """Save host-normalized outcomes for a failed read and its follow-ups."""
    from deerflow.agents.middlewares.tool_result_meta import (
        normalize_tool_message,
        stamp_exception_meta,
    )

    accessor, config = state_accessor(app, TOOL_FINDINGS_THREAD)
    workspace = "/mnt/user-data/workspace"
    missing = f"{workspace}/missing.txt"
    read = {"id": "read", "name": "read_file", "args": {"path": missing}}
    document = {
        "id": "document",
        "name": "read_file",
        "args": {"path": f"{workspace}/document.txt"},
    }
    shell = {
        "id": "shell",
        "name": "bash",
        "args": {"command": f"cat {missing} 2>&1; echo EXIT_CODE=$?"},
    }
    search = {
        "id": "search",
        "name": "glob",
        "args": {"path": workspace, "pattern": "missing.txt"},
    }

    def missing_result(id):
        return stamp_exception_meta(
            ToolMessage(
                id=id,
                name="read_file",
                tool_call_id="read",
                status="error",
                content=f"Error: FileNotFoundError: {missing}",
            ),
            FileNotFoundError(missing),
        )

    batches = [
        [HumanMessage(id="findings-user", content="FILE-FAILURE-RETRIES")],
        [AIMessage(id="first-read", content="", tool_calls=[read, document])],
        [
            missing_result("first-error"),
            ToolMessage(
                content="Error: this is actual document content",
                name="read_file",
                tool_call_id="document",
                additional_kwargs={
                    "deerflow_tool_meta": {"status": "success", "source": "tool_return"}
                },
            ),
        ],
        [AIMessage(id="second-read", content="", tool_calls=[read])],
        [missing_result("second-error")],
        [AIMessage(content="", tool_calls=[shell])],
        [
            normalize_tool_message(
                ToolMessage(
                    name="bash",
                    tool_call_id="shell",
                    content=f"cat: {missing}: No such file or directory\nEXIT_CODE=1",
                )
            )
        ],
        [AIMessage(content="", tool_calls=[search])],
        [
            normalize_tool_message(
                ToolMessage(
                    name="glob", tool_call_id="search", content="No files matched"
                )
            )
        ],
        [AIMessage(content="Error: the model claims it retried 99 times")],
    ]
    for messages in batches:
        await accessor.aupdate(config, {"messages": messages}, as_node="seed")


def create_app(
    directory,
    *,
    seed=True,
    mode="full",
    persist_parent_run_id=False,
    repeat_in_run=False,
    timing_evidence=False,
):
    directory = Path(directory)
    paths = Paths(base_dir=directory / "home")

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncSqliteSaver.from_conn_string(
            str(directory / "checkpoints.sqlite")
        ) as saver:
            app.state.checkpointer = saver
            app.state.checkpoint_channel_mode = mode
            app.state.store = None
            app.state.thread_store = MemoryThreadMetaStore(InMemoryStore())
            for thread, user in [
                (THREAD, "alice"),
                (OTHER_THREAD, "bob"),
                (CHILD_THREAD, "alice"),
                (TIMING_THREAD, "alice"),
                (TOOL_FINDINGS_THREAD, "alice"),
            ]:
                await app.state.thread_store.create(thread, user_id=user)
            if seed:
                await seed_history(app)
                await seed_subagent_history(
                    app,
                    mode,
                    persist_parent_run_id=persist_parent_run_id,
                    repeat_in_run=repeat_in_run,
                )
                if timing_evidence:
                    await seed_timing_history(app, paths)
                    await seed_tool_findings_history(app)
                uploads = paths.sandbox_uploads_dir(THREAD, user_id="alice")
                uploads.mkdir(parents=True, exist_ok=True)
                (uploads / "image_1.png").write_bytes(PNG)
            app.state.reads = []

            async def builder(
                request, *, thread_id, checkpoint_id=None, fail_closed=False
            ):
                assert fail_closed
                app.state.reads.append((thread_id, checkpoint_id))
                return state_accessor(app, thread_id, checkpoint_id)

            # Replace only model/assistant assembly, retaining real host ACL,
            # accessor materialization, SQLite and artifact/export file handling.
            with (
                patch.object(
                    services, "build_thread_checkpoint_state_accessor", builder
                ),
                patch("deerflow.config.paths.get_paths", return_value=paths),
                patch("app.gateway.path_utils.get_paths", return_value=paths),
            ):
                extensions, diagnostics = load_extensions(
                    [
                        ExtensionSpec(
                            use="deerflow_extension_trajectory:install",
                            required=True,
                            config={"timing": {"slow_thresholds_ms": TIMING_THRESHOLDS}}
                            if timing_evidence
                            else {},
                        )
                    ]
                )
                assert not diagnostics
                app.state.extensions = extensions
                for _, router in extensions.routers:
                    app.include_router(router)
                yield

    app = FastAPI(lifespan=lifespan)

    @app.middleware("http")
    async def identity(request, call_next):
        user_id = request.headers.get("x-test-user", "")
        user = SimpleNamespace(id=user_id, system_role="user")
        request.state.user = user if user_id else None
        request.state.auth_source = "session"
        request.state.auth = SimpleNamespace(
            is_authenticated=bool(user_id),
            user=user if user_id else None,
            has_permission=lambda *args: True,
        )
        token = set_current_user(user)
        try:
            return await call_next(request)
        finally:
            reset_current_user(token)

    setattr(
        app.state,
        EXTENSION_PRINCIPAL_RESOLVER_KEY,
        lambda request: (
            ExtensionPrincipal(request.state.user.id) if request.state.user else None
        ),
    )
    app.include_router(plugins_router)
    app.include_router(artifacts_router)
    return app


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    with TemporaryDirectory(prefix="deerflow-trajectory-test-") as directory:
        uvicorn.run(
            create_app(directory, timing_evidence=True),
            host="127.0.0.1",
            port=int(sys.argv[1]),
            log_level="warning",
        )
