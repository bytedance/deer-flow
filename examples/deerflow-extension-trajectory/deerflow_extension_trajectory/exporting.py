"""Bounded checkpoint and measured-operation evidence export."""

import asyncio
import hashlib
import io
import json
import re
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath

from .checkpoints import read_page
from .analysis import analyze_rows
from .subagents import child_selection, discover_children, validate_child

MAX_TEXT_BYTES = 32 * 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGES = 200


class ExportLimit(ValueError):
    pass


async def collect_export(
    accessor,
    config,
    max_checkpoints=10000,
    *,
    child_reader_factory=None,
    timing_enricher=None,
    execution_id=None,
):
    reader = accessor if hasattr(accessor, "aget_tuple") else accessor.checkpointer
    head = await reader.aget_tuple(config)
    if head is None:
        raise LookupError("没有可导出的 checkpoint。")
    config = head.config
    thread_id = config["configurable"]["thread_id"]
    namespace = config["configurable"].get("checkpoint_ns", "")
    head_id = config["configurable"]["checkpoint_id"]
    batches, warnings, seen = [], [], set()
    scanned = size = row_count = 0
    while True:
        cid = config["configurable"]["checkpoint_id"]
        if cid in seen:
            warnings.append("checkpoint 父链出现循环，历史不完整。")
            break
        seen.add(cid)
        if scanned >= max_checkpoints:
            raise ExportLimit("历史超过 10000 个快照，未生成不完整的导出文件。")
        page = await read_page(
            accessor, config, limit=min(24, max_checkpoints - scanned), text_limit=None
        )
        if timing_enricher is not None:
            page["rows"], notes = await timing_enricher(
                page["rows"], execution_id, page.get("checkpoint_ids", [])
            )
            page["warnings"].extend(notes)
        scanned += page["scanned"]
        for row in page["rows"]:
            row.setdefault("checkpoint_ns", namespace)
            row.setdefault("thread_id", thread_id)
        row_count += len(page["rows"])
        size += len(json.dumps(page["rows"], ensure_ascii=False).encode("utf-8"))
        if size > MAX_TEXT_BYTES or row_count > 50000:
            raise ExportLimit(
                "轨迹超过 32 MB 或 50000 条记录，未生成不完整的导出文件。"
            )
        batches.append(page["rows"])
        warnings.extend(page["warnings"])
        if not page["next_checkpoint"]:
            break
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": page["next_checkpoint"],
            }
        }
        await asyncio.sleep(0)
    data = {
        "schema_version": 1,
        "source": "checkpoint",
        "thread_id": thread_id,
        "head_checkpoint_id": head_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "history_complete": not warnings,
        "scanned": scanned,
        "warnings": list(dict.fromkeys(warnings)),
        "scope": "当前分支保存的用户、助手、工具与状态变化；不包含完整模型请求。时间为快照保存时间。图片引用不保证历史文件版本仍在。",
        "rows": analyze_rows(
            [row for batch in reversed(batches) for row in batch],
            thread_id=thread_id,
            execution_id=execution_id,
        ),
    }
    if child_reader_factory is not None and not namespace:
        child_accessor = child_reader_factory(accessor)
        exported = set()
        for row in data["rows"]:
            for call in row.get("tool_calls", []):
                if call.get("name") != "task" or not call.get("id"):
                    continue
                children, notes = await discover_children(
                    accessor, config, row["checkpoint_id"], call["id"]
                )
                warnings.extend(notes)
                if not children:
                    warnings.append(
                        "部分 task 委派没有可关联的子 checkpoint；子历史可能未启用或已被清理。"
                    )
                call["subagents"] = []
                for child in children:
                    if child["checkpoint_ns"] in exported:
                        continue
                    exported.add(child["checkpoint_ns"])
                    selection = child_selection(thread_id, child)
                    await validate_child(child_accessor, selection, child)
                    child_data = await collect_export(
                        child_accessor,
                        selection,
                        max_checkpoints=max_checkpoints - scanned,
                        timing_enricher=timing_enricher,
                        execution_id=child["execution_id"],
                    )
                    scanned += child_data["scanned"]
                    row_count += len(child_data["rows"])
                    size += len(
                        json.dumps(child_data, ensure_ascii=False).encode("utf-8")
                    )
                    if size > MAX_TEXT_BYTES or row_count > 50000:
                        raise ExportLimit(
                            "主子轨迹超过导出容量上限，未生成不完整的导出文件。"
                        )
                    warnings.extend(child_data["warnings"])
                    call["subagents"].append({**child_data, **child})
        data["scanned"] = scanned
        data["warnings"] = list(dict.fromkeys(warnings))
        data["history_complete"] = not warnings
        data["scope"] += " 子执行按 task 委派分组，不代表并发主子执行的全局时间顺序。"
    if timing_enricher is not None:
        data["scope"] += (
            " 耗时来自实际调用计时；独立计时记录的时间为调用结束时间，缺少证据不估算。"
        )
    return data


def all_rows(data):
    for row in data["rows"]:
        yield row
        for call in row.get("tool_calls", []):
            for child in call.get("subagents", []):
                yield from all_rows(child)


def fenced(text):
    text = str(text or "")
    fence = "`" * max(
        3, max((len(m[0]) + 1 for m in re.finditer(r"`+", text)), default=3)
    )
    return f"{fence}\n{text}\n{fence}\n"


def comparison_markdown(comparison, labels, heading_level=4):
    heading = "#" * min(6, heading_level)
    lines = [
        f"{heading} 压缩前",
        "",
        "此前摘要：",
        fenced(comparison["before_summary"] or "（此前没有摘要）"),
        "本次从快照移除的可展示消息：",
        "",
    ]
    for message in comparison["removed_messages"]:
        lines += [f"**{labels.get(message['kind'], message['kind'])}**", ""]
        content = message.get("content", message.get("text", ""))
        lines += [
            fenced(
                content
                if isinstance(content, str)
                else json.dumps(content, ensure_ascii=False, indent=2)
            )
        ]
        for call in message.get("tool_calls", []):
            lines += [f"工具调用：{call.get('name', '')}", fenced(call.get("args"))]
    lines += [
        f"{heading} 压缩后",
        "",
        "新摘要：",
        fenced(comparison["after_summary"]),
        f"保留的可展示消息：{len(comparison['retained_messages'])} 条。",
        "",
        "本对照来自相邻快照差异，不是完整模型请求或精确压缩输入映射。",
        "",
    ]
    if comparison["omitted_before_count"] or comparison["omitted_after_count"]:
        lines += [
            f"系统或隐藏消息未展示：压缩前 {comparison['omitted_before_count']} 条，压缩后 {comparison['omitted_after_count']} 条。",
            "",
        ]
    return lines


def render_markdown(data, images, warnings, *, heading_offset=0):
    def heading(level, text):
        return "#" * min(6, level + heading_offset) + " " + text

    lines = [
        heading(1, "对话运行轨迹"),
        "",
        f"对话 ID：{data['thread_id']}",
        f"导出时间：{data.get('exported_at', '')}",
        f"起始 checkpoint：{data['head_checkpoint_id']}",
        "",
        "按当前分支保存顺序排列；时间为快照保存时间。此文件不是完整模型请求日志。图片为导出时仍可读取的文件。",
        "",
    ]
    if warnings:
        lines += [heading(2, "导出提示"), fenced("\n".join(warnings))]
    labels = {
        "user": "用户",
        "assistant": "助手",
        "tool": "工具结果",
        "compaction": "压缩",
        "state_change": "状态变化",
        "timing": "计时记录",
    }
    turn = 0
    names = {
        call.get("id"): call.get("name")
        for row in data["rows"]
        for call in row.get("tool_calls", [])
        if call.get("id")
    }
    for row in data["rows"]:
        if row["kind"] == "user" and not row.get("updated"):
            turn += 1
            lines += [heading(2, f"第 {turn} 轮"), ""]
        text = row.get("display_text", row.get("text", ""))
        if not (
            text.strip()
            or row.get("images")
            or row.get("tool_calls")
            or row.get("tool_status")
            or row["kind"] in {"compaction", "state_change"}
        ):
            continue
        lines += [
            heading(3, labels.get(row["kind"], row["kind"])),
            "",
            f"时间：{row.get('created_at', '')}",
            "",
        ]
        if row["kind"] == "tool":
            lines += [
                fenced(
                    row.get("tool_name")
                    or (row.get("analysis") or {}).get("tool_name")
                    or (
                        names.get(row.get("tool_call_id"))
                        if not row.get("analysis")
                        else None
                    )
                    or "未知工具"
                )
            ]
            if row.get("tool_status"):
                lines += [fenced(row["tool_status"])]
        if "before_count" in row:
            lines += [f"可见消息：{row['before_count']} → {row['after_count']}", ""]
        if row["kind"] in {"assistant", "tool", "timing"}:
            timing = row.get("timing")
            if timing:
                lines += [
                    f"实测耗时：{timing['duration_ms']:.3f} ms；结果：{timing['outcome']}；超过慢阈值：{timing.get('is_slow', False)}。",
                    "",
                ]
            else:
                status = "；结果：failed" if row.get("model_error_fallback") else ""
                lines += [f"耗时：未记录{status}。", ""]
        if row.get("analysis"):
            lines += [
                "证据定位：",
                fenced(json.dumps(row["analysis"]["evidence"], ensure_ascii=False)),
                (
                    f"执行内保存顺序：{row['analysis']['saved_order']}。"
                    if row["analysis"]["saved_order"] is not None
                    else "独立运行时证据，按锚点定位，不参与 checkpoint 顺序编号。"
                ),
                "",
            ]
            if row["kind"] == "tool":
                lines += [
                    f"调用关联：{row['analysis'].get('association')}；调用记录：{row['analysis']['result_links']}。",
                    "返回码（进程结构化证据）：",
                    fenced(
                        json.dumps(row.get("process") or "未记录", ensure_ascii=False)
                    ),
                ]
        failure = (row.get("analysis") or {}).get("tool_failure")
        if failure:
            lines += [
                f"工具失败线索：{failure['reason']}；证据类别：{failure['confidence']}。",
                "",
            ]
        if row.get("comparison"):
            lines += comparison_markdown(row["comparison"], labels, heading_offset + 4)
        elif text:
            lines += [fenced(text)]
        for call in row.get("tool_calls", []):
            lines += ["工具调用：", fenced(call.get("name")), fenced(call.get("args"))]
            if call.get("analysis"):
                fact = call["analysis"]
                lines += [
                    f"调用关联：{fact['association']}；结果记录：{fact['result_row_ids']}；同轮同执行完全相同调用：{fact['repeat_index']}/{fact['repeat_count']}（当前导出范围）。",
                    "",
                ]
            retry = (call.get("analysis") or {}).get("retry")
            if retry:
                lines += [
                    f"重试线索：{retry['reason']}；证据类别：{retry['confidence']}。",
                    fenced(json.dumps(retry, ensure_ascii=False)),
                ]
            for child in call.get("subagents", []):
                lines += [
                    heading(4, "子 agent 轨迹"),
                    fenced(child["name"]),
                    "执行 ID：",
                    fenced(child["execution_id"]),
                    "子步骤按保存顺序排列；不表示与主执行之间的全局时间顺序。",
                    "",
                ]
                lines += [
                    render_markdown(
                        child,
                        images,
                        child["warnings"],
                        heading_offset=heading_offset + 3,
                    )
                ]
        for image in row.get("images", []):
            lines += [fenced(f"{image['name']} · {image['size']}")]
            local = images.get(image["path"])
            lines += [
                f"![上传图片]({local})" if local else "图片未打包；见导出提示。",
                "",
            ]
        if row.get("images") and row.get("text") != text:
            lines += ["上传文件说明：", fenced(row.get("text"))]
    return "\n".join(lines)


def build_download(data, format, image_reader, stop=None):
    stop = stop or threading.Event()
    warnings = list(data["warnings"])
    if format == "json":
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), warnings
    paths, files = {}, {}
    total = 0
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for row in all_rows(data):
            for image in row.get("images", []):
                if stop.is_set():
                    raise ExportLimit("导出已取消。")
                path = image["path"]
                if path in paths:
                    continue
                if len(paths) >= MAX_IMAGES:
                    raise ExportLimit("图片超过 200 张，未生成不完整的 ZIP。")
                paths[path] = None
                try:
                    content = image_reader(path)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise ExportLimit("单张图片超过 20 MB。")
                except ExportLimit:
                    raise
                except (OSError, ValueError) as exc:
                    warnings.append(
                        f"图片未打包：{path}（{type(exc).__name__}，文件缺失或无法访问）。"
                    )
                    continue
                digest = hashlib.sha256(content).hexdigest()
                if digest not in files:
                    total += len(content)
                    if total > MAX_TOTAL_IMAGE_BYTES:
                        raise ExportLimit("图片总量超过 64 MB，未生成不完整的 ZIP。")
                    filename = f"images/{digest}{PurePosixPath(path).suffix.lower()}"
                    files[digest] = filename
                    archive.writestr(
                        filename, content, compress_type=zipfile.ZIP_STORED
                    )
                paths[path] = files[digest]
        archive.writestr("trajectory.md", render_markdown(data, paths, warnings))
        archive.writestr(
            "EXPORT_NOTES.txt",
            "解压后打开 trajectory.md；images 目录须与它保存在一起。\n图片为导出时文件版本，不保证与历史调用时字节一致。\n"
            + "\n".join(warnings),
        )
    return buffer.getvalue(), warnings
