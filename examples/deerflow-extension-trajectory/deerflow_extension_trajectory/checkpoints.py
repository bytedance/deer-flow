"""Read-only projection of saved state; no model or tool execution."""

import hashlib
import json
import re
from types import SimpleNamespace

from .analysis import PROCESS_KEY, process_evidence
from .timing import KEY, TimingOptions
from .findings import operation_targets, tool_meta_evidence

TEXT_LIMIT = 4000
HIDDEN_CONTROL_NAMES = {
    "summary",
    "loop_warning",
    "todo_reminder",
    "todo_completion_reminder",
}


def uploaded_images(text, max_images=16):
    """Project upload references only; bytes remain behind the host's artifact ACL."""
    images = []

    def replace_block(match):
        entries = re.findall(
            r"- (.+)\s*\(([\d.]+\s*(?:B|KB|MB|GB|TB))\)\s*\n\s*Path:\s*([^\n]+)",
            match[2],
        )
        accepted = 0
        for name, size, raw_path in entries:
            path = raw_path.strip()
            if (
                (max_images is not None and len(images) >= max_images)
                or not path.startswith("/mnt/user-data/uploads/")
                or any(part in {"", ".", ".."} for part in path[1:].split("/"))
                or any(ord(char) < 32 or char == "\\" for char in path)
                or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif"))
            ):
                continue
            images.append({"name": name.strip(), "path": path, "size": size})
            accepted += 1
        return "" if entries and accepted == len(entries) else match[0]

    display = re.sub(
        r"<(current_uploads|uploaded_files)>([\s\S]*?)</\1>", replace_block, text
    )
    return images, display.strip()


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def project(snapshot, text_limit=TEXT_LIMIT, *, include_content=False):
    values = snapshot.values or {}
    messages = []
    for index, raw in enumerate(values.get("messages", ())):
        message = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(message, dict):
            continue
        extra = message.get("additional_kwargs") or {}
        kind = {"human": "user", "ai": "assistant", "tool": "tool"}.get(
            message.get("type", message.get("role"))
        )
        if (
            not kind
            or extra.get("hide_from_ui")
            or message.get("name") in HIDDEN_CONTROL_NAMES
        ):
            continue
        model_error_fallback = (
            kind == "assistant" and extra.get("deerflow_error_fallback") is True
        )
        content = message.get("content", "")
        text = (
            content
            if isinstance(content, str)
            else "\n".join(
                block.get("text", "")
                for block in content or ()
                if isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            )
        )
        images, display_text = (
            uploaded_images(text, max_images=None if text_limit is None else 16)
            if kind == "user"
            else ([], text)
        )
        calls = []
        truncated = text_limit is not None and len(text) > text_limit
        for call in message.get("tool_calls") or ():
            args = json.dumps(call.get("args"), ensure_ascii=False, default=str)
            truncated |= text_limit is not None and len(args) > text_limit
            calls.append(
                {
                    "id": call.get("id"),
                    "name": call.get("name"),
                    "args": args[:text_limit],
                    "args_fingerprint": fingerprint(call.get("args")),
                    "operation_targets": operation_targets(
                        call.get("name"), call.get("args")
                    ),
                }
            )
        messages.append(
            {
                "id": message.get("id")
                or f"unidentified:{index}:{fingerprint(message)}",
                "unidentified": not bool(message.get("id")),
                "fingerprint": fingerprint(
                    [
                        kind,
                        text,
                        message.get("tool_calls"),
                        message.get("tool_call_id"),
                        message.get("status"),
                        extra.get("deerflow_tool_meta"),
                        extra.get(PROCESS_KEY),
                        model_error_fallback,
                    ]
                ),
                "kind": kind,
                "text": text[:text_limit],
                "display_text": display_text[:text_limit],
                "images": images,
                "tool_calls": calls,
                "tool_name": message.get("name"),
                "tool_call_id": message.get("tool_call_id"),
                "tool_meta": tool_meta_evidence(extra.get("deerflow_tool_meta")),
                "process": process_evidence(extra.get(PROCESS_KEY)),
                "tool_status": (extra.get("deerflow_tool_meta") or {}).get("status")
                or message.get("status"),
                "truncated": truncated,
                **({"model_error_fallback": True} if model_error_fallback else {}),
                **(
                    {"timing": TimingOptions().project(extra.get(KEY))}
                    if kind in {"assistant", "tool"}
                    else {}
                ),
                **({"content": content} if include_content else {}),
            }
        )
    summary = values.get("summary_text") or ""
    return {
        "messages": messages,
        "summary": fingerprint(summary),
        "summary_text": str(summary)[:text_limit],
        "summary_truncated": (
            text_limit is not None and len(str(summary)) > text_limit
        ),
        "next": tuple(snapshot.next or ()),
        "versions": getattr(snapshot, "channel_versions", {}) or {},
        "update_source": (getattr(snapshot, "metadata", {}) or {}).get("source"),
        "manual_compaction_seen": "manual_compaction"
        in (getattr(snapshot, "versions_seen", {}) or {}),
        "created_at": snapshot.created_at,
        "thread_id": (snapshot.config or {}).get("configurable", {}).get("thread_id"),
        "checkpoint_id": (snapshot.config or {})
        .get("configurable", {})
        .get("checkpoint_id"),
        "checkpoint_ns": (snapshot.config or {})
        .get("configurable", {})
        .get("checkpoint_ns", ""),
        "omitted_message_count": len(values.get("messages", ())) - len(messages),
    }


def transition(before, after, *, include_comparison=False):
    previous = {message["id"]: message for message in before["messages"]}
    current = {message["id"]: message for message in after["messages"]}
    removed = previous.keys() - current.keys()
    replaced = set()
    # DynamicContext rekeys a visible user X to X__user. Content equality alone
    # cannot prove identity: a later execution may repeat the exact same text.
    for message in after["messages"]:
        original = message["id"].removesuffix("__user")
        if (
            message["kind"] == "user"
            and original != message["id"]
            and original in removed
            and previous[original]["fingerprint"] == message["fingerprint"]
        ):
            removed.remove(original)
            replaced.add(message["id"])
    summary_changed = before["summary"] != after["summary"]
    rows = []
    if removed or summary_changed:
        ran_summarizer = any(
            "Summarization" in node
            and not node.startswith("branch:")
            and version != before.get("versions", {}).get(node)
            for node, version in after.get("versions", {}).items()
        )
        # Repeated manual compactions inherit the same empty versions_seen entry.
        # Require the host's update shape as well; the inherited marker alone is
        # not proof of a new compaction. This is a snapshot-based classification,
        # not an exact execution-event attribution.
        manual_compaction = (
            after.get("update_source") == "update"
            and after.get("manual_compaction_seen", False)
            and bool(removed)
            and len(current) < len(previous)
            and bool(after["summary_text"].strip())
        )
        compaction = summary_changed and (
            manual_compaction
            or ran_summarizer
            or any("Summarization" in node for node in before["next"])
        )
        rows.append(
            {
                "kind": "compaction" if compaction else "state_change",
                "text": after["summary_text"]
                if summary_changed
                else "保存的消息集合发生变化；不能据此认定为压缩。",
                "before_count": len(previous),
                "after_count": len(current),
                "truncated": after["summary_truncated"] if summary_changed else False,
            }
        )
        if compaction and include_comparison:

            def displayed(message):
                return {
                    key: value for key, value in message.items() if key != "fingerprint"
                }

            rows[-1]["comparison"] = {
                "source": "checkpoint_diff",
                "before_checkpoint_id": before.get("checkpoint_id"),
                "after_checkpoint_id": after.get("checkpoint_id"),
                "before_summary": before.get("summary_text", ""),
                "after_summary": after["summary_text"],
                "removed_messages": [
                    displayed(message)
                    for message in before["messages"]
                    if message["id"] in removed
                ],
                "retained_messages": [
                    displayed(message) for message in after["messages"]
                ],
                "omitted_before_count": before.get("omitted_message_count", 0),
                "omitted_after_count": after.get("omitted_message_count", 0),
            }
    for message in after["messages"]:
        if message["id"] in replaced:
            continue
        old = previous.get(message["id"])
        if old is None or old["fingerprint"] != message["fingerprint"]:
            rows.append(
                {
                    key: value
                    for key, value in message.items()
                    if key not in {"fingerprint", "content"}
                }
                | {"updated": old is not None}
            )
    for index, row in enumerate(rows):
        row.update(
            checkpoint_id=after["checkpoint_id"],
            checkpoint_ns=after.get("checkpoint_ns", ""),
            thread_id=after.get("thread_id"),
            created_at=after["created_at"],
            row_id=f"{after.get('checkpoint_ns', '')}:{after['checkpoint_id']}:{index}",
        )
    return rows


EMPTY = {"messages": [], "summary": fingerprint(""), "next": ()}


async def read_page(accessor, config, limit=24, text_limit=TEXT_LIMIT):
    """Follow one branch's parents. Retain only two materialized snapshots at a time."""
    blocks = []
    warnings = []
    seen = set()
    scope = {
        key: config["configurable"].get(key, "")
        for key in ("thread_id", "checkpoint_ns")
    }

    async def saved_state(selection):
        reader = accessor if hasattr(accessor, "aget_tuple") else accessor.checkpointer
        saved = await reader.aget_tuple(selection)
        if saved is None:
            return None
        # Pin the exact tuple selected above, including when reading latest state.
        snapshot = await accessor.aget(getattr(saved, "config", selection))
        raw_checkpoint = getattr(saved, "checkpoint", {}) or {}
        pending_nodes = tuple(
            key.removeprefix("branch:to:")
            for key in raw_checkpoint.get("channel_values", {})
            if key.startswith("branch:to:")
        )
        return SimpleNamespace(
            values=snapshot.values,
            config=snapshot.config,
            parent_config=snapshot.parent_config,
            next=snapshot.next or pending_nodes,
            created_at=snapshot.created_at,
            channel_versions=(getattr(saved, "checkpoint", {}) or {}).get(
                "channel_versions", {}
            ),
            metadata=getattr(saved, "metadata", {}) or {},
            versions_seen=raw_checkpoint.get("versions_seen", {}),
        )

    current = await saved_state(config)
    if current is None:
        warnings.append("此位置没有可读取的 checkpoint；可能未持久化或已被清理。")
    processed = 0
    while current and (current.config or {}).get("configurable", {}).get(
        "checkpoint_id"
    ):
        current_config = current.config["configurable"]
        checkpoint_id = current_config["checkpoint_id"]
        if checkpoint_id in seen:
            warnings.append("父链出现循环，已停止读取。")
            return {
                **scope,
                "rows": sum(reversed(blocks), []),
                "next_checkpoint": None,
                "scanned": processed,
                "warnings": warnings,
                "checkpoint_ids": list(seen),
            }
        seen.add(checkpoint_id)
        child = project(
            current, text_limit=text_limit, include_content=text_limit is None
        )
        parent_config = current.parent_config
        if parent_config:
            parent_values = parent_config.get("configurable", {})
            if parent_values.get("thread_id") != config["configurable"][
                "thread_id"
            ] or parent_values.get("checkpoint_ns", "") != config["configurable"].get(
                "checkpoint_ns", ""
            ):
                raise ValueError("Invalid checkpoint parent scope")
            parent = await saved_state(parent_config)
            if not parent or not (parent.config or {}).get("configurable", {}).get(
                "checkpoint_id"
            ):
                warnings.append(
                    "较早 checkpoint 已缺失；以下最早一段仅代表仍保存的快照，历史不完整。"
                )
                parent = None
        else:
            parent = None
        blocks.append(
            transition(
                project(
                    parent, text_limit=text_limit, include_content=text_limit is None
                )
                if parent
                else EMPTY,
                child,
                include_comparison=text_limit is None,
            )
        )
        processed += 1
        current = parent
        if processed >= limit or sum(len(block) for block in blocks) >= 120:
            break
    return {
        **scope,
        "rows": sum(reversed(blocks), []),
        "checkpoint_ids": list(seen),
        "scanned": processed,
        "warnings": warnings,
        "next_checkpoint": current.config["configurable"]["checkpoint_id"]
        if current
        else None,
    }
