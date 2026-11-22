"""WeKnora v0.8.3 ingestion adapter. API mapping informed by superbuzzy's
community/weknora/documents.py; authorization is explicit and request-local.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from typing import Literal

import httpx
from pydantic import AnyHttpUrl, Field, field_validator, model_validator

from .contracts import Capabilities, IngestRequest, ManagementContext, ManagementCredentialUnavailable, Model, Operation, ProcessingOptions, ProcessingResult

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 16 * 1024 * 1024


def resource_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("Invalid resource ID")
    return value


class Grant(Model):
    user_id: str = Field(min_length=1)
    knowledge_base_ids: tuple[str, ...] = Field(min_length=1)
    operations: frozenset[Operation] = Field(min_length=1)

    @model_validator(mode="after")
    def exact(self):
        if self.user_id != self.user_id.strip():
            raise ValueError("Use exact host user identities")
        for base in self.knowledge_base_ids:
            resource_id(base)
        return self


class Connection(Model):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    base_url: AnyHttpUrl
    tenant_id: str = Field(pattern=r"^[1-9][0-9]{0,19}$")
    api_key_env: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    grants: tuple[Grant, ...] = Field(min_length=1)

    @field_validator("base_url")
    @classmethod
    def safe_url(cls, value):
        if value.username is not None or value.password is not None or value.query is not None or value.fragment is not None:
            raise ValueError("Connection URL must not contain credentials, query or fragment")
        return value


class Settings(Model):
    connections: tuple[Connection, ...] = Field(min_length=1, max_length=20)
    timeout: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique(self):
        if len({c.id for c in self.connections}) != len(self.connections):
            raise ValueError("Duplicate connection ID")
        return self


class WeKnoraManagement:
    def __init__(self, config: dict, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = Settings.model_validate(config)
        self.transport = transport

    def _authorize(self, context: ManagementContext, connection: str, base: str, operation: Operation) -> Connection:
        principal = context.principal
        if not principal.is_admin or principal.is_internal:
            raise PermissionError("Management requires an explicitly bound administrator")
        for conn in self.settings.connections:
            if conn.id == connection:
                if any(g.user_id == principal.user_id and base in g.knowledge_base_ids and operation in g.operations for g in conn.grants):
                    resource_id(base)
                    return conn
        raise PermissionError("Management operation is not granted for this resource")

    async def _request(self, conn: Connection, method: str, path: str, **kwargs):
        key = os.environ.get(conn.api_key_env, "").strip()
        if not key or not key.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in key):
            raise ManagementCredentialUnavailable("Management credential is unavailable")
        try:
            async with await asyncio.to_thread(
                httpx.AsyncClient,
                base_url=str(conn.base_url).rstrip("/"),
                headers={"X-API-Key": key, "X-Tenant-ID": conn.tenant_id},
                follow_redirects=False,
                timeout=self.settings.timeout,
                transport=self.transport,
            ) as client:
                async with client.stream(method, path, **kwargs) as response:
                    if response.status_code in {401, 403}:
                        raise PermissionError("Provider denied management access")
                    if response.status_code == 404:
                        raise FileNotFoundError("Provider resource is unavailable")
                    if response.status_code == 409:
                        raise FileExistsError("Provider reported a resource conflict")
                    if response.status_code not in {200, 201, 202}:
                        logger.warning("Knowledge management provider request failed: status=%d", response.status_code)
                        raise RuntimeError("Provider request failed; reconcile state before retrying a write")
                    raw = bytearray()
                    async for part in response.aiter_bytes():
                        if len(raw) + len(part) > 4 * 1024 * 1024:
                            logger.warning("Knowledge management provider request failed: response_too_large")
                            raise RuntimeError("Provider response exceeds limit")
                        raw.extend(part)
                    payload = json.loads(raw)
        except (httpx.HTTPError, ValueError) as exc:
            # Never log exception text, request URLs, response bodies or chains.
            logger.warning("Knowledge management provider request failed: %s", type(exc).__name__)
            raise RuntimeError("Provider response unavailable; reconcile state before retrying a write") from None
        if not isinstance(payload, dict) or payload.get("success") is not True or not isinstance(payload.get("data"), dict):
            logger.warning("Knowledge management provider request failed: invalid_envelope")
            raise RuntimeError("Invalid provider response")
        return payload["data"]

    async def _base(self, conn: Connection, base: str) -> dict:
        data = await self._request(conn, "GET", f"/api/v1/knowledge-bases/{base}")
        if data.get("id") != base:
            raise PermissionError("Provider returned a different knowledge base")
        return data

    def _result(self, conn: Connection, base: str, data: dict, document: str | None = None) -> ProcessingResult:
        if data.get("knowledge_base_id") != base or (document is not None and data.get("id") != document):
            raise PermissionError("Provider returned a document outside the requested resource")
        try:
            doc_id = resource_id(data.get("id"))
        except ValueError:
            raise RuntimeError("Invalid provider document ID") from None
        raw = data.get("parse_status")
        if not isinstance(raw, str) or len(raw) > 64 or not re.fullmatch(r"[a-z_]+", raw):
            raise RuntimeError("Invalid provider processing state")
        key = os.environ.get(conn.api_key_env, "").strip()
        if key and (key in doc_id or key in raw):
            raise RuntimeError("Invalid provider document metadata")
        states = {"pending": "queued", "unprocessed": "queued", "processing": "running", "parsing": "running", "finalizing": "running", "completed": "completed", "failed": "failed", "cancelled": "cancelled"}
        identity = [str(conn.base_url).rstrip("/"), conn.tenant_id, base]
        dataset = "wk1_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        return ProcessingResult(
            provider="weknora", connection_id=conn.id, dataset_id=dataset, document_id=doc_id, state=states.get(raw, "unknown"), provider_state=raw, searchable=raw in {"completed", "finalizing"} and data.get("enable_status") == "enabled"
        )

    async def _document(self, conn: Connection, base: str, document: str) -> ProcessingResult:
        data = await self._request(conn, "GET", f"/api/v1/knowledge/{resource_id(document)}")
        return self._result(conn, base, data, document)

    @staticmethod
    def _options(options: ProcessingOptions, base: dict) -> dict:
        capabilities = base.get("capabilities", {})
        if options.graph_enabled is True and (not isinstance(capabilities, dict) or capabilities.get("graph") is not True):
            raise NotImplementedError("Graph extraction is not enabled for this knowledge base")
        result = options.model_dump(exclude_none=True, exclude={"chunk_size", "chunk_overlap"})
        if options.chunk_size is not None:
            existing = base.get("chunking_config")
            if not isinstance(existing, dict):
                raise RuntimeError("Invalid provider chunking configuration")
            if existing.get("enable_parent_child") is True:
                raise NotImplementedError("Chunk overrides are unsupported in parent-child mode")
            # v0.8.3 merges nonzero integers but treats enable_parent_child as
            # authoritative even when omitted. Preserve its full base snapshot.
            if options.chunk_overlap == 0 and existing.get("chunk_overlap") != 0:
                raise NotImplementedError("This provider cannot override nonzero overlap with zero")
            result["chunking_config"] = {**existing, "chunk_size": options.chunk_size, "chunk_overlap": options.chunk_overlap}
        return result

    async def capabilities(self, context: ManagementContext, connection: str, base: str) -> Capabilities:
        conn = self._authorize(context, connection, base, "capabilities")
        data = await self._base(conn, base)
        flags = data.get("capabilities")
        if not isinstance(flags, dict):
            raise RuntimeError("Invalid provider capabilities")
        operations = frozenset(op for g in conn.grants if g.user_id == context.principal.user_id and base in g.knowledge_base_ids for op in g.operations)
        pipeline = {
            "parse": "provider_managed",
            "chunk": "provider_managed",
            "vector": "provider_managed" if flags.get("vector") is True else "unsupported",
            "entries": "provider_managed" if flags.get("wiki") is True else "unsupported",
            "entity_relations": "provider_managed" if flags.get("graph") is True else "unsupported",
        }
        options = {"summary_enabled"}
        if flags.get("graph") is True:
            options.add("graph_enabled")
        chunking = data.get("chunking_config")
        if isinstance(chunking, dict) and chunking.get("enable_parent_child") is not True:
            options.update({"chunk_size", "chunk_overlap"})
        return Capabilities(operations=operations, processing_options=frozenset(options), pipeline=pipeline)

    async def ingest(self, context: ManagementContext, connection: str, base: str, body: IngestRequest) -> ProcessingResult:
        conn = self._authorize(context, connection, base, body.kind)
        config = self._options(body.processing, await self._base(conn, base))
        payload = {"title": body.title, "process_config": config}
        if body.kind == "manual":
            payload.update(content=body.content, status="publish")
        else:
            payload["url"] = str(body.url)
        data = await self._request(conn, "POST", f"/api/v1/knowledge-bases/{base}/knowledge/{body.kind}", json=payload)
        return self._result(conn, base, data)

    async def upload(self, context: ManagementContext, connection: str, base: str, filename: str, content: bytes, options: ProcessingOptions) -> ProcessingResult:
        conn = self._authorize(context, connection, base, "upload")
        if not content or len(content) > MAX_UPLOAD_BYTES or not filename or len(filename) > 255 or any(c in '/\\"' or ord(c) < 32 or ord(c) == 127 for c in filename) or filename in {".", ".."}:
            raise ValueError("Invalid file name or upload size")
        config = self._options(options, await self._base(conn, base))
        data = await self._request(conn, "POST", f"/api/v1/knowledge-bases/{base}/knowledge/file", files={"file": (filename, content, "application/octet-stream")}, data={"process_config": json.dumps(config)})
        return self._result(conn, base, data)

    async def status(self, context: ManagementContext, connection: str, base: str, document: str) -> ProcessingResult:
        conn = self._authorize(context, connection, base, "status")
        await self._base(conn, base)
        return await self._document(conn, base, document)

    async def process(self, context: ManagementContext, connection: str, base: str, document: str, action: Literal["reprocess", "cancel"], options: ProcessingOptions) -> ProcessingResult:
        if action not in {"reprocess", "cancel"}:
            raise NotImplementedError("Unsupported processing operation")
        conn = self._authorize(context, connection, base, action)
        if action == "cancel" and options.model_fields_set:
            raise ValueError("Cancel does not accept processing options")
        config = self._options(options, await self._base(conn, base))
        await self._document(conn, base, document)
        suffix = "reparse" if action == "reprocess" else "cancel-parse"
        # Omit empty overrides: upstream retains the original processing policy.
        kwargs = {"json": {"process_config": config}} if config else {}
        data = await self._request(conn, "POST", f"/api/v1/knowledge/{document}/{suffix}", **kwargs)
        return self._result(conn, base, data, document)
