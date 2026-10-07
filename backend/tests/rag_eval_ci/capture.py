"""In-process recording of the extension's outbound model calls (§8.2 备料).

Installs one wrapper over ``httpx.AsyncClient.send`` for the duration of the
recording pass: every POST that matches a recorded call kind is captured as
``(key, response)`` and appended to the JSONL fixture. Everything else (the
DB, Qdrant, file IO, the parse of local formats) runs untouched — the pass is
the real pipeline against the real services, only observed.

Used by ``scripts/rag_eval_record.py``; the replay side lives in ``replay.py``
and must agree on ``key_for_request`` (they share it by construction).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import httpx

from rag_eval_ci.replay import UnsupportedReplayRequest, describe_request, key_for_request, rerank_documents_for_entry, round_floats


class Recorder:
    """Collects ``{key: entry}`` entries from observed outbound calls."""

    def __init__(self) -> None:
        self.entries: dict[str, dict[str, Any]] = {}

    async def observe(self, request: httpx.Request, response: httpx.Response) -> None:
        if request.method.upper() != "POST" or not request.content:
            return
        try:
            body = json.loads(request.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if not isinstance(body, dict):
            return
        try:
            key = key_for_request(request.url.path, body)
        except UnsupportedReplayRequest:
            return  # not a recorded call kind (never guessed at)
        if response.status_code >= 400:
            print(f"rag-eval-record note: non-2xx ({response.status_code}) for {request.url.path}; not recorded", file=sys.stderr)
            return
        if not response.is_closed:
            await response.aread()
        try:
            payload = response.json()
        except ValueError:
            return
        entry: dict[str, Any] = {"key": key, "path": request.url.path, "digest": describe_request(request.url.path, body), "response": round_floats(payload)}
        documents = rerank_documents_for_entry(request.url.path, body)
        if documents is not None:
            # The response's indices point into this order — stored so the replay
            # can remap them onto a differently-ordered (tied-score) request.
            entry["documents"] = documents
        existing = self.entries.get(key)
        if existing is not None and existing["response"] != entry["response"]:
            raise ValueError(f"recording conflict for {request.url.path}: two different responses observed for one input")
        self.entries[key] = entry

    def write(self, path: str | Path) -> int:
        import gzip

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(self.entries[key], ensure_ascii=False, sort_keys=True) + "\n" for key in sorted(self.entries)]
        if target.suffix == ".gz":
            with gzip.GzipFile(target, "wb", mtime=0) as handle:
                handle.write("".join(lines).encode("utf-8"))
        else:
            with target.open("w", encoding="utf-8", newline="\n") as handle:
                handle.writelines(lines)
        return len(self.entries)


def install(recorder: Recorder) -> None:
    """Wrap ``httpx.AsyncClient.send`` process-wide (call before the pass)."""
    original = httpx.AsyncClient.send

    async def send(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        response = await original(self, request, **kwargs)
        try:
            await recorder.observe(request, response)
        except Exception as exc:  # noqa: BLE001 — capture must never sink the recording run
            print(f"rag-eval-record note: capture skipped for {request.url.path} ({type(exc).__name__}: {exc})", file=sys.stderr)
        return response

    httpx.AsyncClient.send = send  # type: ignore[method-assign]
