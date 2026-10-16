"""Shared message plumbing for providers that preserve a reasoning string.

``patched_mimo`` and ``patched_stepfun`` both wrap ``ChatOpenAI`` so a provider's
``reasoning_content`` survives multi-turn tool calls, and each carried a
byte-identical copy of the two mechanical steps that job needs: attach a
reasoning string to a LangChain message without mutating the message the caller
still holds, and read ``choices[index].message`` out of a response object that
may not be shaped like that at all (dict payloads, SDK objects, or a chunk with
no choices).

How a provider *finds* its reasoning field stays local on purpose: MiMo reads
``reasoning_content`` through ``_extract_reasoning_content``, StepFun reads both
``reasoning`` and ``reasoning_content`` through ``_extract_reasoning``, and
``patched_minimax`` merges streamed deltas. Those are provider dialects, not this
rule. This module owns only what the two copies already agreed on, so a fix to
the attach-without-mutating rule lands once instead of per provider.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk


def with_reasoning_content(message: AIMessage | AIMessageChunk, reasoning: str) -> AIMessage | AIMessageChunk:
    """Return a copy of ``message`` carrying ``reasoning`` in ``additional_kwargs``.

    The incoming message is never modified: LangChain hands the same object to
    callbacks, run journals and the caller's history, so an in-place write would
    leak reasoning into a message that was already emitted. A copy is returned
    whether or not the value changed, keeping the result's identity predictable
    for callers that replay messages through ``model_copy``.
    """
    additional_kwargs = dict(message.additional_kwargs)
    if additional_kwargs.get("reasoning_content") != reasoning:
        additional_kwargs["reasoning_content"] = reasoning
    return message.model_copy(update={"additional_kwargs": additional_kwargs})


def typed_choice_message(response: Any, index: int) -> Any:
    """Return ``response.choices[index].message`` when that shape exists, else ``None``.

    Non-streaming results arrive either as a dict payload (no attribute access)
    or as an SDK object whose choice list may be shorter than the index the
    caller is replaying. Neither case is an error for the callers here: they
    fall back to the payload they already have, so this reports "nothing typed"
    rather than raising.
    """
    choices = getattr(response, "choices", None)
    if choices is None:
        return None
    try:
        return choices[index].message
    except (AttributeError, IndexError, TypeError):
        return None
