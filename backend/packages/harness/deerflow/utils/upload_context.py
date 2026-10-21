"""Structured upload context, projected only at model/summary boundaries.

The metadata lives on its owning human message, so replacement, deletion and
compaction follow the ordinary message lifecycle without sibling IDs or state
channels. The Gateway strips this server-owned key from external input.
"""

from __future__ import annotations

import logging
from copy import deepcopy

from langchain_core.messages import AnyMessage, HumanMessage

UPLOAD_CONTEXT_KEY = "deerflow_upload_context"
UPLOAD_CONTEXT_VERSION = 1
logger = logging.getLogger(__name__)


def upload_context_text(message: AnyMessage) -> str | None:
    """Read supported context metadata without guessing from user text."""
    if not isinstance(message, HumanMessage) or UPLOAD_CONTEXT_KEY not in message.additional_kwargs:
        return None
    value = message.additional_kwargs[UPLOAD_CONTEXT_KEY]
    if not isinstance(value, dict) or type(value.get("version")) not in (int, float) or value["version"] != UPLOAD_CONTEXT_VERSION or not isinstance(value.get("text"), str):
        logger.debug("Ignoring malformed or unsupported upload context on message %s", message.id)
        return None
    return value["text"]


def project_upload_context(message: AnyMessage, *, sanitized: bool = False) -> AnyMessage:
    """Return the model-facing copy, preserving native multimodal blocks.

    ``projected`` prevents repeated prefixes; ``sanitized`` separately records
    a completed guardrail pass so a fail-open projection can be retried. Both
    markers are request-local and removed by UI/journal restoration.
    """
    text = upload_context_text(message)
    if text is None:
        return message
    metadata = message.additional_kwargs[UPLOAD_CONTEXT_KEY]
    already_projected = metadata.get("projected") is True
    if already_projected and (not sanitized or metadata.get("sanitized") is True):
        return message
    kwargs = deepcopy(message.additional_kwargs)
    kwargs[UPLOAD_CONTEXT_KEY]["projected"] = True
    if sanitized:
        kwargs[UPLOAD_CONTEXT_KEY]["sanitized"] = True
    elif not already_projected:
        kwargs[UPLOAD_CONTEXT_KEY].pop("sanitized", None)
    content = deepcopy(message.content)
    if not already_projected:
        if isinstance(content, str):
            content = f"{text}\n\n{content}"
        else:
            content = [{"type": "text", "text": f"{text}\n\n"}, *content]
    return message.model_copy(update={"content": content, "additional_kwargs": kwargs})


def project_upload_contexts(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Build a transient view without changing IDs, order or stored messages."""
    return [project_upload_context(message) for message in messages]
