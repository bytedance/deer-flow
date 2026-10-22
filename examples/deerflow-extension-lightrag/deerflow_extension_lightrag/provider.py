"""LightRAG v1.5.7 /query/data adapter; graph summaries are not document evidence."""

from __future__ import annotations

import asyncio
import json
import os

import httpx
from deerflow.community.lightrag.formatting import normalize_retrieval_result
from deerflow.community.provider_credentials import reject_url_userinfo
from deerflow.knowledge import KnowledgeCapabilities, KnowledgeRequestContext, RetrievalHit, RetrievalResult
from deerflow.knowledge.providers import validate_scope_capabilities
from deerflow.knowledge.sources import redact_strings
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: AnyHttpUrl
    api_key_env: str = Field(min_length=1)
    user_ids: list[str] = Field(min_length=1, max_length=1000)
    agent_names: list[str] | None = None
    timeout: float = Field(default=30, gt=0, le=120)
    top_k: int = Field(default=20, ge=1, le=100)

    @field_validator("timeout", "top_k", mode="before")
    @classmethod
    def reject_boolean_numbers(cls, value: object, info: ValidationInfo) -> object:
        if isinstance(value, bool):
            raise ValueError(f"{info.field_name} must not be a boolean")
        return value

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        return reject_url_userinfo(value)


def _rows(data: dict, key: str) -> list[dict]:
    value = data.get(key, [])
    if not isinstance(value, list) or len(value) > 1000 or any(not isinstance(item, dict) for item in value):
        raise ValueError("Invalid LightRAG retrieval rows")
    return value


def _text(value: object) -> str:
    return value.strip()[:10_000] if isinstance(value, str) else ""


def normalize_relations(data: dict) -> RetrievalResult:
    """Keep returned one-edge paths; join source_id only to actual chunk IDs.

    LightRAG stores multiple IDs with <SEP>. Never treat file_path on an edge
    as a document quotation or infer extra edges from co-occurring entities.
    """
    chunks = {}
    for chunk in _rows(data, "chunks"):
        chunk_id = chunk.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id:
            if chunk_id in chunks:
                raise ValueError("Ambiguous LightRAG chunk identity")
            chunks[chunk_id] = chunk
    references = _rows(data, "references")
    hits = []
    evidence_positions = {}
    for relation in _rows(data, "relationships"):
        source, target = _text(relation.get("src_id")), _text(relation.get("tgt_id"))
        if not source or not target:
            continue
        description = _text(relation.get("description"))
        path = f"Upstream relation (one edge): {source} — {target}\n{description}"
        ids = relation.get("source_id")
        evidence_ids = [key for key in dict.fromkeys(ids.split("<SEP>")) if key in chunks] if isinstance(ids, str) else []
        positions = []
        evidence_omitted = False
        for key in evidence_ids:
            if key not in evidence_positions:
                normalized = normalize_retrieval_result({"chunks": [chunks[key]], "references": references})
                if not normalized.hits:
                    continue
                # Reserve one hit for the edge and one for the bounded-view note.
                if len(hits) >= 98:
                    evidence_omitted = True
                    break
                hits.append(normalized.hits[0])
                evidence_positions[key] = len(hits)
            positions.append(evidence_positions[key])
        if positions:
            # Evidence precedes its users, so prefix budgeting cannot leave an
            # emitted edge referring to a chunk omitted by the shared formatter.
            evidence_refs = ", ".join(f"result [{position}]" for position in positions)
            hits.append(RetrievalHit(content=f"Evidence: {evidence_refs}.\n{path}"))
        elif evidence_omitted:
            hits.append(RetrievalHit(content=path + "\nEvidence omitted for this edge: bounded view."))
        else:
            hits.append(RetrievalHit(content=path + "\nNo retrieved document evidence for this edge."))
        if len(hits) >= 99:
            break
    for entity in _rows(data, "entities"):
        if len(hits) >= 99:
            break
        name = _text(entity.get("entity_name"))
        if name:
            hits.append(RetrievalHit(content=f"Upstream entity: {name}\n{_text(entity.get('description'))}"))
    if hits:
        hits = hits[:99]
        hits.append(RetrievalHit(content="Graph retrieval is a bounded view of upstream data, not a complete graph or proof that other relations are absent."))
    return RetrievalResult(hits=hits)


class LightRAGProvider:
    capabilities = KnowledgeCapabilities(operations={"search", "sources", "relations_search"})

    def __init__(self, config: dict, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = Settings.model_validate(config)
        self._transport = transport

    async def search(self, query: str) -> RetrievalResult:
        raise PermissionError("LightRAG requires a trusted request context")

    async def _data(self, query: str, context: KnowledgeRequestContext) -> dict:
        if context.user_id not in self.settings.user_ids or (self.settings.agent_names is not None and context.agent_name not in self.settings.agent_names):
            raise PermissionError("No LightRAG binding for this identity")
        if context.scope is not None:
            scope = validate_scope_capabilities(context.scope, self.capabilities)
            if scope["mode"] == "disabled":
                raise ValueError("Knowledge retrieval is disabled")
        if not query.strip():
            raise ValueError("Empty query")
        key = os.getenv(self.settings.api_key_env, "").strip()
        if not key or not key.isascii() or any(ord(char) < 33 or ord(char) == 127 for char in key):
            raise ValueError("Missing or invalid LightRAG credential")
        try:
            async with await asyncio.to_thread(httpx.AsyncClient, base_url=str(self.settings.base_url).rstrip("/"), headers={"X-API-Key": key}, timeout=self.settings.timeout, follow_redirects=False, transport=self._transport) as client:
                async with client.stream("POST", "/query/data", json={"query": query.strip(), "mode": "hybrid", "top_k": self.settings.top_k, "chunk_top_k": self.settings.top_k}) as response:
                    if response.status_code in {401, 403}:
                        raise PermissionError("LightRAG denied access")
                    if response.status_code != 200:
                        raise RuntimeError("LightRAG retrieval failed")
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        raw.extend(part)
                        if len(raw) > 4 * 1024 * 1024:
                            raise RuntimeError("LightRAG response is too large")
                    payload = json.loads(raw)
        except (httpx.HTTPError, ValueError):
            raise RuntimeError("LightRAG retrieval failed") from None
        if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            raise RuntimeError("Invalid LightRAG retrieval response")
        return redact_strings(payload["data"], key)

    async def search_scoped(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult:
        return normalize_retrieval_result(await self._data(query, context))

    async def relations_search(self, query: str, *, context: KnowledgeRequestContext) -> RetrievalResult:
        return normalize_relations(await self._data(query, context))
