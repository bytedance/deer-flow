"""Version-sensitive host adapter. All reads remain subject to host authorization."""

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import threading
from typing import Literal

from deerflow_extension_api.auth import resolve_principal
from fastapi import APIRouter, HTTPException, Query, Request, Response

from .checkpoints import read_page
from .exporting import MAX_IMAGE_BYTES, ExportLimit, build_download, collect_export
from .subagents import child_selection, discover_children, validate_child

_KEY = secrets.token_bytes(32)
_READERS = asyncio.Semaphore(2)
_EXPORTS = asyncio.Semaphore(1)
MAX_COMPARISON_BYTES = 8 * 1024 * 1024


def read_export_image(thread_id, user_id, virtual_path):
    """Read only a regular upload file, without following symlinks at any level."""
    from deerflow.config.paths import get_paths

    prefix = "/mnt/user-data/uploads/"
    if not virtual_path.startswith(prefix):
        raise ValueError("Not an upload")
    parts = virtual_path[len(prefix) :].split("/")
    if any(
        part in {"", ".", ".."} or "\\" in part or any(ord(c) < 32 for c in part)
        for part in parts
    ):
        raise ValueError("Invalid path")
    if not virtual_path.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        raise ValueError("Unsupported image")
    root = get_paths().sandbox_uploads_dir(thread_id, user_id=user_id)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
        with os.fdopen(fd, "rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Not a regular file")
            if info.st_size > MAX_IMAGE_BYTES:
                raise ExportLimit("单张图片超过 20 MB，未生成 ZIP。")
            content = file.read(MAX_IMAGE_BYTES + 1)
            if len(content) > MAX_IMAGE_BYTES:
                raise ExportLimit("单张图片超过 20 MB，未生成 ZIP。")
            if not (
                content.startswith(b"\x89PNG\r\n\x1a\n")
                or content.startswith(b"\xff\xd8\xff")
                or content.startswith((b"GIF87a", b"GIF89a"))
                or (content.startswith(b"RIFF") and content[8:12] == b"WEBP")
            ):
                raise ValueError("Not a supported image")
            return content
    finally:
        os.close(descriptor)


def encode_cursor(user, thread, checkpoint):
    data = base64.urlsafe_b64encode(
        json.dumps([user, thread, checkpoint]).encode()
    ).decode()
    return data + "." + hmac.new(_KEY, data.encode(), hashlib.sha256).hexdigest()


def decode_cursor(cursor, user, thread):
    try:
        data, signature = cursor.split(".")
        expected = hmac.new(_KEY, data.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        owner, thread_id, checkpoint = json.loads(base64.urlsafe_b64decode(data))
        if (owner, thread_id) != (user, thread) or not isinstance(checkpoint, str):
            raise ValueError
        return checkpoint
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(409, "分页标记失效，请刷新轨迹页后重试。") from exc


def scoped_cursor(user, thread, kind, **fields):
    return encode_cursor(user, thread, json.dumps({"kind": kind, **fields}))


def decode_scoped_cursor(cursor, user, thread, kind):
    try:
        data = json.loads(decode_cursor(cursor, user, thread))
        if not isinstance(data, dict) or data.get("kind") != kind:
            raise ValueError
        return data
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "子轨迹标记失效，请刷新轨迹后重试。") from exc


def child_accessor(parent):
    # A saved child namespace is not an embedded subgraph of today's lead graph.
    # Use a state-only, mode-matched reader, without constructing an agent or tools.
    from deerflow.runtime.checkpoint_state import (
        CheckpointStateAccessor,
        build_state_mutation_graph,
    )

    return CheckpointStateAccessor.bind(
        build_state_mutation_graph("trajectory_read", parent.mode),
        parent.checkpointer,
        mode=parent.mode,
        direct_namespace=True,
    )


def timing_path():
    from deerflow.config.paths import get_paths

    return get_paths().base_dir / "extensions" / "trajectory" / "timings.sqlite"


def timing_identity(request):
    """Host-specific identity resolution; caller supplied IDs never grant access."""
    from langgraph.config import get_config
    from deerflow.runtime.user_context import resolve_runtime_user_id

    runtime = request.runtime
    context = runtime.context if isinstance(runtime.context, dict) else {}
    config = getattr(runtime, "config", None)
    if not isinstance(config, dict):
        try:
            config = get_config()
        except RuntimeError:
            config = {}
    state = getattr(request, "state", {}) or {}
    tool_call = getattr(request, "tool_call", None)
    anchor = None
    for message in reversed(state.get("messages", [])):
        if tool_call and not any(
            call.get("id") == tool_call.get("id")
            for call in getattr(message, "tool_calls", ())
        ):
            continue
        if not getattr(message, "id", None) or (
            getattr(message, "additional_kwargs", {}) or {}
        ).get("hide_from_ui"):
            continue
        anchor = message.id
        break
    execution = (config.get("metadata") or {}).get("deerflow_subagent_execution_id")
    checkpoint_map = config.get("configurable", {}).get("checkpoint_map", {})
    namespace = ""
    if execution:
        candidates = [
            key
            for key in checkpoint_map
            if f"deerflow_subagent:{execution}" in key.split("|")
        ]
        namespace = max(candidates, key=len, default="")
    return {
        "user_id": resolve_runtime_user_id(runtime),
        "thread_id": context.get("thread_id")
        or config.get("configurable", {}).get("thread_id"),
        "run_id": context.get("run_id"),
        "execution_id": execution,
        "parent_checkpoint_id": checkpoint_map.get(namespace),
        "anchor_id": anchor,
        "tool_call_id": tool_call.get("id") if tool_call else None,
    }


def build_router(repository=None):
    # The public extension API currently has no checkpoint reader.
    from app.gateway.authz import require_permission
    from app.gateway.services import build_thread_checkpoint_state_accessor
    from .timing import TimingOptions, TimingRepository

    repository = repository or TimingRepository()

    async def enrich(page, user, thread, execution=None):
        page["rows"], notes = await repository.enrich(
            page["rows"], user, thread, execution, page.get("checkpoint_ids", [])
        )
        page["warnings"].extend(notes)
        for row in page["rows"]:
            row.setdefault("checkpoint_ns", page.get("checkpoint_ns", ""))
            row.setdefault("thread_id", thread)
        return page

    router = APIRouter(prefix="/api/ext-trajectory", tags=["ext-trajectory"])

    @router.get("/threads/{thread_id}/checkpoints")
    @require_permission("threads", "read", owner_check=True, require_existing=True)
    async def trajectory(
        thread_id: str,
        request: Request,
        response: Response,
        cursor: str | None = Query(default=None, max_length=2048),
    ):
        response.headers["Cache-Control"] = "no-store"
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        checkpoint = (
            decode_cursor(cursor, principal.user_id, thread_id) if cursor else None
        )
        try:
            # Limit concurrent reads and total request time, including queueing.
            async with asyncio.timeout(20):
                async with _READERS:
                    accessor, config = await build_thread_checkpoint_state_accessor(
                        request,
                        thread_id=thread_id,
                        checkpoint_id=checkpoint,
                        fail_closed=True,
                    )
                    page = await read_page(accessor, config)
                    await enrich(page, principal.user_id, thread_id)
        except TimeoutError as exc:
            raise HTTPException(503, "历史读取超时，请稍后重试。") from exc
        except ValueError as exc:
            raise HTTPException(
                409, "无法读取此会话的 checkpoint，请检查宿主版本及存储模式。"
            ) from exc
        next_checkpoint = page.pop("next_checkpoint")
        page["next_cursor"] = (
            encode_cursor(principal.user_id, thread_id, next_checkpoint)
            if next_checkpoint
            else None
        )
        page["source"] = "checkpoint"
        page["slow_threshold_defaults_ms"] = {
            operation: repository.options.thresholds.get(operation)
            for operation in ("model", "tool")
        }
        for row in page["rows"]:
            for call in row.get("tool_calls", []):
                if call.get("name") == "task" and call.get("id"):
                    call["subagent_cursor"] = scoped_cursor(
                        principal.user_id,
                        thread_id,
                        "invocation",
                        checkpoint_id=row["checkpoint_id"],
                        tool_call_id=call["id"],
                    )
            if row["kind"] == "compaction":
                row["comparison_cursor"] = encode_cursor(
                    principal.user_id, thread_id, row["checkpoint_id"]
                )
        return page

    @router.get("/threads/{thread_id}/subagents")
    @require_permission("threads", "read", owner_check=True, require_existing=True)
    async def subagents(
        thread_id: str,
        request: Request,
        response: Response,
        cursor: str = Query(max_length=4096),
    ):
        response.headers["Cache-Control"] = "no-store"
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        invocation = decode_scoped_cursor(
            cursor, principal.user_id, thread_id, "invocation"
        )
        try:
            async with asyncio.timeout(20), _READERS:
                accessor, config = await build_thread_checkpoint_state_accessor(
                    request,
                    thread_id=thread_id,
                    checkpoint_id=invocation["checkpoint_id"],
                    fail_closed=True,
                )
                children, warnings = await discover_children(
                    accessor,
                    config,
                    invocation["checkpoint_id"],
                    invocation["tool_call_id"],
                )
        except TimeoutError as exc:
            raise HTTPException(503, "子执行查找超时，请重试。") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        for child in children:
            child["cursor"] = scoped_cursor(
                principal.user_id,
                thread_id,
                "child",
                child=child.copy(),
                checkpoint_id=child["head_checkpoint_id"],
            )
        return {"children": children, "warnings": warnings}

    @router.get("/threads/{thread_id}/subagent-checkpoints")
    @require_permission("threads", "read", owner_check=True, require_existing=True)
    async def subagent_checkpoints(
        thread_id: str,
        request: Request,
        response: Response,
        cursor: str = Query(max_length=4096),
    ):
        response.headers["Cache-Control"] = "no-store"
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        selection = decode_scoped_cursor(cursor, principal.user_id, thread_id, "child")
        child = selection["child"]
        try:
            async with asyncio.timeout(20), _READERS:
                parent, _ = await build_thread_checkpoint_state_accessor(
                    request, thread_id=thread_id, fail_closed=True
                )
                accessor = child_accessor(parent)
                config = child_selection(thread_id, child, selection["checkpoint_id"])
                await validate_child(accessor, config, child)
                page = await read_page(accessor, config)
                await enrich(page, principal.user_id, thread_id, child["execution_id"])
        except TimeoutError as exc:
            raise HTTPException(503, "子轨迹读取超时，请重试。") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        checkpoint = page.pop("next_checkpoint")
        page["next_cursor"] = (
            scoped_cursor(
                principal.user_id,
                thread_id,
                "child",
                child=child,
                checkpoint_id=checkpoint,
            )
            if checkpoint
            else None
        )
        for row in page["rows"]:
            if row["kind"] == "compaction":
                row["comparison_cursor"] = scoped_cursor(
                    principal.user_id,
                    thread_id,
                    "child",
                    child=child,
                    checkpoint_id=row["checkpoint_id"],
                )
        return page

    @router.get("/threads/{thread_id}/compaction")
    @require_permission("threads", "read", owner_check=True, require_existing=True)
    async def compaction_comparison(
        thread_id: str,
        request: Request,
        response: Response,
        cursor: str = Query(max_length=4096),
    ):
        response.headers["Cache-Control"] = "no-store"
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        checkpoint = decode_cursor(cursor, principal.user_id, thread_id)
        selection = None
        if checkpoint.startswith("{"):
            selection = decode_scoped_cursor(
                cursor, principal.user_id, thread_id, "child"
            )
            checkpoint = selection["checkpoint_id"]
        try:
            async with asyncio.timeout(20):
                async with _READERS:
                    accessor, config = await build_thread_checkpoint_state_accessor(
                        request,
                        thread_id=thread_id,
                        checkpoint_id=None if selection else checkpoint,
                        fail_closed=True,
                    )
                    if selection:
                        accessor = child_accessor(accessor)
                        config = child_selection(
                            thread_id, selection["child"], checkpoint
                        )
                        await validate_child(accessor, config, selection["child"])
                    page = await read_page(accessor, config, limit=1, text_limit=None)
                    comparison = next(
                        (
                            row["comparison"]
                            for row in page["rows"]
                            if row["kind"] == "compaction"
                            and row["checkpoint_id"] == checkpoint
                        ),
                        None,
                    )
                    if page["warnings"] or comparison is None:
                        raise HTTPException(
                            409,
                            "压缩前后快照已缺失或不再可用，无法生成完整对照。请刷新轨迹后重试。",
                        )
                    if (
                        len(json.dumps(comparison, ensure_ascii=False).encode("utf-8"))
                        > MAX_COMPARISON_BYTES
                    ):
                        raise HTTPException(
                            413,
                            "本次压缩对照超过 8 MiB，请导出 JSON 或 Markdown 查看；页面不会展示截断的对照。",
                        )
        except TimeoutError as exc:
            raise HTTPException(503, "压缩对照读取超时，请稍后重试。") from exc
        except ValueError as exc:
            raise HTTPException(409, "无法读取此对话的压缩快照。") from exc
        return comparison

    @router.get("/threads/{thread_id}/export")
    @require_permission("threads", "read", owner_check=True, require_existing=True)
    async def export_trajectory(
        thread_id: str,
        request: Request,
        format: Literal["json", "markdown"] = Query(default="json"),
        slow_thresholds_ms: str | None = Query(default=None, max_length=4096),
    ):
        principal = resolve_principal(request)
        if principal is None:
            raise HTTPException(401, "Authentication required")
        if principal.is_internal:
            raise HTTPException(403, "请使用登录用户的会话导出。")
        options = repository.options
        if slow_thresholds_ms is not None:
            try:
                overrides = json.loads(slow_thresholds_ms)
                if not isinstance(overrides, dict):
                    raise ValueError
                options = TimingOptions(
                    {"slow_thresholds_ms": {**options.thresholds, **overrides}}
                )
            except (ValueError, RecursionError) as exc:
                raise HTTPException(422, "慢阈值设置无效。") from exc
        try:
            async with asyncio.timeout(120):
                async with _EXPORTS:
                    accessor, config = await build_thread_checkpoint_state_accessor(
                        request,
                        thread_id=thread_id,
                        checkpoint_id=None,
                        fail_closed=True,
                    )
                    data = await collect_export(
                        accessor,
                        config,
                        child_reader_factory=child_accessor,
                        timing_enricher=lambda rows, execution, checkpoint_ids: (
                            repository.enrich(
                                rows,
                                principal.user_id,
                                thread_id,
                                execution,
                                checkpoint_ids,
                                options=options,
                            )
                        ),
                    )
                    stop = threading.Event()
                    job = asyncio.create_task(
                        asyncio.to_thread(
                            build_download,
                            data,
                            format,
                            lambda path: read_export_image(
                                thread_id, principal.user_id, path
                            ),
                            stop,
                        )
                    )
                    try:
                        content, warnings = await asyncio.shield(job)
                    except asyncio.CancelledError:
                        stop.set()
                        try:
                            await asyncio.shield(job)
                        except Exception:
                            pass
                        raise
        except ExportLimit as exc:
            raise HTTPException(413, str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except TimeoutError as exc:
            raise HTTPException(503, "导出超过 120 秒，请稍后重试。") from exc
        except ValueError as exc:
            raise HTTPException(409, "无法读取此对话的历史快照。") from exc
        suffix = "json" if format == "json" else "zip"
        return Response(
            content,
            media_type="application/json" if format == "json" else "application/zip",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": f'attachment; filename="trajectory.{suffix}"',
                "X-Trajectory-Warnings": str(len(warnings)),
                "Access-Control-Expose-Headers": "X-Trajectory-Warnings, Content-Disposition",
            },
        )

    return router
