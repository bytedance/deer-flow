"""Bounded source-artifact forwarding across ordinary subagent results."""

from collections.abc import Mapping
from typing import Any


def cited_source_artifact(messages: list[dict[str, Any]], content: str) -> dict[str, Any] | None:
    """Carry only actual captured sources cited in the child's final result."""
    sources: dict[str, dict[str, Any]] = {}
    remaining = 1_000_000
    for message in messages:
        if message.get("type") != "tool" or message.get("name") not in {"knowledge_search", "task"}:
            continue
        artifact = message.get("artifact")
        payload = artifact.get("knowledge_sources") if isinstance(artifact, Mapping) else None
        if not isinstance(payload, Mapping) or payload.get("version") != 1:
            continue
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list):
            continue
        for source in raw_sources[:100]:
            if not isinstance(source, dict):
                continue
            source_id = source.get("id")
            text = source.get("text")
            if not isinstance(source_id, str) or not isinstance(text, str) or f"](#knowledge-{source_id})" not in content:
                continue
            if source_id in sources:
                continue
            if len(sources) >= 100 or len(text) > remaining:
                continue
            sources[source_id] = dict(source)
            remaining -= len(text)
    return {"knowledge_sources": {"version": 1, "sources": list(sources.values())}} if sources else None
