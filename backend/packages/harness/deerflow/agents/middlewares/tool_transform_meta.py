"""Structured transform-trail metadata for tool results.

Middlewares that rewrite a ToolMessage between the raw callable boundary and
the model-visible result append a declared entry here, so observers classify
raw→visible transforms from facts instead of sniffing output wording.
Entries are additive and ordered by application: the last entry produced the
final visible bytes.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages.content import KNOWN_BLOCK_TYPES

TOOL_TRANSFORMS_KEY = "deerflow_tool_transforms"
_SHA256_HEX_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


def append_tool_transform(additional_kwargs: dict, kind: str, *, by: str, version: str = "1", source_sha256: str | None = None) -> None:
    """Append one transform entry.

    ``source_sha256`` names the content the transform replaced, for observers
    that compare results across calls: a replacement can embed per-call data
    (an externalized file path, for example), so its bytes are not a stable
    identity for the output the tool returned.
    """
    trail = additional_kwargs.get(TOOL_TRANSFORMS_KEY)
    if not isinstance(trail, list):
        trail = []
    entry = {"kind": kind, "by": by, "version": version}
    if source_sha256 is not None:
        entry["source_sha256"] = source_sha256
    additional_kwargs[TOOL_TRANSFORMS_KEY] = [*trail, entry]


def read_tool_transforms(message: object) -> tuple[dict[str, str], ...]:
    kwargs = getattr(message, "additional_kwargs", None)
    trail = kwargs.get(TOOL_TRANSFORMS_KEY) if isinstance(kwargs, dict) else None
    if not isinstance(trail, list):
        return ()
    return tuple(entry for entry in trail if isinstance(entry, dict) and isinstance(entry.get("kind"), str))


def tool_result_source_digest(message: object) -> str | None:
    """Digest of the content the first recorded content replacement started from."""
    for entry in read_tool_transforms(message):
        digest = entry.get("source_sha256")
        if isinstance(digest, str) and len(digest) == _SHA256_HEX_LENGTH and set(digest) <= _HEX_DIGITS:
            return digest
    return None


def tool_content_fingerprint(content: Any) -> str:
    """sha256 of ToolMessage content without per-call block identity.

    langchain-core's ``create_*_block`` helpers (used by every MCP result
    conversion) stamp a fresh ``lc_<uuid>`` id on each content block, so two
    identical results never serialize the same. Those ids are not tool data.
    Only standard content blocks lose their ``id``: in any other dict it can be
    the data that changed.
    """
    if isinstance(content, list):
        content = [_without_block_id(block) for block in content]
    return hashlib.sha256(json.dumps(content, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _without_block_id(block: Any) -> Any:
    block_type = block.get("type") if isinstance(block, dict) else None
    if not isinstance(block_type, str) or block_type not in KNOWN_BLOCK_TYPES:
        return block
    return {key: value for key, value in block.items() if key != "id"}
