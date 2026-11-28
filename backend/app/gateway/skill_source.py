"""Bounded skills.sh snapshot retrieval and install-compatible preflight."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import posixpath
import re
import shutil
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from deerflow.skills.installer import (
    SkillSecurityScanError,
    resolve_and_validate_skill_dir,
    safe_extract_skill_archive,
    scan_archive_preflight_or_raise,
)
from deerflow.skills.security_static_scanner import StaticScanBlockedError, StaticScannerError, enforce_static_scan

_SKILLS_SH_API_BASE = "https://skills.sh/api/v1/skills"
_SKILLS_SH_SITE_BASE = "https://skills.sh"
_SOURCE_CONNECT_TIMEOUT_SECONDS = 3.0
_SOURCE_TOTAL_TIMEOUT_SECONDS = 15.0
_SOURCE_RESPONSE_MAX_BYTES = 12 * 1024 * 1024
SOURCE_FILE_COUNT_LIMIT = 256
SOURCE_FILE_BYTES_LIMIT = 1024 * 1024
SOURCE_TOTAL_BYTES_LIMIT = 8 * 1024 * 1024
SOURCE_ARCHIVE_BYTES_LIMIT = 10 * 1024 * 1024
_SOURCE_REQUESTS_PER_USER_PER_MINUTE = 20
_SOURCE_MAX_CONCURRENT_REQUESTS = 4
_SOURCE_WINDOW_SECONDS = 60.0
_OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")
_REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
_SKILL_RE = re.compile(r"[A-Za-z0-9-]{1,64}")
_SNAPSHOT_DIGEST_RE = re.compile(r"[a-f0-9]{64}")


class SkillSourceError(Exception):
    """A source error safe to expose through the structured API envelope."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        findings: list[dict] | None = None,
        retry_after: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.findings = findings
        self.retry_after = retry_after


@dataclass(frozen=True)
class SkillSourceRef:
    source: str
    slug: str

    @property
    def id(self) -> str:
        return f"{self.source}/{self.slug}"

    @property
    def source_url(self) -> str:
        return f"{_SKILLS_SH_SITE_BASE}/{self.id}"

    @property
    def api_url(self) -> str:
        return "/".join((_SKILLS_SH_API_BASE, *(quote(part, safe="") for part in (*self.source.split("/"), self.slug))))


@dataclass(frozen=True)
class SnapshotFile:
    path: str
    content: bytes


@dataclass(frozen=True)
class PreparedSkillSource:
    reference: SkillSourceRef
    archive_path: Path
    temporary_root: Path
    snapshot_digest: str
    upstream_hash: str | None
    file_count: int
    total_bytes: int
    skill_name: str
    description: str


class _SourceRateLimiter:
    """Process-local admission control; excess work is rejected, never queued."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active = 0
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune = 0.0

    async def acquire(self, user_id: str) -> None:
        async with self._lock:
            now = time.monotonic()
            if now - self._last_prune >= _SOURCE_WINDOW_SECONDS:
                for existing_user, entries in list(self._requests.items()):
                    while entries and entries[0] <= now - _SOURCE_WINDOW_SECONDS:
                        entries.popleft()
                    if not entries:
                        del self._requests[existing_user]
                self._last_prune = now
            requests = self._requests[user_id]
            while requests and requests[0] <= now - _SOURCE_WINDOW_SECONDS:
                requests.popleft()
            if self._active >= _SOURCE_MAX_CONCURRENT_REQUESTS:
                raise SkillSourceError(429, "skill_source_rate_limited", "Too many concurrent skills.sh requests; try again shortly.", retry_after="1")
            if len(requests) >= _SOURCE_REQUESTS_PER_USER_PER_MINUTE:
                retry_after = max(1, int(_SOURCE_WINDOW_SECONDS - (now - requests[0]) + 0.999))
                raise SkillSourceError(429, "skill_source_rate_limited", "The per-user skills.sh request limit was exceeded; try again later.", retry_after=str(retry_after))
            self._active += 1
            requests.append(now)

    def release(self) -> None:
        # Synchronous event-loop bookkeeping cannot be interrupted in a finally.
        self._active -= 1


_source_rate_limiter = _SourceRateLimiter()


@asynccontextmanager
async def _upstream_request_slot(user_id: str) -> AsyncIterator[None]:
    await _source_rate_limiter.acquire(user_id)
    try:
        yield
    finally:
        _source_rate_limiter.release()


def source_install_available() -> bool:
    """Evaluate deployment capability afresh for every feature/request check."""
    return bool((os.environ.get("VERCEL_OIDC_TOKEN") or "").strip())


def parse_skill_source(value: str) -> SkillSourceRef:
    """Parse the sole accepted source grammar without whitespace normalization."""
    if not isinstance(value, str) or not value or len(value) > 256 or not value.isascii() or ".." in value:
        raise SkillSourceError(400, "skill_source_invalid", "Source must be an ASCII owner/repo@skill identifier of at most 256 characters.")
    if any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value):
        raise SkillSourceError(400, "skill_source_invalid", "Source must not contain whitespace or control characters.")
    if value.count("@") != 1:
        raise SkillSourceError(400, "skill_source_invalid", "Source must contain exactly one '@'.")
    repository, slug = value.split("@")
    if repository.count("/") != 1:
        raise SkillSourceError(400, "skill_source_invalid", "Source repository must have exactly one owner and repository segment.")
    owner, repo = repository.split("/")
    if not _OWNER_RE.fullmatch(owner) or not _REPO_RE.fullmatch(repo) or not _SKILL_RE.fullmatch(slug):
        raise SkillSourceError(400, "skill_source_invalid", "Source does not match the owner/repo@skill grammar.")
    return SkillSourceRef(source=f"{owner.lower()}/{repo.lower()}", slug=slug.lower())


def validate_expected_snapshot_digest(value: str) -> str:
    if not isinstance(value, str) or not _SNAPSHOT_DIGEST_RE.fullmatch(value):
        raise SkillSourceError(400, "skill_source_invalid", "expected_snapshot_digest must be exactly 64 lowercase hexadecimal characters.")
    return value


def compute_snapshot_digest(files: Sequence[SnapshotFile]) -> str:
    """Hash an unambiguous, order-independent versioned snapshot encoding."""
    digest = hashlib.sha256()
    digest.update(b"deerflow-skill-snapshot-v1\0")
    digest.update(len(files).to_bytes(8, "big", signed=False))
    normalized_files = [(posixpath.normpath(file.path).encode("utf-8"), file.content) for file in files]
    for path, content in sorted(normalized_files, key=lambda item: item[0]):
        digest.update(len(path).to_bytes(8, "big", signed=False))
        digest.update(path)
        digest.update(len(content).to_bytes(8, "big", signed=False))
        digest.update(content)
    return digest.hexdigest()


def _snapshot_unusable(message: str, *, findings: list[dict] | None = None) -> SkillSourceError:
    return SkillSourceError(422, "skill_source_snapshot_unusable", message, findings=findings)


def _parse_snapshot(reference: SkillSourceRef, payload: Any) -> tuple[list[SnapshotFile], str | None]:
    if not isinstance(payload, dict):
        raise _snapshot_unusable("The skills.sh response must be a JSON object.")
    response_source = payload.get("source")
    response_slug = payload.get("slug")
    response_id = payload.get("id")
    if not all(isinstance(value, str) for value in (response_source, response_slug, response_id)):
        raise _snapshot_unusable("The skills.sh response has no valid source identity.")
    id_source, separator, id_slug = response_id.rpartition("/")
    if response_source.casefold() != reference.source or response_slug != reference.slug or not separator or id_source.casefold() != reference.source or id_slug != reference.slug:
        raise _snapshot_unusable("The skills.sh response source identity does not match the request.")

    upstream_hash = payload.get("hash")
    if upstream_hash is not None and not isinstance(upstream_hash, str):
        raise _snapshot_unusable("The skills.sh response hash must be a string or null.")
    raw_files = payload.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise _snapshot_unusable("The skills.sh snapshot has no usable text files; upload a .skill archive instead.")
    if len(raw_files) > SOURCE_FILE_COUNT_LIMIT:
        raise _snapshot_unusable(f"The source contains too many files ({len(raw_files)} > {SOURCE_FILE_COUNT_LIMIT}).")

    files: list[SnapshotFile] = []
    total_bytes = 0
    for entry in raw_files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("contents"), str):
            raise _snapshot_unusable("Every skills.sh file must contain string path and contents fields.")
        raw_path = entry["path"]
        if not raw_path or raw_path.endswith(("/", "\\")):
            raise _snapshot_unusable("Every skills.sh file path must name a file, not a directory.")
        if "\x00" in raw_path:
            raise _snapshot_unusable("A source file path contains a NUL character.")
        path = raw_path.replace("\\", "/")
        if path.startswith("/"):
            raise _snapshot_unusable(f"Source file path is absolute: {raw_path!r}")
        try:
            path.encode("utf-8")
            content = entry["contents"].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise _snapshot_unusable("Source paths and file contents must be valid UTF-8 text.") from exc
        if len(content) > SOURCE_FILE_BYTES_LIMIT:
            raise _snapshot_unusable(f"Source file '{path}' exceeds the 1 MiB UTF-8 content limit.")
        total_bytes += len(content)
        if total_bytes > SOURCE_TOTAL_BYTES_LIMIT:
            raise _snapshot_unusable("The source exceeds the 8 MiB total UTF-8 content limit.")
        files.append(SnapshotFile(path=path, content=content))
    return files, upstream_hash


def _prepare_snapshot(reference: SkillSourceRef, payload: Any, *, app_config: Any) -> PreparedSkillSource:
    """Build and validate a real .skill archive using the installer's gates."""
    files, upstream_hash = _parse_snapshot(reference, payload)
    temporary_root = Path(tempfile.mkdtemp(prefix="deerflow-skill-source-"))
    archive_path = temporary_root / "snapshot.skill"
    extraction_root = temporary_root / "extracted"
    prepared = False
    try:
        extraction_root.mkdir()
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.writestr(f"skill/{file.path}", file.content)
        if archive_path.stat().st_size > SOURCE_ARCHIVE_BYTES_LIMIT:
            raise ValueError("The generated .skill archive exceeds the 10 MiB limit.")

        with zipfile.ZipFile(archive_path, "r") as archive:
            scan_archive_preflight_or_raise(archive_path, app_config=app_config)
            safe_extract_skill_archive(archive, extraction_root)
        skill_dir, skill_name, description = resolve_and_validate_skill_dir(extraction_root)
        enforce_static_scan(skill_dir, skill_name=skill_name, app_config=app_config)
        result = PreparedSkillSource(
            reference=reference,
            archive_path=archive_path,
            temporary_root=temporary_root,
            snapshot_digest=compute_snapshot_digest(files),
            upstream_hash=upstream_hash,
            file_count=len(files),
            total_bytes=sum(len(file.content) for file in files),
            skill_name=skill_name,
            description=description,
        )
        prepared = True
        return result
    except SkillSecurityScanError as exc:
        raise _snapshot_unusable(str(exc), findings=exc.findings) from exc
    except StaticScanBlockedError as exc:
        raise _snapshot_unusable(str(exc), findings=exc.findings) from exc
    except StaticScannerError as exc:
        raise _snapshot_unusable(f"Static security scan failed: {exc}") from exc
    except SkillSourceError:
        raise
    except (OSError, UnicodeError, ValueError, zipfile.BadZipFile) as exc:
        raise _snapshot_unusable(str(exc)) from exc
    finally:
        if not prepared:
            shutil.rmtree(temporary_root, ignore_errors=True)


def discard_prepared_source(prepared: PreparedSkillSource) -> None:
    """Best-effort cleanup which cannot replace the primary request outcome."""
    shutil.rmtree(prepared.temporary_root, ignore_errors=True)


def _valid_retry_after(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return value
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if isinstance(parsed, datetime) and parsed.tzinfo is not None else None


async def _fetch_snapshot_payload(reference: SkillSourceRef, user_id: str) -> Any:
    token = (os.environ.get("VERCEL_OIDC_TOKEN") or "").strip()
    if not token:
        raise SkillSourceError(503, "skill_source_not_configured", "This deployment does not have skills.sh credentials.")
    timeout = httpx.Timeout(_SOURCE_TOTAL_TIMEOUT_SECONDS, connect=_SOURCE_CONNECT_TIMEOUT_SECONDS)
    try:
        async with asyncio.timeout(_SOURCE_TOTAL_TIMEOUT_SECONDS):
            # TLS trust initialization is synchronous in HTTPX.
            client = await asyncio.to_thread(httpx.AsyncClient, timeout=timeout, trust_env=False, follow_redirects=False)
            async with client:
                async with client.stream(
                    "GET",
                    reference.api_url,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Accept-Encoding": "identity"},
                ) as response:
                    if response.status_code in (401, 403):
                        raise SkillSourceError(503, "skill_source_auth_failed", "skills.sh authentication failed; check the Vercel OIDC credential source and expiry.")
                    if response.status_code == 404:
                        raise SkillSourceError(404, "skill_source_not_found", "The requested skill source was not found.")
                    if response.status_code == 429:
                        raise SkillSourceError(
                            429,
                            "skill_source_rate_limited",
                            "skills.sh rate limited the request; try again later.",
                            retry_after=_valid_retry_after(response.headers.get("retry-after")),
                        )
                    if response.status_code != 200:
                        raise SkillSourceError(503, "skill_source_unavailable", "skills.sh is unavailable; try again later.")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > _SOURCE_RESPONSE_MAX_BYTES:
                            raise _snapshot_unusable("The skills.sh JSON response exceeds the 12 MiB limit.")
                        chunks.append(chunk)
    except SkillSourceError:
        raise
    except (TimeoutError, httpx.TimeoutException, httpx.RequestError) as exc:
        raise SkillSourceError(503, "skill_source_unavailable", "skills.sh is unavailable; try again later.") from exc
    try:
        return await asyncio.to_thread(lambda: json.loads(b"".join(chunks)))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _snapshot_unusable("The skills.sh response is not valid UTF-8 JSON.") from exc


async def prepare_skill_source(source: str, *, user_id: str, app_config: Any) -> PreparedSkillSource:
    """Fetch, bound, and deterministically preflight one source snapshot."""
    reference = parse_skill_source(source)
    async with _upstream_request_slot(user_id):
        payload = await _fetch_snapshot_payload(reference, user_id)
        task = asyncio.ensure_future(asyncio.to_thread(_prepare_snapshot, reference, payload, app_config=app_config))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError:
                    continue
            if not task.cancelled() and task.exception() is None:
                prepared = task.result()
                await asyncio.to_thread(discard_prepared_source, prepared)
            raise
