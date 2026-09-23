"""Host-owned model construction, bounded invocation and neutral projection."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Mapping

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
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from deerflow.models import create_chat_model

logger = logging.getLogger(__name__)
_MESSAGE_TYPES = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}


def _reject_constant(value):
    raise ValueError("Non-finite JSON number")


def _schema_validator(schema):
    """Inline Draft 2020-12 object schemas; never retrieve remote references."""
    plain = json.loads(json.dumps(dict(schema), allow_nan=False))
    if plain.get("type") != "object":
        raise ModelInvocationFailed("response_schema must describe an object")

    def check(value):
        if isinstance(value, dict):
            if any(key in value for key in ("$ref", "$dynamicRef", "$recursiveRef")):
                raise ModelInvocationFailed("response_schema must be inline (no references)")
            if "$schema" in value and value["$schema"] != "https://json-schema.org/draft/2020-12/schema":
                raise ModelInvocationFailed("response_schema must use JSON Schema Draft 2020-12")
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(plain)
    Draft202012Validator.check_schema(plain)
    return plain, Draft202012Validator(plain)


def _usage(metadata):
    if not isinstance(metadata, Mapping):
        return None

    def token_count(key):
        value = metadata.get(key)
        return value if type(value) is int and value >= 0 else None

    return ModelUsage(token_count("input_tokens"), token_count("output_tokens"), token_count("total_tokens"))


class HostModelInvoker:
    def __init__(self, source, grant, semaphore, app_config):
        self._source = source
        self._grant = grant
        self._semaphore = semaphore
        self._app_config = app_config
        self._loop = asyncio.get_running_loop()
        self._closed = False
        self._tasks = set()

    def close(self):
        """Revoke retained handles synchronously, including queued/provider calls."""
        self._closed = True
        for task in tuple(self._tasks):
            task.cancel()

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        if self._closed:
            raise ModelInvocationUnavailable("Model invocation capability has stopped")
        if asyncio.get_running_loop() is not self._loop:
            raise ModelInvocationUnavailable("Model invocation requires the service event loop")
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            if not isinstance(request, ModelInvocationRequest):
                raise ModelInvocationFailed("Expected ModelInvocationRequest")
            timeout = request.timeout_seconds
            if timeout is not None and (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0):
                raise ModelInvocationFailed("timeout_seconds must be finite and positive")
            timeout = min(timeout, self._grant.timeout_seconds) if timeout is not None else self._grant.timeout_seconds
            async with asyncio.timeout(timeout):
                return await self._invoke(request)
        except ModelInvocationError as exc:
            # Copy only our normalized text. In particular, do not pass a JSON,
            # schema or provider exception through __context__ to extensions.
            failure = type(exc)(str(exc))
        except TimeoutError:
            failure = ModelInvocationFailed("Model invocation timed out")
        except Exception as exc:
            logger.warning("Extension model invocation failed for %s (%s)", self._source, type(exc).__name__)
            failure = ModelInvocationFailed("Model invocation failed")
        finally:
            self._tasks.discard(task)
        raise failure from None

    async def _invoke(self, request):
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

        validator = None
        if request.response_schema is not None:
            if not isinstance(request.response_schema, Mapping):
                raise ModelInvocationFailed("response_schema must be an object schema")
            # Freeze before the first await: callers may mutate their request schema.
            plain, validator = _schema_validator(request.response_schema)
            instruction = "Return only a JSON object matching the supplied response schema (no Markdown)."
            schema_data = "Required response schema (JSON data):\n" + json.dumps(plain, allow_nan=False)
            if input_chars + len(instruction) + len(schema_data) > self._grant.max_input_chars:
                raise ModelInvocationFailed("Model input including schema exceeds host limit")
            messages.insert(0, SystemMessage(content=instruction))
            # Schema descriptions may contain extension-owned input. Keep them
            # out of the host's fixed system instruction.
            messages.append(HumanMessage(content=schema_data))

        async with self._semaphore:
            if self._closed:
                raise ModelInvocationUnavailable("Model invocation capability has stopped")
            # Provider construction can load files/credentials; keep it off the loop.
            model = await asyncio.to_thread(create_chat_model, name, app_config=self._app_config)
            response = await model.ainvoke(
                messages,
                config={"run_name": "extension_model_invocation", "metadata": {"extension_source": self._source, "extension_model_role": role, "extension_purpose": request.purpose}},
            )

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
        if validator is not None:
            try:
                structured = json.loads(content, parse_constant=_reject_constant)
                json.dumps(structured, allow_nan=False)
                validator.validate(structured)
            except Exception:
                raise ModelOutputValidationError("Model output did not match response_schema") from None
        return ModelInvocationResult(content, structured, name, _usage(getattr(response, "usage_metadata", None)))
