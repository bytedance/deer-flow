"""Who produced a message, declared by the producer.

DeerFlow's middleware chain injects and rewrites messages: a date reminder, a
recalled-memory block, a compaction summary, a durable-context data block, an
image payload, an activated skill body. By the time any of those reach the
model-call boundary, the component that produced them is no longer recoverable
from the message itself — an observer would have to infer it from wording,
which breaks the moment a prompt is reworded.

The producing middleware therefore stamps the fact. Keys live here, in the
contract package, rather than in the host: an extension pinned to this contract
version must be able to rely on the facility existing, and only a shared
declaration makes that checkable.

Values are plain strings, not enum members, so an unknown producer from a newer
host degrades to an unrecognised string rather than an import error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MESSAGE_CONTENT_KIND_KEY = "deerflow_content_kind"
MESSAGE_PRODUCER_KIND_KEY = "deerflow_producer_kind"
MESSAGE_PRODUCER_ENTITY_ID_KEY = "deerflow_producer_entity_id"

#: Every key this contract owns. The host treats all of them as server-owned and
#: strips caller-supplied values from untrusted input.
PROVENANCE_KEYS: frozenset[str] = frozenset(
    {
        MESSAGE_CONTENT_KIND_KEY,
        MESSAGE_PRODUCER_KIND_KEY,
        MESSAGE_PRODUCER_ENTITY_ID_KEY,
    }
)


class ContentKind(StrEnum):
    """What a stamped message *is*, independent of which component made it."""

    MIDDLEWARE_INJECTION = "middleware_injection"
    MEMORY = "memory"
    DURABLE_CONTEXT = "durable_context"
    SKILL_BODY = "skill_body"
    IMAGE_PAYLOAD = "image_payload"


@dataclass(frozen=True)
class MessageProvenance:
    content_kind: str
    producer_kind: str
    producer_entity_id: str | None = None


def provenance_kwargs(
    content_kind: str,
    producer_kind: str,
    *,
    producer_entity_id: str | None = None,
) -> dict[str, str]:
    """Build the ``additional_kwargs`` fragment a producer merges into its message.

    Optional fields are omitted rather than written as ``None`` so a stamped
    message carries no keys whose value says nothing.
    """
    kwargs = {
        MESSAGE_CONTENT_KIND_KEY: str(content_kind),
        MESSAGE_PRODUCER_KIND_KEY: str(producer_kind),
    }
    if producer_entity_id is not None:
        kwargs[MESSAGE_PRODUCER_ENTITY_ID_KEY] = str(producer_entity_id)
    return kwargs


def read_provenance(message: object) -> MessageProvenance | None:
    """Return the stamp, or ``None`` when absent or malformed.

    Both required fields must be present strings; a partial or wrongly-typed
    stamp is treated as absent rather than as a half-truth an observer would
    then record as fact.
    """
    kwargs = getattr(message, "additional_kwargs", None)
    if not isinstance(kwargs, dict):
        return None
    content_kind = kwargs.get(MESSAGE_CONTENT_KIND_KEY)
    producer_kind = kwargs.get(MESSAGE_PRODUCER_KIND_KEY)
    if not isinstance(content_kind, str) or not isinstance(producer_kind, str):
        return None
    entity_id = kwargs.get(MESSAGE_PRODUCER_ENTITY_ID_KEY)
    return MessageProvenance(
        content_kind=content_kind,
        producer_kind=producer_kind,
        producer_entity_id=entity_id if isinstance(entity_id, str) else None,
    )
