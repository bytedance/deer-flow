"""Middleware to resolve one-go attachment descriptors into thread uploads.

PoC behavior:
- Reads `additional_kwargs.attachments` from the last HumanMessage.
- Supports `type` in {"trusted_link", "trusted_url", "url"}.
- Fetches bytes from trusted link, stores them into thread-scoped uploads backend,
  and exposes normalized entries in `additional_kwargs.files`.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
from pathlib import Path
from typing import NotRequired, override
from urllib.parse import urlparse

import httpx
from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from src.config.paths import VIRTUAL_PATH_PREFIX
from src.storage import get_thread_file_backend, guess_mime_type, materialize_upload_to_local_cache

logger = logging.getLogger(__name__)


class AttachmentsResolverMiddlewareState(AgentState):
    """State schema compatibility shim."""

    uploaded_files: NotRequired[list[dict] | None]


class AttachmentsResolverMiddleware(AgentMiddleware[AttachmentsResolverMiddlewareState]):
    """Resolve trusted-link attachments into canonical thread uploads.

    This middleware allows a one-call PoC flow where downstream provides
    attachment descriptors directly in run input.
    """

    state_schema = AttachmentsResolverMiddlewareState

    def __init__(self) -> None:
        super().__init__()
        self._max_bytes = max(1024 * 1024, int(os.getenv("TRUSTED_LINK_MAX_BYTES", str(20 * 1024 * 1024))))
        self._timeout_seconds = max(1, int(os.getenv("TRUSTED_LINK_TIMEOUT_SECONDS", "15")))
        self._allow_http = os.getenv("TRUSTED_LINK_ALLOW_HTTP", "false").lower() == "true"

    def _is_public_hostname(self, hostname: str) -> bool:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False

        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                return False
        return True

    def _safe_filename(self, filename: str | None, source_url: str, index: int) -> str:
        if filename:
            candidate = Path(filename).name
        else:
            candidate = Path(urlparse(source_url).path).name

        if not candidate:
            candidate = f"attachment_{index}"

        if candidate in {".", ".."}:
            candidate = f"attachment_{index}"

        return candidate

    def _fetch_bytes(self, url: str) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme not in ({"https", "http"} if self._allow_http else {"https"}):
            raise RuntimeError(f"Unsupported trusted link scheme: {parsed.scheme}")
        if not parsed.hostname or not self._is_public_hostname(parsed.hostname):
            raise RuntimeError("Trusted link host is not allowed")

        total = 0
        chunks: list[bytes] = []
        with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > self._max_bytes:
                        raise RuntimeError("Trusted link exceeds max size")
                    chunks.append(chunk)

        return b"".join(chunks)

    @override
    def before_agent(self, state: AttachmentsResolverMiddlewareState, runtime: Runtime) -> dict | None:
        thread_id = runtime.context.get("thread_id")
        if not thread_id:
            return None

        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_index = len(messages) - 1
        last_message = messages[last_index]
        if not isinstance(last_message, HumanMessage):
            return None

        kwargs = dict(last_message.additional_kwargs or {})
        attachments = kwargs.get("attachments")
        if not isinstance(attachments, list) or not attachments:
            return None

        uploads_backend = get_thread_file_backend("uploads")

        existing_files_raw = kwargs.get("files")
        existing_files = existing_files_raw if isinstance(existing_files_raw, list) else []
        merged_by_filename: dict[str, dict] = {f.get("filename"): f for f in existing_files if isinstance(f, dict) and f.get("filename")}

        resolved_count = 0
        for index, descriptor in enumerate(attachments):
            if not isinstance(descriptor, dict):
                continue

            source_type = str(descriptor.get("type") or descriptor.get("kind") or "").lower()
            if source_type not in {"trusted_link", "trusted_url", "url"}:
                continue

            source_url = descriptor.get("url") or descriptor.get("trusted_url")
            if not isinstance(source_url, str) or not source_url.strip():
                raise RuntimeError("trusted_link attachment requires non-empty url")

            filename = self._safe_filename(descriptor.get("filename"), source_url, index)
            content = self._fetch_bytes(source_url)

            virtual_path = f"{VIRTUAL_PATH_PREFIX}/uploads/{filename}"
            uploads_backend.put_virtual_file(thread_id, virtual_path, content)

            try:
                materialize_upload_to_local_cache(thread_id, virtual_path)
            except Exception:
                logger.info("Trusted link resolved durably but local pre-materialization failed for %s", filename)

            merged_by_filename[filename] = {
                "filename": filename,
                "size": len(content),
                "path": virtual_path,
                "mime_type": descriptor.get("mime_type") or guess_mime_type(filename) or "application/octet-stream",
                "status": "resolved",
                "source_type": source_type,
            }
            resolved_count += 1

        if resolved_count == 0:
            return None

        kwargs["files"] = list(merged_by_filename.values())
        updated_message = HumanMessage(content=last_message.content, id=last_message.id, additional_kwargs=kwargs)
        messages[last_index] = updated_message

        return {"messages": messages}
