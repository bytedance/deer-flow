"""Stable UI identity of a persisted message.

The thread feed (``run_events``) and the checkpoint hold the same message under
the same id, so a client can align them — but only if both sides agree on what
"same message" means. This is the backend half of that rule; the frontend half
is ``messageIdentity`` in ``frontend/src/core/threads/hooks.ts``. The two must
stay in sync: a mismatch is silent, degrading placement rather than raising.

Two normalizations matter:

* a ``ToolMessage`` is identified by its ``tool_call_id``, not its own id —
  that is the id both sides can always resolve;
* ``DynamicContextMiddleware`` re-keys the submitted user turn from ``X`` to
  ``X__user`` (giving ``X`` to the injected reminder), so the two human copies
  must collapse to one identity.
"""

from collections.abc import Mapping
from typing import Any

from deerflow.utils.messages import strip_injected_user_message_id_suffix

__all__ = ["MESSAGE_SEQ_KEY", "attach_message_seq", "message_identity"]

#: ``additional_kwargs`` key carrying a message's thread-feed seq to clients.
#: Server-owned display metadata: it is attached when a frame is serialized and
#: must be stripped from anything a client sends back, or a replayed message
#: would write it into the checkpoint (where a fork re-seeds and reassigns seq).
MESSAGE_SEQ_KEY = "deerflow_seq"


def message_identity(message: Mapping[str, Any]) -> str | None:
    """Return the stable identity of *message*, or ``None`` if it has none.

    *message* is a serialized message mapping (as stored in ``run_events``
    content or carried in a checkpoint ``values`` frame), not a ``BaseMessage``.
    """
    tool_call_id = message.get("tool_call_id")
    if isinstance(tool_call_id, str) and tool_call_id:
        return f"tool:{tool_call_id}"

    message_id = message.get("id")
    if not isinstance(message_id, str) or not message_id:
        return None

    # Only human copies collapse: a hidden SystemMessage legitimately reuses the
    # original id, and merging it with the visible turn would hide the turn.
    if message.get("type") == "human":
        message_id = strip_injected_user_message_id_suffix(message_id) or message_id
    return f"message:{message_id}"


def attach_message_seq(message: Mapping[str, Any], seq: int) -> dict[str, Any]:
    """Return a shallow copy of *message* with *seq* under ``MESSAGE_SEQ_KEY``.

    The one stamping expression shared by the worker's run-scoped stamper and
    the request-scoped ``stamp_messages_with_seq``, so the two counterparts of
    the same rule cannot silently diverge. The input is never mutated.
    """
    return {**message, "additional_kwargs": {**(message.get("additional_kwargs") or {}), MESSAGE_SEQ_KEY: seq}}
