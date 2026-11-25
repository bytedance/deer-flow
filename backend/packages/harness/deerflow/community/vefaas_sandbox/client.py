"""BytePlus Function Service (veFaaS) Cloud Sandbox OpenAPI client.

Implements the BytePlus/Volcengine OpenAPI v4 HMAC-SHA256 signing protocol and
the Cloud Sandbox instance lifecycle actions (``Version=2024-06-06``) directly
over ``httpx``, requiring no external cloud SDK package.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import AnyHttpUrl, TypeAdapter

from deerflow.community.provider_credentials import redact_secret, reject_url_userinfo

logger = logging.getLogger(__name__)

VEFAAS_API_VERSION = "2024-06-06"
VEFAAS_SERVICE = "vefaas"
DEFAULT_VEFAAS_REGION = "ap-southeast-1"
DEFAULT_REQUEST_TIMEOUT = 30.0

_URL_ADAPTER = TypeAdapter(AnyHttpUrl)
_NOT_FOUND_ERROR_CODES = frozenset(
    {
        "SandboxNotFound",
        "InstanceNotFound",
        "InvalidSandboxId.NotFound",
        "ResourceNotFound.Sandbox",
        "ResourceNotFound.Instance",
    }
)
_SNAPSHOT_NOT_FOUND_ERROR_CODES = frozenset(
    {
        "SnapshotNotFound",
        "SandboxSnapshotNotFound",
        "InvalidSnapshotId.NotFound",
        "ResourceNotFound.Snapshot",
        "ResourceNotFound.SandboxSnapshot",
    }
)
_TRANSITIONING_SANDBOX_STATUSES = frozenset(
    {
        "pending",
        "creating",
        "starting",
        "pausing",
        "resuming",
        "snapshotting",
    }
)
_TERMINAL_SANDBOX_STATUSES = frozenset({"failed", "error", "terminated", "deleted", "stopped"})
_READY_SNAPSHOT_STATUSES = frozenset({"ready", "available", "succeeded", "completed"})
_TERMINAL_SNAPSHOT_STATUSES = frozenset({"failed", "error", "deleted", "expired", "deleting"})
_SUCCEEDED_PRECACHE_STATUSES = frozenset({"success", "succeeded", "completed", "ready"})
_TERMINAL_PRECACHE_STATUSES = frozenset({"failed", "error", "canceled", "cancelled", "timeout"})


class VeFaaSApiError(RuntimeError):
    """Error returned by the BytePlus veFaaS control plane."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.request_id = request_id


class VeFaaSSandboxNotFoundError(VeFaaSApiError):
    """Authoritative response proving a remote veFaaS sandbox does not exist."""


class VeFaaSSnapshotNotFoundError(VeFaaSApiError):
    """Authoritative response proving a remote veFaaS sandbox snapshot does not exist."""


@dataclass(frozen=True)
class VeFaaSSandboxRecord:
    """Normalized veFaaS cloud sandbox instance metadata."""

    id: str
    function_id: str
    status: str
    pending: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    error_code: str = ""
    error_message: str = ""
    expire_at: str = ""
    paused_at: str = ""

    @property
    def is_running(self) -> bool:
        return self.status.strip().lower() == "running" and not self.pending

    @property
    def is_paused(self) -> bool:
        return self.status.strip().lower() == "paused" and not self.pending

    @property
    def is_transitioning(self) -> bool:
        return self.pending or self.status.strip().lower() in _TRANSITIONING_SANDBOX_STATUSES

    @property
    def is_terminal_failure(self) -> bool:
        return self.status.strip().lower() in _TERMINAL_SANDBOX_STATUSES


@dataclass(frozen=True)
class VeFaaSSnapshotRecord:
    """Normalized veFaaS cloud sandbox snapshot metadata."""

    id: str
    sandbox_id: str
    function_id: str
    status: str
    snapshot_type: str = ""
    source: str = ""
    created_at: str = ""
    retention_days: int | None = None
    retention_expires_at: str = ""
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def is_ready(self) -> bool:
        return self.status.strip().lower() in _READY_SNAPSHOT_STATUSES

    @property
    def is_terminal_failure(self) -> bool:
        return self.status.strip().lower() in _TERMINAL_SNAPSHOT_STATUSES


@dataclass(frozen=True)
class VeFaaSPrecacheTicket:
    """Normalized veFaaS sandbox image precache ticket status."""

    ticket_id: str
    status: str
    duration: int | None = None
    progress: dict[str, Any] = field(default_factory=dict)

    @property
    def is_succeeded(self) -> bool:
        return self.status.strip().lower() in _SUCCEEDED_PRECACHE_STATUSES

    @property
    def is_terminal_failure(self) -> bool:
        return self.status.strip().lower() in _TERMINAL_PRECACHE_STATUSES


def validate_endpoint_url(url: str, *, allow_insecure_http: bool = False) -> str:
    """Validate an HTTP(S) endpoint URL, forbidding embedded credentials."""
    raw = url.strip().rstrip("/")
    if not raw:
        raise ValueError("URL must not be empty")
    validated = reject_url_userinfo(_URL_ADAPTER.validate_python(raw))
    parsed = urlsplit(str(validated))
    scheme = parsed.scheme.lower()
    if scheme != "https" and not (allow_insecure_http and scheme == "http"):
        raise ValueError(f"Endpoint URL must use HTTPS (set allow_insecure_http: true only for local testing): {raw!r}")
    return str(validated).rstrip("/")


def _hmac_sha256(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _canonical_query(params: Mapping[str, str]) -> str:
    pairs = sorted((quote(str(k), safe="-_.~"), quote(str(v), safe="-_.~")) for k, v in params.items())
    return "&".join(f"{k}={v}" for k, v in pairs)


def _normalize_host_for_signing(host: str) -> str:
    if ":" not in host:
        return host
    hostname, port = host.rsplit(":", 1)
    if port in {"80", "443"}:
        return hostname
    return host


def sign_v4_headers(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    host: str,
    body: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str = VEFAAS_SERVICE,
    session_token: str | None = None,
    content_type: str = "application/json; charset=utf-8",
    now: datetime.datetime | None = None,
) -> dict[str, str]:
    """Produce BytePlus/Volcengine OpenAPI v4 HMAC-SHA256 signed headers.

    Matches ``volcenginesdkcore.signv4.SignerV4`` byte-for-byte: key derivation
    uses ``HMAC-SHA256(sk, short_date)`` (without an AWS prefix) and signs
    ``Content-Type``, ``Content-Md5``, ``Host``, and ``X-*`` headers.
    """
    canonical_path = path or "/"
    utc_now = (now or datetime.datetime.now(datetime.UTC)).astimezone(datetime.UTC)
    x_date = utc_now.strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]

    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    headers: dict[str, str] = {
        "Host": host,
        "X-Date": x_date,
        "X-Content-Sha256": body_hash,
    }
    if method.upper() != "GET":
        headers["Content-Type"] = content_type
    if session_token:
        headers["X-Security-Token"] = session_token

    signed_map: dict[str, str] = {}
    for key, value in headers.items():
        if key in {"Content-Type", "Content-Md5", "Host"} or key.startswith("X-"):
            signed_map[key.lower()] = _normalize_host_for_signing(value) if key == "Host" else value

    sorted_keys = sorted(signed_map.keys())
    canonical_headers = "".join(f"{k}:{signed_map[k]}\n" for k in sorted_keys)
    signed_headers = ";".join(sorted_keys)

    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_path,
            _canonical_query(query),
            canonical_headers,
            signed_headers,
            body_hash,
        ]
    )
    credential_scope = f"{short_date}/{region}/{service}/request"
    string_to_sign = "\n".join(
        [
            "HMAC-SHA256",
            x_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    k_date = _hmac_sha256(secret_key.encode("utf-8"), short_date)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers["Authorization"] = f"HMAC-SHA256 Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return headers


def _parse_metadata(raw: Any) -> dict[str, str]:
    """Normalize veFaaS Metadata (dict in ListSandboxes) and MetadataList (list in DescribeSandbox)."""
    if isinstance(raw, Mapping):
        return {str(k): str(v) for k, v in raw.items() if k is not None and v is not None}
    if isinstance(raw, list):
        parsed: dict[str, str] = {}
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            key = item.get("MetaKey")
            value = item.get("MetaValue")
            if isinstance(key, str) and value is not None:
                parsed[key] = str(value)
        return parsed
    return {}


def _parse_record(payload: Mapping[str, Any], *, fallback_function_id: str) -> VeFaaSSandboxRecord | None:
    sandbox_id = payload.get("Id") or payload.get("SandboxId")
    if not isinstance(sandbox_id, str) or not sandbox_id.strip():
        return None
    metadata = _parse_metadata(payload.get("Metadata"))
    if not metadata and "MetadataList" in payload:
        metadata = _parse_metadata(payload.get("MetadataList"))
    return VeFaaSSandboxRecord(
        id=sandbox_id.strip(),
        function_id=str(payload.get("FunctionId") or fallback_function_id),
        status=str(payload.get("Status") or ""),
        pending=bool(payload.get("Pending", False)),
        metadata=metadata,
        error_code=str(payload.get("ErrorCode") or ""),
        error_message=str(payload.get("ErrorMessage") or ""),
        expire_at=str(payload.get("ExpireAt") or ""),
        paused_at=str(payload.get("PausedAt") or ""),
    )


def _parse_snapshot_record(payload: Mapping[str, Any], *, fallback_function_id: str) -> VeFaaSSnapshotRecord | None:
    snapshot_id = payload.get("SnapshotId") or payload.get("Id")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        return None
    raw_retention = payload.get("RetentionDays")
    retention_days = raw_retention if isinstance(raw_retention, int) and not isinstance(raw_retention, bool) else None
    return VeFaaSSnapshotRecord(
        id=snapshot_id.strip(),
        sandbox_id=str(payload.get("SandboxId") or ""),
        function_id=str(payload.get("FunctionId") or fallback_function_id),
        status=str(payload.get("Status") or ""),
        snapshot_type=str(payload.get("SnapshotType") or payload.get("Type") or ""),
        source=str(payload.get("Source") or ""),
        created_at=str(payload.get("CreatedAt") or ""),
        retention_days=retention_days,
        retention_expires_at=str(payload.get("RetentionExpiresAt") or ""),
        metadata=_parse_metadata(payload.get("Metadata")),
    )


def _parse_precache_ticket(payload: Mapping[str, Any], *, fallback_ticket_id: str) -> VeFaaSPrecacheTicket | None:
    raw_status = payload.get("Status")
    if not isinstance(raw_status, str) or not raw_status.strip():
        return None
    raw_ticket_id = payload.get("TicketId") or fallback_ticket_id
    if not isinstance(raw_ticket_id, str) or not raw_ticket_id.strip():
        return None
    raw_duration = payload.get("Duration")
    duration = raw_duration if isinstance(raw_duration, int) and not isinstance(raw_duration, bool) else None
    raw_progress = payload.get("Progress")
    progress = dict(raw_progress) if isinstance(raw_progress, Mapping) else {}
    return VeFaaSPrecacheTicket(
        ticket_id=raw_ticket_id.strip(),
        status=raw_status.strip(),
        duration=duration,
        progress=progress,
    )


class VeFaaSClient:
    """Thread-safe BytePlus veFaaS Cloud Sandbox OpenAPI client.

    The underlying ``httpx.Client`` is created lazily on first request so
    constructing the client (or provider) does no synchronous TLS setup on an
    async event loop.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        access_key: str,
        secret_key: str,
        session_token: str | None = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        allow_insecure_http: bool = False,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        self._endpoint = validate_endpoint_url(endpoint, allow_insecure_http=allow_insecure_http)
        parsed = urlsplit(self._endpoint)
        self._host = parsed.netloc
        self._base_path = parsed.path.rstrip("/") or "/"
        self._region = region.strip()
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._timeout = float(timeout)
        self._lock = threading.Lock()
        self._owns_client = httpx_client is None
        self._client: httpx.Client | None = httpx_client
        self._closed = False

    def _redact(self, value: object) -> str:
        text = redact_secret(value, self._secret_key)
        text = redact_secret(text, self._access_key)
        text = redact_secret(text, self._session_token)
        return text

    def _get_client(self) -> httpx.Client:
        with self._lock:
            if self._closed:
                raise RuntimeError("VeFaaSClient has been closed")
            if self._client is None:
                self._client = httpx.Client(timeout=self._timeout)
            return self._client

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            client = self._client
            self._client = None
        if client is not None and self._owns_client:
            try:
                client.close()
            except Exception as exc:
                logger.warning("Error closing VeFaaSClient HTTP client: %s", self._redact(exc))

    def _request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        query = {"Action": action, "Version": VEFAAS_API_VERSION}
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
        headers = sign_v4_headers(
            method="POST",
            path=self._base_path,
            query=query,
            host=self._host,
            body=body,
            access_key=self._access_key,
            secret_key=self._secret_key,
            region=self._region,
            service=VEFAAS_SERVICE,
            session_token=self._session_token,
        )
        client = self._get_client()
        try:
            response = client.post(
                self._endpoint,
                params=query,
                content=body.encode("utf-8"),
                headers=headers,
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise VeFaaSApiError(f"veFaaS {action} request failed: {self._redact(exc)}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise VeFaaSApiError(
                f"veFaaS {action} returned non-JSON response (HTTP {response.status_code})",
                status_code=response.status_code,
            ) from exc

        if not isinstance(data, dict):
            raise VeFaaSApiError(
                f"veFaaS {action} returned malformed payload of type {type(data).__name__}",
                status_code=response.status_code,
            )

        meta = data.get("ResponseMetadata")
        request_id = meta.get("RequestId") if isinstance(meta, dict) else None
        error_obj = meta.get("Error") if isinstance(meta, dict) else None
        if isinstance(error_obj, dict) and (error_obj.get("Code") or error_obj.get("Message")):
            error_code = str(error_obj.get("Code") or "")
            error_msg = self._redact(error_obj.get("Message") or error_code)
            err_cls: type[VeFaaSApiError]
            if error_code in _NOT_FOUND_ERROR_CODES:
                err_cls = VeFaaSSandboxNotFoundError
            elif error_code in _SNAPSHOT_NOT_FOUND_ERROR_CODES:
                err_cls = VeFaaSSnapshotNotFoundError
            else:
                err_cls = VeFaaSApiError
            raise err_cls(
                f"veFaaS {action} failed ({error_code}): {error_msg}",
                status_code=response.status_code,
                error_code=error_code,
                request_id=str(request_id) if request_id else None,
            )

        if response.status_code >= 400:
            raise VeFaaSApiError(
                f"veFaaS {action} returned HTTP {response.status_code}",
                status_code=response.status_code,
                request_id=str(request_id) if request_id else None,
            )

        result = data.get("Result")
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise VeFaaSApiError(
                f"veFaaS {action} returned malformed Result of type {type(result).__name__}",
                status_code=response.status_code,
                request_id=str(request_id) if request_id else None,
            )
        return result

    def create_sandbox(
        self,
        function_id: str,
        *,
        cpu_milli: int | None = None,
        memory_mb: int | None = None,
        timeout_minutes: int | None = None,
        metadata: Mapping[str, str] | None = None,
        envs: Mapping[str, str] | None = None,
        instance_image_info: Mapping[str, Any] | None = None,
        instance_tos_mount_config: Mapping[str, Any] | None = None,
        session_id: str | None = None,
        snapshot_id: str | None = None,
        auto_pause_config: Mapping[str, Any] | None = None,
    ) -> str:
        """Create a veFaaS cloud sandbox instance and return its remote ``SandboxId``."""
        payload: dict[str, Any] = {"FunctionId": function_id}
        if cpu_milli is not None:
            payload["CpuMilli"] = cpu_milli
        if memory_mb is not None:
            payload["MemoryMB"] = memory_mb
        if timeout_minutes is not None:
            payload["Timeout"] = timeout_minutes
            payload["TimeoutUnit"] = "minute"
        if metadata:
            payload["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        if envs:
            payload["Envs"] = [{"Key": str(k), "Value": str(v)} for k, v in envs.items()]
        if instance_image_info:
            payload["InstanceImageInfo"] = dict(instance_image_info)
        if instance_tos_mount_config:
            payload["InstanceTosMountConfig"] = dict(instance_tos_mount_config)
        if session_id:
            payload["SessionId"] = session_id
        if snapshot_id:
            payload["SnapshotId"] = snapshot_id
        if auto_pause_config:
            payload["AutoPauseConfig"] = dict(auto_pause_config)

        result = self._request("CreateSandbox", payload)
        sandbox_id = result.get("SandboxId") or result.get("Id")
        if not isinstance(sandbox_id, str) or not sandbox_id.strip():
            raise VeFaaSApiError("veFaaS CreateSandbox response did not include a SandboxId")
        return sandbox_id.strip()

    def describe_sandbox(self, function_id: str, sandbox_id: str) -> VeFaaSSandboxRecord | None:
        """Describe one sandbox instance; return ``None`` only on authoritative not-found."""
        try:
            result = self._request(
                "DescribeSandbox",
                {"FunctionId": function_id, "SandboxId": sandbox_id},
            )
        except VeFaaSSandboxNotFoundError:
            return None
        record = _parse_record(result, fallback_function_id=function_id)
        if record is None:
            raise VeFaaSApiError(f"veFaaS DescribeSandbox response for {sandbox_id} did not include a valid sandbox record")
        return record

    def list_sandboxes(
        self,
        function_id: str,
        *,
        metadata: Mapping[str, str] | None = None,
        status: str | None = None,
        page_number: int | None = None,
        page_size: int = 50,
        max_pages: int = 100,
    ) -> list[VeFaaSSandboxRecord]:
        """List sandbox instances belonging to ``function_id`` with optional metadata filters.

        When ``page_number`` is omitted, paginates across pages until a short page
        or the reported ``Total`` count is reached (bounded by ``max_pages``).
        """
        records: list[VeFaaSSandboxRecord] = []
        seen_ids: set[str] = set()
        current_page = 1 if page_number is None else page_number
        single_page = page_number is not None
        pages_fetched = 0
        raw_seen = 0

        while True:
            payload: dict[str, Any] = {
                "FunctionId": function_id,
                "PageNumber": current_page,
                "PageSize": page_size,
            }
            if metadata:
                payload["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
            if status:
                payload["Status"] = status

            result = self._request("ListSandboxes", payload)
            raw_items = result.get("Sandboxes")
            if raw_items is None:
                raw_items = result.get("Items")
            if raw_items is None:
                break
            if not isinstance(raw_items, list):
                raise VeFaaSApiError(f"veFaaS ListSandboxes returned malformed Sandboxes of type {type(raw_items).__name__}")

            for item in raw_items:
                if not isinstance(item, Mapping):
                    continue
                record = _parse_record(item, fallback_function_id=function_id)
                if record is not None and record.id not in seen_ids:
                    seen_ids.add(record.id)
                    records.append(record)

            pages_fetched += 1
            raw_seen += len(raw_items)
            if single_page or len(raw_items) < page_size:
                break
            total = result.get("Total")
            if isinstance(total, int) and not isinstance(total, bool) and raw_seen >= total:
                break
            if pages_fetched >= max_pages:
                logger.warning(
                    "veFaaS ListSandboxes stopped after max_pages=%d (%d records fetched for function %s)",
                    max_pages,
                    len(records),
                    function_id,
                )
                break
            current_page += 1
        return records

    def set_sandbox_timeout(self, function_id: str, sandbox_id: str, *, timeout_minutes: int) -> None:
        """Extend the active lifetime of a running veFaaS sandbox instance."""
        self._request(
            "SetSandboxTimeout",
            {
                "FunctionId": function_id,
                "SandboxId": sandbox_id,
                "Timeout": timeout_minutes,
                "TimeoutUnit": "minute",
            },
        )

    def kill_sandbox(self, function_id: str, sandbox_id: str) -> None:
        """Terminate a veFaaS sandbox instance; treat authoritative not-found as idempotent."""
        try:
            self._request(
                "KillSandbox",
                {"FunctionId": function_id, "SandboxId": sandbox_id},
            )
        except VeFaaSSandboxNotFoundError:
            logger.debug("veFaaS sandbox %s already absent during KillSandbox", sandbox_id)

    def pause_sandbox(self, function_id: str, sandbox_id: str) -> None:
        """Pause a running veFaaS sandbox instance so its state can be resumed later."""
        self._request(
            "PauseSandbox",
            {"FunctionId": function_id, "SandboxId": sandbox_id},
        )

    def resume_sandbox(
        self,
        function_id: str,
        sandbox_id: str,
        *,
        snapshot_id: str | None = None,
        timeout_minutes: int | None = None,
        async_resume: bool | None = None,
    ) -> str:
        """Resume a paused veFaaS sandbox instance (or restore from ``snapshot_id``)."""
        payload: dict[str, Any] = {"FunctionId": function_id, "SandboxId": sandbox_id}
        if snapshot_id:
            payload["SnapshotId"] = snapshot_id
        if timeout_minutes is not None:
            payload["Timeout"] = timeout_minutes
            payload["TimeoutUnit"] = "minute"
        if async_resume is not None:
            payload["Async"] = bool(async_resume)
        result = self._request("ResumeSandbox", payload)
        return str(result.get("Status") or "")

    def create_sandbox_snapshot(
        self,
        function_id: str,
        sandbox_id: str,
        *,
        snapshot_type: str | None = None,
        retention_days: int | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        """Create a snapshot of a running veFaaS sandbox instance and return its ``SnapshotId``."""
        payload: dict[str, Any] = {"FunctionId": function_id, "SandboxId": sandbox_id}
        if snapshot_type:
            payload["Type"] = snapshot_type
        if retention_days is not None:
            payload["RetentionDays"] = retention_days
        if metadata:
            payload["Metadata"] = {str(k): str(v) for k, v in metadata.items()}
        result = self._request("CreateSandboxSnapshot", payload)
        snapshot_id = result.get("SnapshotId") or result.get("Id")
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise VeFaaSApiError("veFaaS CreateSandboxSnapshot response did not include a SnapshotId")
        return snapshot_id.strip()

    def describe_sandbox_snapshot(self, function_id: str, snapshot_id: str) -> VeFaaSSnapshotRecord | None:
        """Describe one sandbox snapshot; return ``None`` only on authoritative not-found."""
        try:
            result = self._request(
                "DescribeSandboxSnapshot",
                {"FunctionId": function_id, "SnapshotId": snapshot_id},
            )
        except VeFaaSSnapshotNotFoundError:
            return None
        raw_snapshot = result.get("Snapshot") if isinstance(result.get("Snapshot"), Mapping) else result
        record = _parse_snapshot_record(raw_snapshot, fallback_function_id=function_id)
        if record is None:
            raise VeFaaSApiError(f"veFaaS DescribeSandboxSnapshot response for {snapshot_id} did not include a valid snapshot record")
        return record

    def list_sandbox_snapshots(
        self,
        function_id: str,
        *,
        sandbox_id: str | None = None,
        filters: Sequence[Mapping[str, Any]] | None = None,
        page_number: int | None = None,
        page_size: int = 50,
        max_pages: int = 100,
    ) -> list[VeFaaSSnapshotRecord]:
        """List snapshots belonging to ``function_id`` with optional sandbox/filter criteria."""
        records: list[VeFaaSSnapshotRecord] = []
        seen_ids: set[str] = set()
        current_page = 1 if page_number is None else page_number
        single_page = page_number is not None
        pages_fetched = 0
        raw_seen = 0

        while True:
            payload: dict[str, Any] = {
                "FunctionId": function_id,
                "PageNumber": current_page,
                "PageSize": page_size,
            }
            if sandbox_id:
                payload["SandboxId"] = sandbox_id
            if filters:
                payload["Filters"] = [dict(item) for item in filters]

            result = self._request("ListSandboxSnapshots", payload)
            raw_items = result.get("Snapshots")
            if raw_items is None:
                raw_items = result.get("Items")
            if raw_items is None:
                break
            if not isinstance(raw_items, list):
                raise VeFaaSApiError(f"veFaaS ListSandboxSnapshots returned malformed Snapshots of type {type(raw_items).__name__}")

            for item in raw_items:
                if not isinstance(item, Mapping):
                    continue
                record = _parse_snapshot_record(item, fallback_function_id=function_id)
                if record is not None and record.id not in seen_ids:
                    seen_ids.add(record.id)
                    records.append(record)

            pages_fetched += 1
            raw_seen += len(raw_items)
            if single_page or len(raw_items) < page_size:
                break
            total = result.get("Total")
            if isinstance(total, int) and not isinstance(total, bool) and raw_seen >= total:
                break
            if pages_fetched >= max_pages:
                logger.warning(
                    "veFaaS ListSandboxSnapshots stopped after max_pages=%d (%d snapshots fetched for function %s)",
                    max_pages,
                    len(records),
                    function_id,
                )
                break
            current_page += 1
        return records

    def delete_sandbox_snapshot(self, function_id: str, snapshot_id: str) -> None:
        """Delete a veFaaS sandbox snapshot; treat authoritative not-found as idempotent."""
        try:
            self._request(
                "DeleteSandboxSnapshot",
                {"FunctionId": function_id, "SnapshotId": snapshot_id},
            )
        except VeFaaSSnapshotNotFoundError:
            logger.debug("veFaaS snapshot %s already absent during DeleteSandboxSnapshot", snapshot_id)

    def precache_sandbox_images(
        self,
        image_urls: Sequence[str],
        *,
        client_token: str | None = None,
        registry_type: str | None = None,
        network_config: Mapping[str, Any] | None = None,
        registry_auth_config: Mapping[str, Any] | None = None,
    ) -> str:
        """Submit a sandbox image precache job and return its ``TicketId``."""
        if isinstance(image_urls, (str, bytes)):
            raise ValueError("image_urls must be a sequence of non-empty image URLs")
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in image_urls:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("image_urls must contain only non-empty strings")
            url = item.strip()
            if url not in seen:
                seen.add(url)
                cleaned.append(url)
        if not cleaned:
            raise ValueError("image_urls must contain at least one non-empty image URL")
        payload: dict[str, Any] = {"ImageUrls": cleaned}
        if client_token:
            payload["ClientToken"] = client_token
        if registry_type:
            payload["RegistryType"] = registry_type
        if network_config:
            payload["NetworkConfig"] = dict(network_config)
        if registry_auth_config:
            payload["RegistryAuthConfig"] = dict(registry_auth_config)
        result = self._request("PrecacheSandboxImages", payload)
        ticket_id = result.get("TicketId")
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            raise VeFaaSApiError("veFaaS PrecacheSandboxImages response did not include a TicketId")
        return ticket_id.strip()

    def get_sandbox_image_precache_ticket(self, ticket_id: str) -> VeFaaSPrecacheTicket:
        """Query the status and progress of a sandbox image precache ticket."""
        result = self._request("GetSandboxImagePrecacheTicket", {"TicketId": ticket_id})
        ticket = _parse_precache_ticket(result, fallback_ticket_id=ticket_id)
        if ticket is None:
            raise VeFaaSApiError(f"veFaaS GetSandboxImagePrecacheTicket response for {ticket_id} did not include a valid status")
        return ticket


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT",
    "DEFAULT_VEFAAS_REGION",
    "VEFAAS_API_VERSION",
    "VEFAAS_SERVICE",
    "VeFaaSApiError",
    "VeFaaSClient",
    "VeFaaSPrecacheTicket",
    "VeFaaSSandboxNotFoundError",
    "VeFaaSSandboxRecord",
    "VeFaaSSnapshotNotFoundError",
    "VeFaaSSnapshotRecord",
    "sign_v4_headers",
    "validate_endpoint_url",
]
