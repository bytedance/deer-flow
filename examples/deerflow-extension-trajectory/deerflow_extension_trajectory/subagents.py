"""Bounded discovery of saved native child histories for one parent invocation."""

from contextlib import aclosing

from .checkpoints import project

MAX_DISCOVERY_CHECKPOINTS = 2000
MAX_CHILDREN = 64
MAX_PARENT_HOPS = 1000


def dispatch_message_id(snapshot, tool_call_id):
    """The latest AI message that issued this provider-scoped call ID."""
    for raw in reversed((snapshot.values or {}).get("messages", ())):
        message = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(message, dict) or message.get("type") != "ai":
            continue
        if any(
            call.get("id") == tool_call_id and call.get("name") == "task"
            for call in message.get("tool_calls") or ()
        ):
            identity = message.get("id")
            return identity if isinstance(identity, str) and identity else None
    return None


def native_namespace(namespace, execution):
    parts = namespace.split("|")
    # LangGraph can append a numeric invocation counter in a parent task.
    if parts[-1].isdecimal():
        parts.pop()
    return len(parts) > 1 and parts[-1] == "deerflow_subagent:" + execution


async def discover_children(accessor, config, checkpoint_id, tool_call_id):
    thread_id = config["configurable"]["thread_id"]
    selection = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": "",
            "checkpoint_id": checkpoint_id,
        }
    }
    parent = await accessor.aget_tuple(selection)
    if parent is None:
        raise ValueError("委派所在的父 checkpoint 已缺失，请刷新轨迹。")
    state = await accessor.aget(selection)
    calls = [
        call for message in project(state)["messages"] for call in message["tool_calls"]
    ]
    if not any(call["id"] == tool_call_id and call["name"] == "task" for call in calls):
        raise ValueError("父 checkpoint 中不存在这次 task 委派。")
    dispatch_id = dispatch_message_id(state, tool_call_id)
    if dispatch_id is None:
        return [], ["父快照缺少委派消息标识，无法可靠定位子轨迹。"]
    # Gateway run IDs live in runtime context and need not be persisted in
    # parent metadata. Child metadata still records the parent run explicitly.
    run_id = (parent.metadata or {}).get("run_id")
    run_id = run_id if isinstance(run_id, str) and run_id else None
    reader = accessor.checkpointer
    children, seen, warnings = [], set(), []
    ancestry = {checkpoint_id: True}
    dispatches = {checkpoint_id: dispatch_id}
    hops = 0

    async def belongs_to_invocation(start):
        nonlocal hops
        path = []
        current = start
        while current and current not in ancestry:
            if current in path:
                return False
            if hops >= MAX_PARENT_HOPS:
                if "父链校验达到上限，部分子执行未列出。" not in warnings:
                    warnings.append("父链校验达到上限，部分子执行未列出。")
                return False
            hops += 1
            path.append(current)
            saved = await reader.aget_tuple(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": current,
                    }
                }
            )
            scope = (saved.parent_config or {}).get("configurable", {}) if saved else {}
            if scope.get("thread_id", thread_id) != thread_id or scope.get(
                "checkpoint_ns", ""
            ):
                return False
            current = scope.get("checkpoint_id")
        matched = ancestry.get(current, False)
        ancestry.update({entry: matched for entry in path})
        return matched

    candidates = []
    filters = {"deerflow_subagent_tool_call_id": tool_call_id}
    if run_id:
        filters["deerflow_parent_run_id"] = run_id
    history = reader.alist(
        {"configurable": {"thread_id": thread_id}},
        filter=filters,
        limit=MAX_DISCOVERY_CHECKPOINTS + 1,
    )
    # SQLite holds its saver lock for the iterator's lifetime. Finish/close it
    # before walking any parent chain through the same saver.
    scanned = 0
    async with aclosing(history):
        async for saved in history:
            scanned += 1
            if scanned > MAX_DISCOVERY_CHECKPOINTS:
                warnings.append("子 checkpoint 较多，执行列表可能不完整。")
                break
            scope, metadata = saved.config.get("configurable", {}), saved.metadata or {}
            namespace = scope.get("checkpoint_ns", "")
            execution = metadata.get("deerflow_subagent_execution_id")
            child_run_id = metadata.get("deerflow_parent_run_id")
            if (
                scope.get("thread_id") != thread_id
                or not isinstance(execution, str)
                or not execution
                or not isinstance(namespace, str)
                or not native_namespace(namespace, execution)
                or not isinstance(child_run_id, str)
                or not child_run_id
                or (run_id is not None and child_run_id != run_id)
                or metadata.get("deerflow_subagent_tool_call_id") != tool_call_id
                or namespace in seen
            ):
                continue
            seen.add(namespace)
            candidates.append(
                {
                    "execution_id": execution,
                    "name": metadata.get("deerflow_subagent_name") or "subagent",
                    "parent_run_id": child_run_id,
                    "tool_call_id": tool_call_id,
                    "parent_checkpoint_id": checkpoint_id,
                    "checkpoint_ns": namespace,
                    "head_checkpoint_id": scope["checkpoint_id"],
                    "_parent_checkpoint": (metadata.get("parents") or {}).get(""),
                }
            )
    for child in candidates:
        parent_checkpoint = child.pop("_parent_checkpoint")
        if not isinstance(parent_checkpoint, str) or not parent_checkpoint:
            continue
        if not await belongs_to_invocation(parent_checkpoint):
            continue
        if parent_checkpoint not in dispatches:
            saved_parent = await accessor.aget(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": parent_checkpoint,
                    }
                }
            )
            dispatches[parent_checkpoint] = dispatch_message_id(
                saved_parent, tool_call_id
            )
        # An ancestor match alone also accepts a later reuse of the call ID,
        # even in the same run. Match the issuing message at the child parent.
        if dispatches[parent_checkpoint] != dispatch_id:
            continue
        if len(children) >= MAX_CHILDREN:
            warnings.append("子执行超过 64 次，仅列出部分已保存的执行。")
            break
        children.append(child)
    return children, warnings


def child_selection(thread_id, child, checkpoint_id=None):
    return {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_ns": child["checkpoint_ns"],
            "checkpoint_id": checkpoint_id or child["head_checkpoint_id"],
        }
    }


async def validate_child(accessor, selection, child):
    saved = await accessor.aget_tuple(selection)
    if saved is None:
        raise ValueError("子 checkpoint 已缺失，请刷新子轨迹。")
    metadata = saved.metadata or {}
    for key, field in [
        ("deerflow_subagent_execution_id", "execution_id"),
        ("deerflow_parent_run_id", "parent_run_id"),
        ("deerflow_subagent_tool_call_id", "tool_call_id"),
    ]:
        if metadata.get(key) != child[field]:
            raise ValueError("子 checkpoint 与委派关联不匹配。")
