"""Dify multi-workflow router — unified invocation entry point."""

import logging
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg
from langgraph.config import get_stream_writer
from zens.community.dify.dify_client import DifyAPIError, DifyClient

from deerflow.config import get_app_config
from deerflow.runtime.user_context import get_current_user, get_effective_user_id

_MAX_CONVERSATION_CACHE = 1000
_conversation_ids: OrderedDict[str, str] = OrderedDict()
_lock = Lock()
_workflow_loggers: dict[str, logging.Logger] = {}


class ToolConfigResult:
    """Parsed result of a tool config read from config.yaml."""

    def __init__(self, api_key: str, base_url: str, response_mode: str = "blocking"):
        self.api_key = api_key
        self.base_url = base_url
        self.response_mode = response_mode


def _get_cache_key(tool_name: str, config: RunnableConfig | None) -> str:
    user_id = get_effective_user_id()
    thread_id = _get_thread_id(config)
    return f"{user_id}:{thread_id}:{tool_name}"


def _get_thread_id(config: RunnableConfig | None) -> str:
    """Extract thread_id from RunnableConfig, or return 'default'."""
    if config is None:
        return "default"
    configurable = config.get("configurable") or {}
    thread_id = configurable.get("thread_id")
    if thread_id is None:
        return "default"
    return str(thread_id)


def _get_cached_conversation(cache_key: str) -> str:
    """Retrieve conversation_id from bounded LRU cache, or empty string if not found (thread-safe)."""
    with _lock:
        if cache_key in _conversation_ids:
            _conversation_ids.move_to_end(cache_key)
            return _conversation_ids[cache_key]
        return ""


def _cache_conversation(cache_key: str, conversation_id: str) -> None:
    """Store conversation_id in bounded LRU cache (thread-safe)."""
    with _lock:
        _conversation_ids[cache_key] = conversation_id
        _conversation_ids.move_to_end(cache_key)
        if len(_conversation_ids) > _MAX_CONVERSATION_CACHE:
            _conversation_ids.popitem(last=False)


def _get_tool_config(tool_name: str) -> ToolConfigResult:
    """Read tool configuration from config.yaml."""
    config = get_app_config().get_tool_config(tool_name)
    if config is None:
        raise DifyAPIError(0, f"Tool '{tool_name}' is not configured in config.yaml")
    api_key: str | None = None
    if config.model_extra:
        api_key = config.model_extra.get("api_key")
    if not api_key:
        raise DifyAPIError(0, f"api_key not configured for tool '{tool_name}'")
    base_url = (config.model_extra.get("base_url") if config.model_extra else None) or "http://localhost:8000"
    response_mode = (config.model_extra.get("response_mode") if config.model_extra else None) or "blocking"
    return ToolConfigResult(api_key=api_key, base_url=base_url, response_mode=response_mode)


def _get_workflow_logger(tool_name: str) -> logging.Logger:
    """Return a logger that writes per-workflow log files to backend/logs/dify_{tool_name}.log."""
    with _lock:
        if tool_name not in _workflow_loggers:
            logger = logging.getLogger(f"zens.community.dify.{tool_name}")
            logger.setLevel(logging.DEBUG)
            _logs_dir = Path(__file__).resolve().parent.parent.parent.parent / "logs"
            _logs_dir.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(_logs_dir / f"dify_{tool_name}.log", mode="a", encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
            logger.addHandler(handler)
            _workflow_loggers[tool_name] = logger
        return _workflow_loggers[tool_name]


def _dify_file_type(mime_type: str) -> str:
    """Map Dify's upload-response ``mime_type`` to the file-ref ``type`` field.

    Dify chat-messages' ``files`` entries require a ``type`` from
    ``{"image", "audio", "video", "document", "custom"}``. We derive it from
    the upload response's MIME type so the workflow receives a category that
    matches the file's content.
    """
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "document"


async def invoke_workflow(
    tool_name: str,
    query: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,
    inputs: dict | None = None,
    files: list[str] | None = None,
) -> str:
    """Unified workflow invocation entry point.

    Routes to blocking or streaming mode based on the ``response_mode`` field
    in config.yaml for the given tool. Maintains conversation context in a
    thread-safe LRU cache keyed by (user_id, thread_id, workflow_name).

    In streaming mode, the tool pushes ``dify_started`` / ``dify_chunk`` /
    ``dify_completed`` / ``dify_failed`` events to the LangGraph custom stream
    as Dify answer fragments arrive, so the UI can render partial output in
    real time. The function still returns the joined full answer string for
    the LLM — the workflow tool's ``return_direct=True`` keeps that string
    terminal, no further agent turn.

    Args:
        tool_name: Workflow identifier (e.g. ``"dify_document_review"``).
        query: User query forwarded to the Dify chatflow.
        config: LangGraph runnable config (auto-injected).
        inputs: Optional dict merged into the Dify request's ``inputs`` field
            so the workflow can read workflow-level variables
            (e.g. ``{"mode": "精确回答", "policy_classification": "..."}``).
            Defaults to an empty dict when ``None``.
        files: Optional list of local file paths to attach. Each path is
            uploaded to Dify's ``/v1/files/upload`` first; the returned
            ``upload_file_id`` (plus a ``type`` derived from the upload
            response's ``mime_type``) is then placed in the chat-messages
            ``files`` field. Defaults to ``None`` (no attachments).
    """
    logger = _get_workflow_logger(tool_name)
    cache_key = _get_cache_key(tool_name, config)
    conversation_id = _get_cached_conversation(cache_key)
    user_id = get_effective_user_id() or "anonymous"
    current_user_info = get_current_user()
    if current_user_info is not None:
        # Use email for user identification to pass to Dify
        user = str(current_user_info.email)
    else:
        user = f"deerflow_{user_id}"

    logger.info(
        "invoke_workflow: tool=%s, query=%r, user=%r, conversation_id=%r, inputs=%r, files=%r",
        tool_name,
        query,
        user,
        conversation_id,
        inputs,
        files,
    )

    tool_cfg = _get_tool_config(tool_name)
    client = DifyClient(api_key=tool_cfg.api_key, base_url=tool_cfg.base_url)
    payload_inputs = inputs if inputs is not None else {}

    # Upload local files first, then build the chat-messages file refs.
    payload_files: list[dict] = []
    if files:
        try:
            for path in files:
                upload_resp = await client.upload_file(path, user)
                payload_files.append(
                    {
                        "type": _dify_file_type(upload_resp.mime_type),
                        "transfer_method": "local_file",
                        "upload_file_id": upload_resp.id,
                    }
                )
        except DifyAPIError as e:
            # The upload stage runs before the streaming branch, so without
            # this emit the UI sees no event for the failure — only an
            # unhandled exception. Mirror the chat-stage dify_failed event.
            if tool_cfg.response_mode == "streaming":
                writer = get_stream_writer()
                writer({"type": "dify_started", "tool": tool_name, "query_len": len(query)})
                writer({"type": "dify_failed", "tool": tool_name, "status_code": e.status_code, "message": e.message})
            raise

    if tool_cfg.response_mode == "streaming":
        writer = get_stream_writer()
        writer({"type": "dify_started", "tool": tool_name, "query_len": len(query)})
        full: list[str] = []
        last_conv = ""
        try:
            async for chunk in client.astream_chat(query=query, conversation_id=conversation_id, user=user, inputs=payload_inputs, files=payload_files):
                full.append(chunk.answer)
                if chunk.conversation_id:
                    last_conv = chunk.conversation_id
                writer({"type": "dify_chunk", "tool": tool_name, "delta": chunk.answer, "index": len(full) - 1})
        except DifyAPIError as e:
            writer({"type": "dify_failed", "tool": tool_name, "status_code": e.status_code, "message": e.message})
            raise
        if last_conv:
            _cache_conversation(cache_key, last_conv)
        full_answer = "".join(full)
        writer({"type": "dify_completed", "tool": tool_name, "total_len": len(full_answer), "conversation_id": last_conv})
        logger.info(
            "invoke_workflow streaming completed: answer=%r, conversation_id=%s",
            full_answer[:50] if full_answer else "",
            last_conv,
        )
        return full_answer

    response = client.chat(query=query, conversation_id=conversation_id, user=user, inputs=payload_inputs, files=payload_files)
    if response.conversation_id:
        _cache_conversation(cache_key, response.conversation_id)
    logger.info(
        "invoke_workflow blocking completed: answer=%r",
        response.answer[:50] if response.answer else "",
    )
    return response.answer
