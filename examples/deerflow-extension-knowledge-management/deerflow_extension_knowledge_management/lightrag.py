"""Optional LightRAG v1.5.7 entity graph projection for the knowledge center.

Each operator connection binds one server workspace, addressed as `workspace`.
No cross-dataset filtering, workspace header, ingestion or full-graph claim.
"""

import asyncio
import hashlib
import json
import os

import httpx
from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from .contracts import Capabilities, ManagementCredentialUnavailable, Model
from .library import Entity, Evidence, Graph, LibraryQuery, LibraryResult, Relation
from .weknora import Grant
from .weknora_library import rows, text


def graph_id(conn, value):
    key = os.environ.get(conn.api_key_env, "").strip()
    if not isinstance(value, str) or not value or len(value) > 500 or (key and key in value):
        raise RuntimeError("Graph identity cannot be safely represented")
    return value


class Connection(Model):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    base_url: AnyHttpUrl
    api_key_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    grants: tuple[Grant, ...] = Field(min_length=1)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value):
        if value.username is not None or value.password is not None or value.query is not None or value.fragment is not None:
            raise ValueError("Connection URL cannot contain credentials, query or fragment")
        return value

    @model_validator(mode="after")
    def workspace(self):
        if any(set(g.knowledge_base_ids) != {"workspace"} or not g.operations <= {"capabilities", "graph"} for g in self.grants):
            raise ValueError("LightRAG library grants address only the configured workspace graph")
        return self


class Settings(Model):
    connections: tuple[Connection, ...] = Field(min_length=1, max_length=20)
    timeout: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique(self):
        if len({c.id for c in self.connections}) != len(self.connections):
            raise ValueError("Duplicate connection ID")
        return self


class LightRAGLibrary:
    def __init__(self, config, *, transport=None):
        self.settings = Settings.model_validate(config)
        self.transport = transport

    def _authorize(self, context, connection, base, operation):
        caller = context.principal
        if caller.is_admin and not caller.is_internal and base == "workspace":
            for conn in self.settings.connections:
                if conn.id == connection and any(g.user_id == caller.user_id and operation in g.operations for g in conn.grants):
                    return conn
        raise PermissionError("Graph operation is not granted for this workspace")

    async def capabilities(self, context, connection, base):
        conn = self._authorize(context, connection, base, "capabilities")
        operations = frozenset(op for grant in conn.grants if grant.user_id == context.principal.user_id for op in grant.operations)
        return Capabilities(operations=operations, processing_options=frozenset(), pipeline={"entity_relations": "provider_managed"})

    async def library(self, context, connection, base, operation, query):
        conn = self._authorize(context, connection, base, operation)
        if operation != "graph":
            raise NotImplementedError("Only graph queries are supported")
        query = LibraryQuery.model_validate(query)
        if not query.search.strip():
            raise ValueError("A graph query is required")
        key = os.environ.get(conn.api_key_env, "").strip()
        if not key or not key.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in key):
            raise ManagementCredentialUnavailable("Graph credential is unavailable")
        try:
            async with await asyncio.to_thread(httpx.AsyncClient, base_url=str(conn.base_url).rstrip("/"), headers={"X-API-Key": key}, follow_redirects=False, timeout=self.settings.timeout, transport=self.transport) as client:
                async with client.stream("POST", "/query/data", json={"query": query.search.strip(), "mode": "hybrid", "top_k": 50, "chunk_top_k": 50}) as response:
                    if response.status_code in {401, 403}:
                        raise PermissionError("Graph provider denied access")
                    if response.status_code != 200:
                        raise RuntimeError("Graph query failed")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > 4 * 1024 * 1024:
                            raise RuntimeError("Graph response exceeds limit")
                        raw.extend(chunk)
                    payload = json.loads(raw)
        except (httpx.HTTPError, ValueError):
            raise RuntimeError("Graph response unavailable") from None
        if not isinstance(payload, dict) or payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
            raise RuntimeError("Invalid graph response")
        data = payload["data"]
        try:
            evidence = {}
            for row in rows(data.get("chunks"), 100):
                item = Evidence(id=graph_id(conn, row.get("chunk_id")), content=text(conn, row.get("content"), 100_000))
                if item.id in evidence:
                    raise RuntimeError("Ambiguous graph evidence")
                evidence[item.id] = item
            entities = {}
            for row in rows(data.get("entities"), 100):
                item = Entity(id=graph_id(conn, row.get("entity_name")), description=text(conn, row.get("description"), 10000))
                if item.id in entities:
                    raise RuntimeError("Ambiguous graph entity")
                entities[item.id] = item
            relations = []
            for row in rows(data.get("relationships"), 100):
                source, target = graph_id(conn, row.get("src_id")), graph_id(conn, row.get("tgt_id"))
                # Endpoints named by real edges are real returned identities.
                for endpoint in (source, target):
                    entities.setdefault(endpoint, Entity(id=endpoint))
                ids = row.get("source_id")
                ids = tuple(key for key in dict.fromkeys(ids.split("<SEP>")) if key in evidence) if isinstance(ids, str) else ()
                relations.append(Relation(source=source, target=target, description=text(conn, row.get("description"), 10000), evidence_ids=ids))
            graph = Graph(entities=tuple(entities.values()), relations=relations, evidence=tuple(evidence.values()))
        except ValueError:
            raise RuntimeError("Invalid graph rows") from None
        dataset = "lr1_" + hashlib.sha256(json.dumps([str(conn.base_url).rstrip("/"), "workspace"], ensure_ascii=False).encode()).hexdigest()
        return LibraryResult(provider="lightrag", connection_id=connection, dataset_id=dataset, title="LightRAG", graph=graph)
