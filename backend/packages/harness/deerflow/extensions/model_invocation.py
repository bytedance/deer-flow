"""Host-owned model construction, bounded invocation and neutral projection."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from deerflow_extension_api import (
    ModelInvocationError,
    ModelInvocationFailed,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelInvocationUnauthorized,
    ModelInvocationUnavailable,
    ModelMessage,
    ModelOutputValidationError,
    ModelUsage,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)
_MESSAGE_TYPES = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}


@dataclass
class _Invocation:
    acquired: bool = False
    abandoned: bool = False
    provider: asyncio.Task | None = None


async def _schema_validator(schema_json, content=None):
    """Run CPU-bound JSON Schema work outside the Gateway process/GIL.

    A dedicated pipe-I/O thread also works with Windows' selector loop and cannot
    be starved by sync providers occupying asyncio's default executor. Admission
    bounds both these threads and child processes. Cancellation kills and reaps
    the child before this call releases its slot.
    """
    loop = asyncio.get_running_loop()
    finished = loop.create_future()
    cancelled = threading.Event()
    payload = schema_json + "\n"
    if content is not None:
        payload += json.dumps(content) + "\n"

    def work():
        status = b""
        try:
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {}
            with subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).with_name("model_schema_worker.py"))],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                **options,
            ) as process:
                try:
                    data = payload.encode("utf-8")
                    while not cancelled.is_set():
                        try:
                            status, _ = process.communicate(data, timeout=0.05)
                            break
                        except subprocess.TimeoutExpired:
                            data = None  # communicate retains pending input for the next poll.
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.communicate()
        except Exception:
            pass  # Only fixed validation status crosses the public error boundary.
        finally:
            loop.call_soon_threadsafe(finished.set_result, status.split())

    threading.Thread(target=work, name="extension-schema-validation", daemon=True).start()
    interrupted = False
    while not finished.done():
        try:
            await asyncio.shield(finished)
        except asyncio.CancelledError:
            interrupted = True
            cancelled.set()
    if interrupted:
        raise asyncio.CancelledError
    status = finished.result()
    if content is None:
        if status != [b"ready"]:
            raise ModelInvocationFailed("response_schema must be a valid inline Draft 2020-12 object schema")
    elif status != [b"ready", b"valid"]:
        raise ModelOutputValidationError("Model output did not match response_schema")


def _usage(metadata):
    if not isinstance(metadata, Mapping):
        return None

    def token_count(key):
        value = metadata.get(key)
        return value if type(value) is int and value >= 0 else None

    return ModelUsage(token_count("input_tokens"), token_count("output_tokens"), token_count("total_tokens"))


class HostModelInvoker:
    def __init__(self, source, grant, budget, app_config):
        self._source = source
        self._grant = grant
        self._budget = budget
        self._app_config = app_config
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._tasks = set()

    def close(self):
        """Revoke handles and cancel callers; running providers retain their slots."""
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if self._closed:
            raise ModelInvocationUnavailable("Model invocation capability has stopped")
        if asyncio.get_running_loop() is not self._loop:
            raise ModelInvocationUnavailable("Model invocation requires the service event loop")
        if self._budget.admitted >= self._budget.capacity:
            raise ModelInvocationFailed("Model invocation capacity exceeded")
        self._budget.admitted += 1
        call = _Invocation()
        deadline = None
        task = asyncio.current_task()
        cancellation_count = task.cancelling()
        self._tasks.add(task)
        try:
            if not isinstance(request, ModelInvocationRequest):
                raise ModelInvocationFailed("Expected ModelInvocationRequest")
            timeout = request.timeout_seconds
            if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
                raise ModelInvocationFailed("timeout_seconds must be finite and positive")
            timeout = min(timeout, self._grant.timeout_seconds) if timeout is not None else self._grant.timeout_seconds
            deadline = asyncio.timeout(timeout)
            async with deadline:
                await self._budget.semaphore.acquire()
                call.acquired = True
                return await self._invoke(request, call)
        except asyncio.CancelledError:
            # shield also raises when only the provider task is cancelled. A
            # previously handled caller cancellation must not mask that failure.
            if task.cancelling() > cancellation_count or call.provider is None or not call.provider.cancelled():
                raise
            failure = ModelInvocationFailed("Model provider cancelled")
        except ModelInvocationError as exc:
            # Copy only our normalized text. In particular, do not pass a JSON,
            # schema or provider exception through __context__ to extensions.
            failure = type(exc)(str(exc))
        except TimeoutError:
            failure = ModelInvocationFailed("Model invocation timed out" if deadline is not None and deadline.expired() else "Model provider timed out")
        except Exception as exc:
            logger.warning("Extension model invocation failed for %s (%s)", self._source, type(exc).__name__)
            failure = ModelInvocationFailed("Model invocation failed")
        finally:
            self._tasks.discard(task)
            call.abandoned = True

            def release(_=None):
                self._budget.admitted -= 1
                if call.acquired:
                    self._budget.semaphore.release()

            if call.provider is not None and not call.provider.done():
                call.provider.add_done_callback(release)
            else:
                release()
        raise failure from None

    async def _provider_call(self, name, messages, role, purpose, call):
        # Neither to_thread construction nor a sync-backed ainvoke is cancellable.
        # The caller may leave, but the real work keeps its admission/slot until done.
        model = await asyncio.to_thread(create_chat_model, name, app_config=self._app_config)
        if self._closed or call.abandoned:
            raise ModelInvocationUnavailable("Model invocation capability has stopped")
        return await model.ainvoke(
            messages,
            config={"run_name": "extension_model_invocation", "metadata": {"extension_source": self._source, "extension_model_role": role, "extension_purpose": purpose}},
        )

    async def _invoke(self, request, call):
        role = request.model_role if request.model_role is not None else "default"
        if not isinstance(role, str) or role not in self._grant.roles:
            raise ModelInvocationUnauthorized("Model role is not granted to this extension")
        name = self._grant.roles[role]
        if self._app_config.get_model_config(name) is None:
            raise ModelInvocationUnavailable("Configured model is unavailable")
        if request.purpose is not None and (not isinstance(request.purpose, str) or not 1 <= len(request.purpose) <= 128):
            raise ModelInvocationFailed("purpose must contain 1 to 128 characters")
        if not request.messages or len(request.messages) > 256:
            raise ModelInvocationFailed("Expected 1 to 256 text messages")
        messages = []
        input_chars = 0
        for message in request.messages:
            if not isinstance(message, ModelMessage) or not isinstance(message.role, str) or message.role not in _MESSAGE_TYPES or not isinstance(message.content, str):
                raise ModelInvocationFailed("Only system, user and assistant text messages are supported")
            input_chars += len(message.content)
            if input_chars > self._grant.max_input_chars:
                raise ModelInvocationFailed("Model input exceeds host limit")
            messages.append(_MESSAGE_TYPES[message.role](content=message.content))

        schema_json = None
        if request.response_schema is not None:
            if not isinstance(request.response_schema, Mapping):
                raise ModelInvocationFailed("response_schema must be an object schema")
            # Snapshot the schema before validation crosses the process boundary.
            schema_json = json.dumps(dict(request.response_schema), allow_nan=False)
            instruction = "Return only a JSON object matching the supplied response schema (no Markdown)."
            schema_data = "Required response schema (JSON data):\n" + schema_json
            if input_chars + len(instruction) + len(schema_data) > self._grant.max_input_chars:
                raise ModelInvocationFailed("Model input including schema exceeds host limit")
            messages.insert(0, SystemMessage(content=instruction))
            # Schema descriptions may contain extension-owned input. Keep them
            # out of the host's fixed system instruction.
            messages.append(HumanMessage(content=schema_data))
            await _schema_validator(schema_json)

        if self._closed:
            raise ModelInvocationUnavailable("Model invocation capability has stopped")
        call.provider = asyncio.create_task(self._provider_call(name, messages, role, request.purpose, call))
        self._budget.retain(call.provider)
        response = await asyncio.shield(call.provider)

        if self._closed:
            raise ModelInvocationUnavailable("Model invocation capability has stopped")

        if getattr(response, "tool_calls", None) or getattr(response, "invalid_tool_calls", None):
            raise ModelInvocationFailed("Tool-call responses are not supported")
        content = response.content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                else:
                    raise ModelInvocationFailed("Model returned non-text content")
            content = "".join(parts)
        if not isinstance(content, str):
            raise ModelInvocationFailed("Model returned non-text content")
        if len(content) > self._grant.max_output_chars:
            raise ModelInvocationFailed("Model output exceeds host limit")
        structured = None
        if schema_json is not None:
            await _schema_validator(schema_json, content)
            structured = json.loads(content)
        return ModelInvocationResult(content, structured, name, _usage(getattr(response, "usage_metadata", None)))
