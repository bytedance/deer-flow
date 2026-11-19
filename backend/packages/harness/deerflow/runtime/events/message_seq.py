"""Attach the thread-global feed seq to serialized checkpoint messages.

The checkpoint holds no seq of its own, so a client merging it with the
seq-ordered feed cannot place a message the loaded page window no longer
reaches back to. The streaming path solves this by stamping `values` frames as
they are published — but a client that merely *opens* a conversation never sees
a frame. It reads the checkpoint over REST, and without a seq there a
summarization-rescued early turn is placed by its nearest anchor instead, which
after compaction sits deep in the loaded page (#4666).

This is the request-scoped counterpart of the worker's stamper: everything the
checkpoint still holds is already persisted, so one batched lookup resolves the
whole list and there is nothing to retry later.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from deerflow.runtime.events.message_identity import attach_message_seq, message_identity

logger = logging.getLogger(__name__)

__all__ = ["stamp_messages_with_seq"]


async def stamp_messages_with_seq(store: Any, thread_id: str, messages: Sequence[Any]) -> list[Any]:
    """Return *messages* with ``MESSAGE_SEQ_KEY`` attached where the feed knows one.

    The input is never mutated: entries that gain a seq are shallow-copied, and
    everything else is passed through as-is. A missing store, an entry that is
    not a mapping, an identity the feed does not know, and a failing lookup all
    degrade to "no seq" rather than raising — placement is an enhancement, and a
    client without it falls back to its own ordering rule.
    """
    if store is None or not messages:
        return list(messages)

    identities = [message_identity(m) if isinstance(m, Mapping) else None for m in messages]
    wanted = {identity for identity in identities if identity is not None}
    if not wanted:
        return list(messages)

    try:
        found = await store.get_message_seqs(thread_id, sorted(wanted))
    except Exception:
        logger.warning("Failed to resolve message seqs for thread %s", thread_id, exc_info=True)
        return list(messages)

    return [attach_message_seq(message, seq) if identity is not None and (seq := found.get(identity)) is not None else message for message, identity in zip(messages, identities, strict=True)]
