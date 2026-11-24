"""Offline unit tests for the BytePlus veFaaS Cloud Sandbox community provider.

All control-plane tests drive ``VeFaaSClient`` through ``httpx.MockTransport``
(no live network calls, no cloud credentials required).
"""

from __future__ import annotations

import datetime
import io
import json
import os
import signal
import subprocess
import tarfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from deerflow.community.aio_sandbox.ownership import OwnershipBackendError, RenewOutcome
from deerflow.community.provider_credentials import REDACTION_MARKER
from deerflow.community.vefaas_sandbox import (
    VeFaaSApiError,
    VeFaaSClient,
    VeFaaSSandboxProvider,
    sign_v4_headers,
)
from deerflow.community.vefaas_sandbox import provider as provider_mod
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.identity import derive_sandbox_scope_token
from deerflow.sandbox.sandbox_provider import hold_sandbox_shutdown_ownership

# ── Helpers & Fakes ──────────────────────────────────────────────────────


class _FakeAioSandbox:
    """In-memory stand-in for AioSandbox recording data-plane calls."""

    def __init__(
        self,
        id: str,
        base_url: str,
        request_headers: dict[str, str] | None = None,
        default_command_timeout: float | None = None,
        lark_cli_broker: bool | None = None,
    ) -> None:
        self.id = id
        self.base_url = base_url
        self.request_headers = dict(request_headers or {})
        self.default_command_timeout = default_command_timeout
        self.lark_cli_broker = lark_cli_broker
        self.commands: list[str] = []
        self.uploaded_files: dict[str, bytes] = {}
        self.remote_outputs: dict[str, bytes] = {}
        self.closed = False
        self.fail_upload_script = False
        self.fail_bootstrap = False
        self.bootstrap_output_override: str | None = None
        self.init_marker_override: str | None = None

    def execute_command(self, command: str) -> str:
        self.commands.append(command)
        if command == provider_mod._BOOTSTRAP_COMMAND:
            if self.bootstrap_output_override is not None:
                return self.bootstrap_output_override
            if self.fail_bootstrap:
                return "mkdir: cannot create directory '/mnt/user-data/workspace': Permission denied\n"
            return f"{provider_mod._BOOTSTRAP_OK_MARKER}\n"
        if "INIT_MARKER:" in command:
            if self.init_marker_override is not None:
                return self.init_marker_override
            marker = self.uploaded_files.get(provider_mod._INIT_MARKER_PATH)
            if marker is not None:
                return f"INIT_MARKER:{marker.decode('utf-8').strip()}\n"
            return "INIT_MARKER:MISSING\n"
        if "UPLOAD_OK" in command:
            return "" if self.fail_upload_script else "UPLOAD_OK\n"
        if "find /mnt/user-data/outputs" in command:
            return "\n".join(sorted(self.remote_outputs.keys()))
        return ""

    def update_file(self, path: str, content: bytes) -> None:
        self.uploaded_files[path] = content

    def download_file(self, path: str, *, max_bytes: int | None = None) -> bytes:
        data = self.remote_outputs[path]
        if max_bytes is not None and len(data) > max_bytes:
            raise ValueError("download exceeded max_bytes")
        return data

    def close(self) -> None:
        self.closed = True


class _FakeVeFaaSServer:
    """In-memory BytePlus veFaaS OpenAPI simulator backing httpx.MockTransport."""

    def __init__(self) -> None:
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, dict[str, Any], dict[str, str]]] = []
        self.next_seq = 1
        self.kill_error: tuple[int, str, str] | None = None
        self.describe_after_kill_keeps_running = False
        self.describe_error: tuple[int, str, str] | None = None
        self.create_status_sequence: list[str] = ["Running"]
        self.ignore_list_metadata_filter = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        action = request.url.params.get("Action", "")
        version = request.url.params.get("Version", "")
        assert version == "2024-06-06"
        assert request.headers.get("Authorization", "").startswith("HMAC-SHA256 Credential=")
        assert "X-Date" in request.headers
        assert "X-Content-Sha256" in request.headers

        payload = json.loads(request.content.decode("utf-8"))
        self.requests.append((action, payload, dict(request.headers)))

        if action == "CreateSandbox":
            remote_id = f"vefaas-sb-{self.next_seq}"
            self.next_seq += 1
            self.sandboxes[remote_id] = {
                "Id": remote_id,
                "FunctionId": payload["FunctionId"],
                "Status": self.create_status_sequence[0],
                "_status_queue": list(self.create_status_sequence),
                "Pending": False,
                "Metadata": dict(payload.get("Metadata") or {}),
                "Envs": list(payload.get("Envs") or []),
                "Timeout": payload.get("Timeout"),
                "InstanceTosMountConfig": payload.get("InstanceTosMountConfig"),
            }
            return httpx.Response(
                200,
                json={"ResponseMetadata": {"RequestId": "req-create"}, "Result": {"SandboxId": remote_id}},
            )

        if action == "DescribeSandbox":
            if self.describe_error is not None:
                code, err_code, err_msg = self.describe_error
                return httpx.Response(
                    code,
                    json={"ResponseMetadata": {"RequestId": "req-desc-err", "Error": {"Code": err_code, "Message": err_msg}}},
                )
            remote_id = payload["SandboxId"]
            record = self.sandboxes.get(remote_id)
            if record is None:
                return httpx.Response(
                    404,
                    json={"ResponseMetadata": {"RequestId": "req-404", "Error": {"Code": "SandboxNotFound", "Message": "not found"}}},
                )
            queue = record.get("_status_queue")
            if queue:
                record["Status"] = queue.pop(0)
            return httpx.Response(
                200,
                json={
                    "ResponseMetadata": {"RequestId": "req-desc"},
                    "Result": {
                        "Id": record["Id"],
                        "FunctionId": record["FunctionId"],
                        "Status": record["Status"],
                        "Pending": record["Pending"],
                        "MetadataList": [{"MetaKey": k, "MetaValue": v} for k, v in record["Metadata"].items()],
                    },
                },
            )

        if action == "ListSandboxes":
            wanted_meta = payload.get("Metadata") or {}
            items = []
            for record in self.sandboxes.values():
                if record["FunctionId"] != payload["FunctionId"]:
                    continue
                if self.ignore_list_metadata_filter or all(record["Metadata"].get(k) == v for k, v in wanted_meta.items()):
                    items.append(
                        {
                            "Id": record["Id"],
                            "FunctionId": record["FunctionId"],
                            "Status": record["Status"],
                            "Pending": record["Pending"],
                            "Metadata": dict(record["Metadata"]),
                        }
                    )
            page_number = int(payload.get("PageNumber", 1))
            page_size = int(payload.get("PageSize", 50))
            start = (page_number - 1) * page_size
            page_items = items[start : start + page_size]
            return httpx.Response(
                200,
                json={"ResponseMetadata": {"RequestId": "req-list"}, "Result": {"Sandboxes": page_items, "Total": len(items)}},
            )

        if action == "SetSandboxTimeout":
            remote_id = payload["SandboxId"]
            if remote_id not in self.sandboxes:
                return httpx.Response(
                    404,
                    json={"ResponseMetadata": {"RequestId": "req-to-404", "Error": {"Code": "SandboxNotFound", "Message": "not found"}}},
                )
            self.sandboxes[remote_id]["Timeout"] = payload["Timeout"]
            return httpx.Response(
                200,
                json={"ResponseMetadata": {"RequestId": "req-timeout"}, "Result": {"SandboxId": remote_id}},
            )

        if action == "KillSandbox":
            if self.kill_error is not None:
                code, err_code, err_msg = self.kill_error
                return httpx.Response(
                    code,
                    json={"ResponseMetadata": {"RequestId": "req-kill-err", "Error": {"Code": err_code, "Message": err_msg}}},
                )
            remote_id = payload["SandboxId"]
            if not self.describe_after_kill_keeps_running:
                self.sandboxes.pop(remote_id, None)
            return httpx.Response(200, json={"ResponseMetadata": {"RequestId": "req-kill"}, "Result": {}})

        return httpx.Response(400, json={"ResponseMetadata": {"Error": {"Code": "InvalidAction", "Message": action}}})


def _make_app_config(
    tmp_path: Path,
    *,
    sandbox_overrides: dict[str, Any] | None = None,
    skills_container_path: str = "/mnt/skills",
) -> Any:
    raw: dict[str, Any] = {
        "use": "deerflow.community.vefaas_sandbox:VeFaaSSandboxProvider",
        "idle_timeout": 0,
        "replicas": 3,
        "vefaas": {
            "region": "ap-southeast-1",
            "endpoint": "https://vefaas.ap-southeast-1.byteplusapi.com",
            "function_id": "fn-demo-app",
            "sandbox_base_url": "https://sandbox.ap-southeast-1.byteplus.example",
            "access_key": "AK-TEST-KEY",
            "secret_key": "SK-TEST-SECRET",
            "timeout_minutes": 60,
            "ready_timeout": 10,
        },
    }
    if sandbox_overrides:
        if "vefaas" in sandbox_overrides and isinstance(sandbox_overrides["vefaas"], dict):
            raw["vefaas"] = {**raw["vefaas"], **sandbox_overrides["vefaas"]}
        for k, v in sandbox_overrides.items():
            if k != "vefaas":
                raw[k] = v
    sandbox_cfg = SandboxConfig(**raw)
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        sandbox=sandbox_cfg,
        skills=SimpleNamespace(
            container_path=skills_container_path,
            path=str(skills_dir),
            get_skills_path=lambda: skills_dir,
        ),
        stream_bridge=None,
    )


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    server: _FakeVeFaaSServer | None = None,
    sandbox_overrides: dict[str, Any] | None = None,
    ready_result: bool = True,
) -> tuple[VeFaaSSandboxProvider, _FakeVeFaaSServer, list[_FakeAioSandbox]]:
    fake_server = server or _FakeVeFaaSServer()
    mock_http = httpx.Client(transport=httpx.MockTransport(fake_server.handler))
    app_cfg = _make_app_config(tmp_path, sandbox_overrides=sandbox_overrides)
    monkeypatch.setattr(provider_mod, "get_app_config", lambda: app_cfg)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "deer-flow-home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    created_aio: list[_FakeAioSandbox] = []

    def fake_aio_ctor(**kwargs: Any) -> _FakeAioSandbox:
        inst = _FakeAioSandbox(**kwargs)
        created_aio.append(inst)
        return inst

    monkeypatch.setattr(provider_mod, "AioSandbox", fake_aio_ctor)
    monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", lambda url, timeout=30, headers=None: ready_result)
    monkeypatch.setattr(provider_mod.time, "sleep", lambda _s: None)

    client = VeFaaSClient(
        endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
        region="ap-southeast-1",
        access_key="AK-TEST-KEY",
        secret_key="SK-TEST-SECRET",
        httpx_client=mock_http,
    )
    with hold_sandbox_shutdown_ownership():
        provider = VeFaaSSandboxProvider(client=client)
    return provider, fake_server, created_aio


# ── 1. SigV4 Signing ─────────────────────────────────────────────────────


class TestSigV4Signing:
    def test_deterministic_sigv4_golden_vector(self) -> None:
        fixed_now = datetime.datetime(2026, 11, 20, 10, 30, 45, tzinfo=datetime.UTC)
        ours = sign_v4_headers(
            method="POST",
            path="/",
            query={"Version": "2024-06-06", "Action": "CreateSandbox"},
            host="vefaas.ap-southeast-1.byteplusapi.com:443",
            body='{"FunctionId":"fn-123","Timeout":60}',
            access_key="AK-SAMPLE",
            secret_key="SK-SAMPLE-SECRET",
            region="ap-southeast-1",
            service="vefaas",
            session_token="STS-TOKEN-123",
            now=fixed_now,
        )
        assert ours["X-Date"] == "20261120T103045Z"
        assert ours["X-Content-Sha256"] == "1690c1caa5853a6576bd4d2b6620c64da66231c64c663ce86f5693a30cdc2db7"
        assert ours["X-Security-Token"] == "STS-TOKEN-123"
        assert ours["Authorization"] == (
            "HMAC-SHA256 Credential=AK-SAMPLE/20261120/ap-southeast-1/vefaas/request, SignedHeaders=content-type;host;x-content-sha256;x-date;x-security-token, Signature=cd6d3ce28d1342fd6569a5fc7b59b3c40b4fa4a2a4f12ca8208c39216a29538d"
        )

    def test_matches_volcengine_sdk_signer_byte_for_byte(self) -> None:
        pytest.importorskip("volcenginesdkcore.signv4")
        from volcenginesdkcore.signv4 import SignerV4

        fixed_now = datetime.datetime(2026, 11, 20, 10, 30, 45, tzinfo=datetime.UTC)
        query = {"Action": "CreateSandbox", "Version": "2024-06-06"}
        body = '{"FunctionId":"fn-123","Timeout":60}'
        host = "vefaas.ap-southeast-1.byteplusapi.com:443"

        ours = sign_v4_headers(
            method="POST",
            path="/",
            query=query,
            host=host,
            body=body,
            access_key="AK-SAMPLE",
            secret_key="SK-SAMPLE-SECRET",
            region="ap-southeast-1",
            service="vefaas",
            session_token="STS-TOKEN-123",
            now=fixed_now,
        )

        # Reproduce SDK signer with the exact same UTC timestamp.
        sdk_headers = {"Host": host, "Content-Type": "application/json; charset=utf-8"}

        class _FrozenDateTime(datetime.datetime):
            @classmethod
            def utcnow(cls) -> datetime.datetime:
                return fixed_now.replace(tzinfo=None)

        orig_dt = SignerV4.sign.__globals__["datetime"].datetime
        SignerV4.sign.__globals__["datetime"].datetime = _FrozenDateTime
        try:
            SignerV4.sign(
                path="/",
                method="POST",
                headers=sdk_headers,
                body=body,
                post_params=None,
                query=query,
                ak="AK-SAMPLE",
                sk="SK-SAMPLE-SECRET",
                region="ap-southeast-1",
                service="vefaas",
                session_token="STS-TOKEN-123",
            )
        finally:
            SignerV4.sign.__globals__["datetime"].datetime = orig_dt

        assert ours["X-Date"] == sdk_headers["X-Date"]
        assert ours["X-Content-Sha256"] == sdk_headers["X-Content-Sha256"]
        assert ours["X-Security-Token"] == "STS-TOKEN-123"
        assert ours["Authorization"] == sdk_headers["Authorization"]


# ── 2. VeFaaSClient OpenAPI & Security ───────────────────────────────────


class TestVeFaaSClient:
    def test_enforces_https_and_rejects_userinfo(self) -> None:
        with pytest.raises(ValueError, match="HTTPS"):
            VeFaaSClient(
                endpoint="http://vefaas.ap-southeast-1.byteplusapi.com",
                region="ap-southeast-1",
                access_key="ak",
                secret_key="sk",
            )
        with pytest.raises(ValueError, match="username or password"):
            VeFaaSClient(
                endpoint="https://user:pass@vefaas.ap-southeast-1.byteplusapi.com",
                region="ap-southeast-1",
                access_key="ak",
                secret_key="sk",
            )

    def test_redacts_secrets_from_transport_and_api_errors(self) -> None:
        secret = "SUPER-SECRET-SK-999"

        def failing_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                json={"ResponseMetadata": {"RequestId": "req-err", "Error": {"Code": "InternalError", "Message": f"upstream leaked {secret}"}}},
            )

        client = VeFaaSClient(
            endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
            region="ap-southeast-1",
            access_key="AK-1",
            secret_key=secret,
            httpx_client=httpx.Client(transport=httpx.MockTransport(failing_handler)),
        )
        with pytest.raises(VeFaaSApiError) as exc_info:
            client.describe_sandbox("fn-1", "sb-1")
        assert secret not in str(exc_info.value)
        assert REDACTION_MARKER in str(exc_info.value)

    def test_describe_returns_none_only_on_not_found_and_raises_on_500(self) -> None:
        server = _FakeVeFaaSServer()
        client = VeFaaSClient(
            endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
            region="ap-southeast-1",
            access_key="ak",
            secret_key="sk",
            httpx_client=httpx.Client(transport=httpx.MockTransport(server.handler)),
        )
        assert client.describe_sandbox("fn-1", "missing-id") is None

        server.describe_error = (503, "ServiceUnavailable", "temporary outage")
        with pytest.raises(VeFaaSApiError):
            client.describe_sandbox("fn-1", "missing-id")

        # Non-sandbox *NotFound errors and empty-code 404s must fail closed rather than proving absence.
        for status_code, err_code, err_msg in (
            (404, "FunctionNotFound", "function does not exist"),
            (404, "ActionNotFound", "unknown action"),
            (404, "AccountNotFound", "unknown account"),
            (404, "RouteNotFound", "unknown route"),
            (404, "", "gateway route not found"),
        ):
            server.describe_error = (status_code, err_code, err_msg)
            with pytest.raises(VeFaaSApiError):
                client.describe_sandbox("fn-1", "missing-id")

        # Bare JSON HTTP 404 responses (no ResponseMetadata.Error) must also fail closed.
        for bare_404 in ({}, {"message": "no Route matched"}):
            bare_client = VeFaaSClient(
                endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
                region="ap-southeast-1",
                access_key="ak",
                secret_key="sk",
                httpx_client=httpx.Client(transport=httpx.MockTransport(lambda _r, body=bare_404: httpx.Response(404, json=body))),
            )
            with pytest.raises(VeFaaSApiError):
                bare_client.describe_sandbox("fn-1", "sb-1")

        # Malformed/empty 2xx DescribeSandbox responses must fail closed rather than proving absence.
        for bad_body in (
            {"ResponseMetadata": {"RequestId": "req-empty"}, "Result": {}},
            {"ResponseMetadata": {"RequestId": "req-no-id"}, "Result": {"Status": "Running"}},
        ):
            bad_client = VeFaaSClient(
                endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
                region="ap-southeast-1",
                access_key="ak",
                secret_key="sk",
                httpx_client=httpx.Client(transport=httpx.MockTransport(lambda _r, body=bad_body: httpx.Response(200, json=body))),
            )
            with pytest.raises(VeFaaSApiError, match="valid sandbox record"):
                bad_client.describe_sandbox("fn-1", "sb-1")


# ── 3. Config Validation ─────────────────────────────────────────────────


class TestVeFaaSConfigValidation:
    def test_rejects_boolean_and_out_of_range_numeric_fields(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="cpu_milli"):
            _install_provider(monkeypatch, tmp_path, sandbox_overrides={"vefaas": {"cpu_milli": True}})
        with pytest.raises(ValueError, match="memory_mb"):
            _install_provider(monkeypatch, tmp_path, sandbox_overrides={"vefaas": {"memory_mb": 128}})
        with pytest.raises(ValueError, match="timeout_minutes"):
            _install_provider(monkeypatch, tmp_path, sandbox_overrides={"vefaas": {"timeout_minutes": 2}})

    def test_rejects_tos_mount_without_bucket_or_traversal_prefix(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="bucket"):
            _install_provider(monkeypatch, tmp_path, sandbox_overrides={"vefaas": {"tos_mount": {"enabled": True}}})
        with pytest.raises(ValueError, match="invalid path segments"):
            _install_provider(
                monkeypatch,
                tmp_path,
                sandbox_overrides={"vefaas": {"tos_mount": {"enabled": True, "bucket": "bkt", "prefix": "../escape"}}},
            )

    def test_rejects_unsafe_skills_roots(self) -> None:
        assert provider_mod._validate_skills_root("/mnt/skills") == "/mnt/skills"
        for bad in ("/", "/etc", "/mnt/user-data", "/mnt/user-data/skills", "/mnt/skills/../etc"):
            with pytest.raises(ValueError):
                provider_mod._validate_skills_root(bad)


# ── 4. Provider Lifecycle, Skills Sync, TOS Mount & Ownership ────────────


class TestVeFaaSSandboxProviderLifecycle:
    def test_acquire_get_scoped_release_reclaim_and_shutdown(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"vefaas": {"sandbox_access_token": "apig-secret-tok"}},
        )
        try:
            assert provider.supports_agent_skill_isolation is True
            assert provider.supports_lazy_agent_skill_isolation is False
            assert provider.uses_thread_data_mounts is False

            sandbox_id = provider.acquire("thread-1", user_id="user-a")
            expected_id = derive_sandbox_scope_token(user_id="user-a", thread_id="thread-1")
            assert sandbox_id == expected_id
            assert len(aio_instances) == 1

            # Verify AioSandbox reused with unified domain + instance routing header + bearer token.
            aio = aio_instances[0]
            assert aio.base_url == "https://sandbox.ap-southeast-1.byteplus.example"
            assert aio.request_headers[provider_mod.INSTANCE_ROUTING_HEADER] == "vefaas-sb-1"
            assert aio.request_headers["Authorization"] == "Bearer apig-secret-tok"
            assert aio.lark_cli_broker is False

            # Identity-scoped lookup fails closed for another user or thread.
            assert provider.get(sandbox_id) is aio
            assert provider.get_scoped(sandbox_id, thread_id="thread-1", user_id="user-a") is aio
            assert provider.get_scoped(sandbox_id, thread_id="thread-1", user_id="user-b") is None
            assert provider.get_scoped(sandbox_id, thread_id="thread-2", user_id="user-a") is None

            # Seed an output artifact inside the sandbox and verify release mirrors it to host.
            aio.remote_outputs["/mnt/user-data/outputs/report.txt"] = b"hello-vefaas"
            provider.release(sandbox_id)
            assert provider.get(sandbox_id) is None

            from deerflow.config.paths import get_paths

            mirrored = get_paths().sandbox_outputs_dir("thread-1", user_id="user-a") / "report.txt"
            assert mirrored.read_bytes() == b"hello-vefaas"

            # Reclaim from warm pool extends timeout and avoids CreateSandbox.
            reclaimed_id = provider.acquire("thread-1", user_id="user-a")
            assert reclaimed_id == sandbox_id
            actions = [a for a, _, _ in server.requests]
            assert actions.count("CreateSandbox") == 1
            assert "SetSandboxTimeout" in actions
        finally:
            provider.shutdown()

        # Shutdown kills remote sandbox and confirms absence.
        actions = [a for a, _, _ in server.requests]
        assert "KillSandbox" in actions
        assert server.sandboxes == {}
        assert aio_instances[0].closed is True

        # Admission stays closed after shutdown.
        with pytest.raises(RuntimeError, match="shut down"):
            provider.acquire("thread-2", user_id="user-a")

    def test_url_template_mode_omits_instance_routing_header(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _server, aio_instances = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"vefaas": {"sandbox_base_url": "https://{sandbox_id}.sandbox.example.com"}},
        )
        try:
            provider.acquire("t-tpl", user_id="u-1")
            assert aio_instances[0].base_url == "https://vefaas-sb-1.sandbox.example.com"
            assert provider_mod.INSTANCE_ROUTING_HEADER not in aio_instances[0].request_headers
        finally:
            provider.shutdown()

    def test_tos_mount_uses_scope_token_and_skips_host_mirroring(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={
                "vefaas": {
                    "tos_mount": {
                        "enabled": True,
                        "bucket": "deerflow-prod-bucket",
                        "prefix": "user-data",
                        "local_mount_path": "/mnt/user-data",
                    }
                }
            },
        )
        try:
            sandbox_id = provider.acquire("t-tos", user_id="alice@example.com")
            create_payload = next(p for a, p, _ in server.requests if a == "CreateSandbox")
            tos = create_payload["InstanceTosMountConfig"]
            assert tos["Enable"] is True
            mount = tos["TosMountPoints"][0]
            assert mount["BucketName"] == "deerflow-prod-bucket"
            assert mount["BucketPath"] == f"/user-data/{sandbox_id}"
            assert "alice" not in mount["BucketPath"]
            assert mount["LocalMountPath"] == "/mnt/user-data"

            # Output mirroring is skipped because /mnt/user-data is backed directly by TOS.
            aio_instances[0].remote_outputs["/mnt/user-data/outputs/a.txt"] = b"skip-me"
            provider.release(sandbox_id)
            assert not any("find /mnt/user-data/outputs" in cmd for cmd in aio_instances[0].commands)
        finally:
            provider.shutdown()

    def test_cross_process_discovery_adopts_running_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        server = _FakeVeFaaSServer()
        sandbox_id = derive_sandbox_scope_token(user_id="u1", thread_id="t-discover")
        server.sandboxes["vefaas-existing-9"] = {
            "Id": "vefaas-existing-9",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sandbox_id,
            },
        }
        provider, _, aio_instances = _install_provider(monkeypatch, tmp_path, server=server)
        try:
            acquired = provider.acquire("t-discover", user_id="u1")
            assert acquired == sandbox_id
            assert aio_instances[0].request_headers[provider_mod.INSTANCE_ROUTING_HEADER] == "vefaas-existing-9"
            assert not any(a == "CreateSandbox" for a, _, _ in server.requests)
        finally:
            provider.shutdown()

    def test_sync_agent_skills_uploads_tar_and_rejects_symlinks_and_mismatch(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _server, aio_instances = _install_provider(monkeypatch, tmp_path)
        try:
            sandbox_id = provider.acquire("t-skills", user_id="u-skills")
            aio = aio_instances[0]
            # Initial acquire uploads the shared skills projection and writes the init marker.
            tar_uploads = [k for k in aio.uploaded_files if k.endswith(".tar.gz")]
            assert len(tar_uploads) == 1
            assert provider_mod._INIT_MARKER_PATH in aio.uploaded_files
            aio.uploaded_files.clear()
            aio.commands.clear()

            proj_root = tmp_path / "proj"
            for cat in ("public", "custom", "legacy", "integrations"):
                (proj_root / cat).mkdir(parents=True)
            (proj_root / "public" / "demo-skill").mkdir()
            (proj_root / "public" / "demo-skill" / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")
            host_secret = tmp_path / "host-secret.txt"
            host_secret.write_text("do-not-smuggle", encoding="utf-8")
            (proj_root / "public" / "demo-skill" / "escape.txt").symlink_to(host_secret)

            projection = SimpleNamespace(
                public=proj_root / "public",
                custom=proj_root / "custom",
                legacy=proj_root / "legacy",
                integrations=proj_root / "integrations",
            )
            provider.sync_agent_skills(sandbox_id, thread_id="t-skills", user_id="u-skills", projection=projection)

            assert len(aio.uploaded_files) == 1
            tar_bytes = next(iter(aio.uploaded_files.values()))
            with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
                names = tf.getnames()
            assert "public/demo-skill/SKILL.md" in names
            assert "public/demo-skill/escape.txt" not in names
            assert any("rm -rf --" in cmd and "UPLOAD_OK" in cmd for cmd in aio.commands)

            # Symlinked projection root is refused.
            symlink_root = tmp_path / "symlink-public"
            symlink_root.symlink_to(proj_root / "public")
            bad_projection = SimpleNamespace(
                public=symlink_root,
                custom=proj_root / "custom",
                legacy=proj_root / "legacy",
                integrations=proj_root / "integrations",
            )
            with pytest.raises(ValueError, match="symlinked upload root"):
                provider.sync_agent_skills(sandbox_id, thread_id="t-skills", user_id="u-skills", projection=bad_projection)

            # Identity mismatch fails closed.
            with pytest.raises(RuntimeError, match="does not match"):
                provider.sync_agent_skills(sandbox_id, thread_id="t-skills", user_id="other-user", projection=projection)
        finally:
            provider.shutdown()

    def test_lost_ownership_lease_forgets_locally_without_killing_peer_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(monkeypatch, tmp_path)
        try:
            sandbox_id = provider.acquire("t-lost", user_id="u1")
            mock_store = MagicMock()
            mock_store.supports_cross_process = True
            mock_store.renew.return_value = RenewOutcome.LOST
            provider._ownership = mock_store

            provider._renew_leases_once()

            assert provider.get(sandbox_id) is None
            assert aio_instances[0].closed is True
            assert not any(a == "KillSandbox" for a, _, _ in server.requests)
            assert "vefaas-sb-1" in server.sandboxes
        finally:
            provider.shutdown()

    def test_quarantine_and_retryable_shutdown_when_absence_unconfirmed(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        server = _FakeVeFaaSServer()
        server.describe_after_kill_keeps_running = True
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)

        sandbox_id = provider.acquire("t-quar", user_id="u1")
        with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError):
            provider.shutdown()

        # Remote still alive -> quarantined and shutdown remains retryable.
        assert "vefaas-sb-1" in provider._quarantined_remote_ids.get(sandbox_id, set())

        # Once backend confirms deletion, retry shutdown succeeds cleanly.
        server.describe_after_kill_keeps_running = False
        provider.shutdown()
        assert provider._shutdown_complete is True
        assert server.sandboxes == {}

    def test_failed_provisioning_rollback_blocks_shutdown_until_confirmed_absent(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        server = _FakeVeFaaSServer()
        server.describe_after_kill_keeps_running = True
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server, ready_result=False)

        expected_id = derive_sandbox_scope_token(user_id="u1", thread_id="t-rb-shutdown")
        with pytest.raises(TimeoutError, match="did not become HTTP-ready"):
            provider.acquire("t-rb-shutdown", user_id="u1")

        # Rollback could not confirm absence -> retained for both quarantine and shutdown cleanup.
        assert "vefaas-sb-1" in provider._quarantined_remote_ids.get(expected_id, set())
        assert "vefaas-sb-1" in provider._pending_rollbacks

        # First shutdown retries the rollback generation and stays incomplete while still running.
        with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError):
            provider.shutdown()
        assert provider._shutdown_complete is False

        # Once deletion is confirmed, retry shutdown clears rollback state and completes cleanly.
        server.describe_after_kill_keeps_running = False
        provider.shutdown()
        assert provider._shutdown_complete is True
        assert provider._pending_rollbacks == {}
        assert provider._quarantined_remote_ids == {}
        assert server.sandboxes == {}

    def test_ownership_backend_error_rolls_back_fresh_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, _ = _install_provider(monkeypatch, tmp_path)
        mock_store = MagicMock()
        mock_store.supports_cross_process = True
        mock_store.take.side_effect = OwnershipBackendError("redis down")
        provider._ownership = mock_store
        try:
            with pytest.raises(OwnershipBackendError, match="redis down"):
                provider.acquire("t-rb", user_id="u1")
            assert any(a == "KillSandbox" for a, _, _ in server.requests)
            assert server.sandboxes == {}
        finally:
            provider.shutdown()

    def test_host_shutdown_ownership_skips_signal_handlers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        installed_signals: list[int] = []
        monkeypatch.setattr(provider_mod.signal, "signal", lambda sig, _h: installed_signals.append(sig))
        provider, _, _ = _install_provider(monkeypatch, tmp_path)
        try:
            assert installed_signals == []
        finally:
            provider.shutdown()

    def test_signal_handler_restores_and_reraises_sig_dfl_outside_host_ownership(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        installed: dict[int, Any] = {}
        raised: list[int] = []

        monkeypatch.setattr(provider_mod, "host_owns_sandbox_shutdown", lambda: False)
        monkeypatch.setattr(provider_mod.signal, "getsignal", lambda _sig: signal.SIG_DFL)
        monkeypatch.setattr(provider_mod.signal, "signal", lambda sig, handler: installed.__setitem__(sig, handler))
        monkeypatch.setattr(provider_mod.signal, "raise_signal", lambda sig: raised.append(sig))

        provider, _, _ = _install_provider(monkeypatch, tmp_path)
        try:
            assert signal.SIGTERM in installed
            handler = installed[signal.SIGTERM]
            # Even if shutdown() raises an unexpected exception, SIG_DFL is restored and re-raised.
            monkeypatch.setattr(provider, "shutdown", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
            handler(signal.SIGTERM, None)
            assert installed[signal.SIGTERM] == signal.SIG_DFL
            assert raised == [signal.SIGTERM]
        finally:
            monkeypatch.undo()
            provider.shutdown()

    def test_sandbox_id_normalizes_none_user_id_and_differs_from_literal_none(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _, _ = _install_provider(monkeypatch, tmp_path)
        try:
            sid_none = provider.acquire("t-none")
            expected_empty = derive_sandbox_scope_token(user_id="", thread_id="t-none")
            assert sid_none == expected_empty
            assert provider.get_scoped(sid_none, thread_id="t-none", user_id="") is not None

            sid_literal_none = provider.acquire("t-none", user_id="None")
            assert sid_literal_none != sid_none
            assert provider.get_scoped(sid_literal_none, thread_id="t-none", user_id="None") is not None
        finally:
            provider.shutdown()

    def test_list_sandboxes_paginates_and_discovery_verifies_metadata_client_side(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        server = _FakeVeFaaSServer()
        server.ignore_list_metadata_filter = True
        sandbox_id = derive_sandbox_scope_token(user_id="u1", thread_id="t-page2")

        # Fill page 1 (50 entries) with unrelated running sandboxes that do not match metadata.
        for idx in range(52):
            server.sandboxes[f"vefaas-other-{idx}"] = {
                "Id": f"vefaas-other-{idx}",
                "FunctionId": "fn-demo-app",
                "Status": "Running",
                "Pending": False,
                "Metadata": {
                    provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                    provider_mod.META_KEY_SANDBOX_ID: f"other-scope-{idx}",
                },
            }
        # Place the matching sandbox on page 2.
        server.sandboxes["vefaas-target-page2"] = {
            "Id": "vefaas-target-page2",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sandbox_id,
            },
        }
        provider, _, aio_instances = _install_provider(monkeypatch, tmp_path, server=server)
        try:
            acquired = provider.acquire("t-page2", user_id="u1")
            assert acquired == sandbox_id
            assert aio_instances[0].request_headers[provider_mod.INSTANCE_ROUTING_HEADER] == "vefaas-target-page2"
            list_pages = [p["PageNumber"] for a, p, _ in server.requests if a == "ListSandboxes"]
            assert list_pages == [1, 2]
            assert not any(a == "CreateSandbox" for a, _, _ in server.requests)
        finally:
            provider.shutdown()

    def test_incomplete_skills_upload_refuses_destructive_replace(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _, aio_instances = _install_provider(monkeypatch, tmp_path)
        try:
            sandbox_id = provider.acquire("t-budget", user_id="u-budget")
            aio = aio_instances[0]
            aio.uploaded_files.clear()
            aio.commands.clear()

            proj_root = tmp_path / "proj-budget"
            for cat in ("public", "custom", "legacy", "integrations"):
                (proj_root / cat).mkdir(parents=True)
            (proj_root / "public" / "a.txt").write_text("one", encoding="utf-8")
            (proj_root / "public" / "b.txt").write_text("two", encoding="utf-8")
            projection = SimpleNamespace(
                public=proj_root / "public",
                custom=proj_root / "custom",
                legacy=proj_root / "legacy",
                integrations=proj_root / "integrations",
            )
            monkeypatch.setattr(provider_mod, "_MAX_UPLOAD_FILES", 1)
            with pytest.raises(RuntimeError, match="exceeds the veFaaS upload limit"):
                provider.sync_agent_skills(sandbox_id, thread_id="t-budget", user_id="u-budget", projection=projection)
            assert aio.uploaded_files == {}
            assert aio.commands == []
        finally:
            provider.shutdown()

    @pytest.mark.skipif(os.name == "nt", reason="POSIX persistent shell test")
    def test_upload_script_preserves_persistent_shell_and_cleans_up_temp_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _, _ = _install_provider(monkeypatch, tmp_path)
        dest_root = tmp_path / "remote-skills"
        dest_root.mkdir()
        (dest_root / "public").mkdir()
        (dest_root / "public" / "existing.txt").write_text("keep-me", encoding="utf-8")

        proj_root = tmp_path / "src-skills"
        for cat in ("public", "custom", "legacy", "integrations"):
            (proj_root / cat).mkdir(parents=True)
        (proj_root / "public" / "new.txt").write_text("fresh-skill", encoding="utf-8")

        proc = subprocess.Popen(
            ["/bin/sh"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        assert proc.stdin is not None and proc.stdout is not None
        recorded_tars: list[Path] = []

        def run_in_persistent_shell(cmd: str) -> str:
            marker = f"__DONE_{len(recorded_tars)}__"
            proc.stdin.write(f"{cmd}\nprintf '%s\\n' '{marker}'\n")
            proc.stdin.flush()
            lines: list[str] = []
            while True:
                line = proc.stdout.readline()
                assert line != "", "persistent shell terminated unexpectedly"
                if line.strip() == marker:
                    break
                lines.append(line)
            return "".join(lines)

        class _ShellSandbox:
            def update_file(self, path: str, content: bytes) -> None:
                p = Path(path)
                recorded_tars.append(p)
                p.write_bytes(content)

            def execute_command(self, command: str) -> str:
                return run_in_persistent_shell(command)

        try:
            shell_sandbox = _ShellSandbox()
            sources = [(proj_root / cat, cat) for cat in ("public", "custom", "legacy", "integrations")]
            assert provider._upload_trees(shell_sandbox, sources, dest_root=str(dest_root), replace=("public", "custom", "legacy", "integrations")) is True

            # New skill replaced old one, temp tar & staging dir cleaned up, parent shell has no errexit.
            assert (dest_root / "public" / "new.txt").read_text(encoding="utf-8") == "fresh-skill"
            assert not (dest_root / "public" / "existing.txt").exists()
            assert not recorded_tars[-1].exists()
            assert not list(dest_root.glob(".vefaas-stage-*"))
            flags_out = run_in_persistent_shell("printf '%s\\n' \"$-:\" ; false; echo STILL_ALIVE")
            assert "STILL_ALIVE" in flags_out
            assert "e" not in flags_out.splitlines()[0].rstrip(":")

            # Failing upload (symlinked dest_root hitting exit 2) keeps parent shell alive & cleans temp tar.
            symlink_dest = tmp_path / "symlink-skills"
            symlink_dest.symlink_to(dest_root)
            with pytest.raises(RuntimeError, match="upload into"):
                provider._upload_trees(shell_sandbox, sources, dest_root=str(symlink_dest), replace=("public", "custom", "legacy", "integrations"))
            assert not recorded_tars[-1].exists()
            assert "STILL_ALIVE" in run_in_persistent_shell("echo STILL_ALIVE")
            assert (dest_root / "public" / "new.txt").read_text(encoding="utf-8") == "fresh-skill"

            # Failing tar extraction keeps parent shell alive and leaves existing skills intact.
            class _CorruptTarShellSandbox(_ShellSandbox):
                def update_file(self, path: str, content: bytes) -> None:
                    del content
                    p = Path(path)
                    recorded_tars.append(p)
                    p.write_bytes(b"not-a-valid-gzip-archive")

            with pytest.raises(RuntimeError, match="upload into"):
                provider._upload_trees(_CorruptTarShellSandbox(), sources, dest_root=str(dest_root), replace=("public", "custom", "legacy", "integrations"))
            assert not recorded_tars[-1].exists()
            assert not list(dest_root.glob(".vefaas-stage-*"))
            assert "STILL_ALIVE" in run_in_persistent_shell("echo STILL_ALIVE")
            assert (dest_root / "public" / "new.txt").read_text(encoding="utf-8") == "fresh-skill"
        finally:
            if proc.stdin:
                proc.stdin.close()
            proc.wait(timeout=5)
            provider.shutdown()

    def test_shutdown_waits_for_inflight_acquire_without_closing_client(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        entered_ready = threading.Event()
        release_ready = threading.Event()
        acquire_errors: list[Exception] = []

        provider, server, _ = _install_provider(monkeypatch, tmp_path)
        # Allow shutdown() to manage client lifecycle so we verify client stays open while acquire is in-flight.
        provider._client_override = None

        def blocking_ready(_url: str, timeout: int = 30, headers: dict[str, str] | None = None) -> bool:
            del timeout, headers
            entered_ready.set()
            release_ready.wait(timeout=5)
            return True

        monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", blocking_ready)

        def run_acquire() -> None:
            try:
                provider.acquire("t-inflight", user_id="u1")
            except Exception as exc:
                acquire_errors.append(exc)

        worker = threading.Thread(target=run_acquire)
        worker.start()
        assert entered_ready.wait(timeout=5)

        # shutdown() sees in-flight acquire -> fails incomplete without closing client or ownership store.
        with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="acquire"):
            provider.shutdown()
        assert provider._shutdown_complete is False
        assert provider._client is not None and provider._client._closed is False

        # Unblock acquire -> rolls back using the still-open client, then retry shutdown completes cleanly.
        release_ready.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert len(acquire_errors) == 1
        assert isinstance(acquire_errors[0], RuntimeError)

        provider.shutdown()
        assert provider._shutdown_complete is True
        assert server.sandboxes == {}

    def test_warm_pool_reap_race_does_not_kill_reacquired_sandbox_or_drop_lease(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(monkeypatch, tmp_path, sandbox_overrides={"idle_timeout": 1})
        try:
            sandbox_id = provider.acquire("t-race", user_id="u1")
            provider.release(sandbox_id)
            assert sandbox_id in provider._warm_pool

            # Expire warm timestamp so _reap_expired_warm considers it eligible.
            entry, _ = provider._warm_pool[sandbox_id]
            provider._warm_pool[sandbox_id] = (entry, time.monotonic() - 10.0)

            # Case 1: acquire() reclaims the sandbox while _reap_expired_warm is about to destroy it.
            reap_entered = threading.Event()
            release_reap = threading.Event()
            orig_destroy_warm = provider._destroy_warm_entry

            def paused_destroy_warm(sid: str, warm_entry: Any, *, reason: str) -> bool:
                reap_entered.set()
                release_reap.wait(timeout=5)
                return orig_destroy_warm(sid, warm_entry, reason=reason)

            monkeypatch.setattr(provider, "_destroy_warm_entry", paused_destroy_warm)
            reaper = threading.Thread(target=provider._reap_expired_warm, args=(1.0,))
            reaper.start()
            assert reap_entered.wait(timeout=5)

            # Concurrent acquire reclaims the sandbox while reaper is paused before reservation.
            reacquired = provider.acquire("t-race", user_id="u1")
            assert reacquired == sandbox_id

            release_reap.set()
            reaper.join(timeout=5)
            assert not reaper.is_alive()

            # Active sandbox must remain tracked, open, alive on server, and still owned.
            assert provider.get(sandbox_id) is aio_instances[0]
            assert aio_instances[0].closed is False
            assert "vefaas-sb-1" in server.sandboxes
            assert not any(a == "KillSandbox" for a, _, _ in server.requests)

            # Case 2: once teardown reserves _local_teardown, a concurrent acquire refuses to promote it.
            provider.release(sandbox_id)
            entry2, _ = provider._warm_pool[sandbox_id]
            provider._warm_pool[sandbox_id] = (entry2, time.monotonic() - 10.0)

            kill_started = threading.Event()
            release_kill = threading.Event()
            orig_kill = provider._client.kill_sandbox

            def blocking_kill(fn_id: str, remote_id: str) -> None:
                kill_started.set()
                release_kill.wait(timeout=5)
                orig_kill(fn_id, remote_id)

            monkeypatch.setattr(provider._client, "kill_sandbox", blocking_kill)
            monkeypatch.setattr(provider, "_destroy_warm_entry", orig_destroy_warm)

            reaper2 = threading.Thread(target=provider._reap_expired_warm, args=(1.0,))
            reaper2.start()
            assert kill_started.wait(timeout=5)

            with pytest.raises(RuntimeError, match="currently being torn down"):
                provider.acquire("t-race", user_id="u1")

            release_kill.set()
            reaper2.join(timeout=5)
            assert not reaper2.is_alive()
            assert server.sandboxes == {}
        finally:
            provider.shutdown()

    def test_stale_renew_lost_does_not_forget_reacquired_sandbox(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _, aio_instances = _install_provider(monkeypatch, tmp_path)
        try:
            sandbox_id = provider.acquire("t-epoch", user_id="u1")

            # Simulate a renew() that observes a concurrent re-acquire (bumping epoch) before returning LOST.
            mock_store = MagicMock()
            mock_store.supports_cross_process = True

            def stale_renew(sid: str) -> RenewOutcome:
                with provider._lock:
                    provider._bump_acquire_epoch_locked(sid)
                return RenewOutcome.LOST

            mock_store.renew.side_effect = stale_renew
            provider._ownership = mock_store

            provider._renew_leases_once()
            assert provider.get(sandbox_id) is aio_instances[0]
            assert aio_instances[0].closed is False

            # Also verify _forget_lost_sandbox skips entries currently reserved for local teardown.
            with provider._lock:
                provider._local_teardown[sandbox_id] = 1
            try:
                provider._forget_lost_sandbox(sandbox_id)
                assert provider.get(sandbox_id) is aio_instances[0]
                assert aio_instances[0].closed is False
            finally:
                with provider._lock:
                    provider._local_teardown.pop(sandbox_id, None)
        finally:
            provider.shutdown()

    def test_release_recycles_dirty_or_pending_sandbox_instead_of_warm_pool(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(monkeypatch, tmp_path)
        try:
            sid1 = provider.acquire("t-dirty", user_id="u1")
            aio_instances[0].requires_container_recycle = True
            provider.release(sid1)
            assert sid1 not in provider._warm_pool
            assert sid1 not in provider._sandboxes
            assert "vefaas-sb-1" not in server.sandboxes

            sid2 = provider.acquire("t-pending", user_id="u1")
            aio_instances[1].has_pending_session_creates = True
            provider.release(sid2)
            assert sid2 not in provider._warm_pool
            assert sid2 not in provider._sandboxes
            assert "vefaas-sb-2" not in server.sandboxes
        finally:
            provider.shutdown()

    @pytest.mark.parametrize("retire_first", [False, True], ids=["active", "retired"])
    def test_shutdown_leaves_an_in_progress_output_mirror_retryable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, retire_first: bool) -> None:
        from deerflow.config.paths import get_paths

        provider, server, aio_instances = _install_provider(monkeypatch, tmp_path)
        provider._client_override = None
        sandbox_id = provider.acquire("mirror-thread", user_id="mirror-user")
        remote = aio_instances[0]
        remote.remote_outputs["/mnt/user-data/outputs/report.txt"] = b"completed report"
        original_download = remote.download_file
        download_started = threading.Event()
        finish_download = threading.Event()

        def paused_download(path: str, *, max_bytes: int | None = None) -> bytes:
            download_started.set()
            assert finish_download.wait(timeout=5)
            if remote.closed or not server.sandboxes:
                raise OSError("Sandbox was torn down before download completed")
            return original_download(path, max_bytes=max_bytes)

        monkeypatch.setattr(remote, "download_file", paused_download)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                release = executor.submit(provider.release, sandbox_id)
                try:
                    assert download_started.wait(timeout=5)
                    if retire_first:
                        provider.reset()
                        assert provider._evict_oldest_warm() is None
                    with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="output mirror"):
                        provider.shutdown()
                    assert not remote.closed
                    assert len(server.sandboxes) == 1
                    assert provider._client is not None and not provider._client._closed
                finally:
                    finish_download.set()
                release.result(timeout=5)

            mirrored = get_paths().sandbox_outputs_dir("mirror-thread", user_id="mirror-user") / "report.txt"
            assert mirrored.read_bytes() == b"completed report"
            provider.shutdown()
            assert provider._shutdown_complete
            assert remote.closed
            assert not server.sandboxes
        finally:
            provider.shutdown()

    def test_recycling_release_remains_visible_to_concurrent_shutdown(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, server, aio_instances = _install_provider(monkeypatch, tmp_path)
        provider._client_override = None
        sandbox_id = provider.acquire("t-recycle-race", user_id="u1")
        aio_instances[0].requires_container_recycle = True

        # Pause release right after _release_scope_locked unlocks and before _destroy_tracked runs.
        destroy_called = threading.Event()
        release_destroy = threading.Event()
        orig_destroy = provider._destroy_tracked

        def paused_destroy(tracked: Any, *, reason: str, **kwargs: Any) -> bool:
            if reason == "recycle_corrupted":
                destroy_called.set()
                release_destroy.wait(timeout=5)
            return orig_destroy(tracked, reason=reason, **kwargs)

        monkeypatch.setattr(provider, "_destroy_tracked", paused_destroy)
        releaser = threading.Thread(target=provider.release, args=(sandbox_id,))
        releaser.start()
        assert destroy_called.wait(timeout=5)

        # Pending destroy is already registered atomically under _lock, so shutdown() sees and kills it.
        assert "vefaas-sb-1" in provider._pending_destroys
        claim_calls_before_resume: list[tuple[str, bool]] = []
        orig_claim = provider._ownership.claim

        def spy_claim(sid: str, *, for_destroy: bool = False) -> bool:
            claim_calls_before_resume.append((sid, for_destroy))
            return orig_claim(sid, for_destroy=for_destroy)

        monkeypatch.setattr(provider._ownership, "claim", spy_claim)
        provider.shutdown()
        assert provider._shutdown_complete is True
        assert sum(1 for a, p, _ in server.requests if a == "KillSandbox" and p["SandboxId"] == "vefaas-sb-1") == 1
        assert server.sandboxes == {}
        assert provider._pending_destroys == {}
        claims_during_shutdown = len(claim_calls_before_resume)

        # Resume paused release after shutdown already completed the teardown and closed the client.
        release_destroy.set()
        releaser.join(timeout=5)
        assert not releaser.is_alive()

        # Deferred release teardown must be a no-op once shutdown has already completed the registration.
        assert provider._pending_destroys == {}
        assert provider._quarantined_remote_ids == {}
        assert len(claim_calls_before_resume) == claims_during_shutdown
        assert sum(1 for a, p, _ in server.requests if a == "KillSandbox" and p["SandboxId"] == "vefaas-sb-1") == 1
        assert provider._ownership.owner(sandbox_id) is None
        provider.shutdown()
        assert provider._pending_destroys == {}

    def test_adoption_verifies_initialization_and_restores_uploads_when_uninitialized(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from deerflow.config.paths import get_paths

        # Case A: uninitialized Running sandbox (worker crashed after CreateSandbox) restores host uploads & writes init marker.
        server_a = _FakeVeFaaSServer()
        sid_a = derive_sandbox_scope_token(user_id="u1", thread_id="t-uninit")
        server_a.sandboxes["vefaas-uninit-1"] = {
            "Id": "vefaas-uninit-1",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_a,
            },
        }
        provider_a, _, aio_a = _install_provider(monkeypatch, tmp_path / "case-a", server=server_a)
        try:
            uploads_dir = get_paths().sandbox_uploads_dir("t-uninit", user_id="u1")
            uploads_dir.mkdir(parents=True, exist_ok=True)
            (uploads_dir / "report.txt").write_text("from-host", encoding="utf-8")

            acquired = provider_a.acquire("t-uninit", user_id="u1")
            assert acquired == sid_a
            assert not any(a == "CreateSandbox" for a, _, _ in server_a.requests)
            aio = aio_a[0]
            assert provider_mod._BOOTSTRAP_COMMAND in aio.commands
            assert provider_mod._INIT_MARKER_PATH in aio.uploaded_files
            assert aio.uploaded_files[provider_mod._INIT_MARKER_PATH].decode("utf-8").strip() == sid_a
            # Verify the existing host upload was packaged and uploaded into /mnt/user-data.
            restored_names: set[str] = set()
            for path, raw in aio.uploaded_files.items():
                if path.endswith(".tar.gz"):
                    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
                        restored_names.update(tf.getnames())
            assert "uploads/report.txt" in restored_names
        finally:
            provider_a.shutdown()

        # Case B: already-initialized Running sandbox is adopted without re-running bootstrap or clobbering files.
        server_b = _FakeVeFaaSServer()
        sid_b = derive_sandbox_scope_token(user_id="u1", thread_id="t-inited")
        server_b.sandboxes["vefaas-inited-2"] = {
            "Id": "vefaas-inited-2",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        provider_b, _, aio_b = _install_provider(monkeypatch, tmp_path / "case-b", server=server_b)
        orig_ctor = provider_mod.AioSandbox

        def initialized_aio_ctor(**kwargs: Any) -> Any:
            inst = orig_ctor(**kwargs)
            inst.init_marker_override = f"INIT_MARKER:{sid_b}\n"
            return inst

        monkeypatch.setattr(provider_mod, "AioSandbox", initialized_aio_ctor)
        try:
            acquired_b = provider_b.acquire("t-inited", user_id="u1")
            assert acquired_b == sid_b
            assert not any(a == "CreateSandbox" for a, _, _ in server_b.requests)
            assert provider_mod._BOOTSTRAP_COMMAND not in aio_b[0].commands
            assert aio_b[0].uploaded_files == {}
        finally:
            provider_b.shutdown()

        # Case C: running sandbox with mismatched/invalid init marker is refused; fresh sandbox is provisioned.
        server_c = _FakeVeFaaSServer()
        sid_c = derive_sandbox_scope_token(user_id="u1", thread_id="t-mismatch")
        server_c.sandboxes["vefaas-bad-marker"] = {
            "Id": "vefaas-bad-marker",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_c,
            },
        }
        provider_c, _, aio_c = _install_provider(monkeypatch, tmp_path / "case-c", server=server_c)
        orig_ctor_c = provider_mod.AioSandbox

        def mismatch_first_ctor(**kwargs: Any) -> Any:
            inst = orig_ctor_c(**kwargs)
            if kwargs.get("request_headers", {}).get(provider_mod.INSTANCE_ROUTING_HEADER) == "vefaas-bad-marker":
                inst.init_marker_override = "INIT_MARKER:wrong-sandbox-id\n"
            return inst

        monkeypatch.setattr(provider_mod, "AioSandbox", mismatch_first_ctor)
        try:
            acquired_c = provider_c.acquire("t-mismatch", user_id="u1")
            assert acquired_c == sid_c
            assert any(a == "CreateSandbox" for a, _, _ in server_c.requests)
            assert aio_c[0].closed is True
            assert aio_c[1].request_headers[provider_mod.INSTANCE_ROUTING_HEADER] == "vefaas-sb-1"
        finally:
            provider_c.shutdown()

    def test_bootstrap_failure_blocks_init_marker_and_rolls_back(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Case A: fresh sandbox creation fails bootstrap (including PTY command-echo output without standalone marker).
        provider_a, server_a, aio_a = _install_provider(monkeypatch, tmp_path / "fresh")
        orig_ctor_a = provider_mod.AioSandbox

        def fail_bootstrap_fresh(**kwargs: Any) -> Any:
            inst = orig_ctor_a(**kwargs)
            inst.bootstrap_output_override = f"{provider_mod._BOOTSTRAP_COMMAND}\nmkdir: Permission denied\n"
            return inst

        monkeypatch.setattr(provider_mod, "AioSandbox", fail_bootstrap_fresh)
        try:
            with pytest.raises(RuntimeError, match="bootstrap failed"):
                provider_a.acquire("t-boot-fresh", user_id="u1")
            assert len(aio_a) == 1
            assert provider_mod._INIT_MARKER_PATH not in aio_a[0].uploaded_files
            assert any(a == "KillSandbox" for a, _, _ in server_a.requests)
            assert server_a.sandboxes == {}
        finally:
            provider_a.shutdown()

        # Case B: adoption of an uninitialized running sandbox fails bootstrap -> no marker, rolled back.
        server_b = _FakeVeFaaSServer()
        sid_b = derive_sandbox_scope_token(user_id="u1", thread_id="t-boot-adopt")
        server_b.sandboxes["vefaas-uninit-boot"] = {
            "Id": "vefaas-uninit-boot",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        provider_b, _, aio_b = _install_provider(monkeypatch, tmp_path / "adopt", server=server_b)
        orig_ctor_b = provider_mod.AioSandbox

        def fail_bootstrap_adopt(**kwargs: Any) -> Any:
            inst = orig_ctor_b(**kwargs)
            inst.fail_bootstrap = True
            return inst

        monkeypatch.setattr(provider_mod, "AioSandbox", fail_bootstrap_adopt)
        try:
            with pytest.raises(RuntimeError, match="bootstrap failed"):
                provider_b.acquire("t-boot-adopt", user_id="u1")
            assert len(aio_b) == 1
            assert provider_mod._INIT_MARKER_PATH not in aio_b[0].uploaded_files
            assert any(a == "KillSandbox" and p["SandboxId"] == "vefaas-uninit-boot" for a, p, _ in server_b.requests)
            assert server_b.sandboxes == {}
        finally:
            provider_b.shutdown()

    def test_concurrent_second_worker_does_not_restore_over_live_files(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        from deerflow.community.aio_sandbox.ownership import MemoryOwnershipStore
        from deerflow.config.paths import get_paths

        def _make_shared_remote_ctor(remote_files: dict[str, bytes], marker_holder: dict[str, bytes | None]) -> Callable[..., Any]:
            class _SharedRemoteAioSandbox(_FakeAioSandbox):
                def update_file(self, path: str, content: bytes) -> None:
                    super().update_file(path, content)
                    if path == provider_mod._INIT_MARKER_PATH:
                        marker_holder["marker"] = content

                def execute_command(self, command: str) -> str:
                    self.commands.append(command)
                    if command == provider_mod._BOOTSTRAP_COMMAND:
                        return f"{provider_mod._BOOTSTRAP_OK_MARKER}\n"
                    if "INIT_MARKER:" in command:
                        marker = marker_holder["marker"]
                        if marker is not None:
                            return f"INIT_MARKER:{marker.decode('utf-8').strip()}\n"
                        return "INIT_MARKER:MISSING\n"
                    if "UPLOAD_OK" in command:
                        # Extract uploaded tar archive into shared remote_files to observe overwrites.
                        for path, raw in list(self.uploaded_files.items()):
                            if path.endswith(".tar.gz") and path in command:
                                with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
                                    for member in tf.getmembers():
                                        if member.isfile():
                                            extracted = tf.extractfile(member)
                                            if extracted is not None:
                                                remote_files[member.name] = extracted.read()
                        return "UPLOAD_OK\n"
                    return ""

            return _SharedRemoteAioSandbox

        # Case A (cross-process style): shared ownership store + distinct in-process lock keys.
        # Worker A holds an exclusive claim while initializing; Worker B probes missing, sees claim() == False,
        # waits until Worker A finishes and writes a live file, then adopts without restoring stale host files.
        server_a = _FakeVeFaaSServer()
        sid_a = derive_sandbox_scope_token(user_id="u1", thread_id="t-peer-race")
        server_a.sandboxes["vefaas-shared-1"] = {
            "Id": "vefaas-shared-1",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_a,
            },
        }
        provider_1, _, _ = _install_provider(monkeypatch, tmp_path / "peer-a", server=server_a)
        provider_2, _, _ = _install_provider(monkeypatch, tmp_path / "peer-a", server=server_a)

        # Share one underlying ownership table across two distinct owner IDs (simulating two workers on Redis).
        shared_leases: dict[str, tuple[str, float]] = {}
        store_1 = MemoryOwnershipStore(owner_id="worker-1", ttl_seconds=60.0)
        store_2 = MemoryOwnershipStore(owner_id="worker-2", ttl_seconds=60.0)
        store_1._leases = shared_leases
        store_2._leases = shared_leases
        store_1._lock = store_2._lock
        provider_1._ownership = store_1
        provider_2._ownership = store_2

        # Simulate separate OS processes where in-process locks do not collide.
        provider_1._config["endpoint"] = "https://worker-1.vefaas.example"
        provider_2._config["endpoint"] = "https://worker-2.vefaas.example"

        remote_files_a: dict[str, bytes] = {}
        marker_a: dict[str, bytes | None] = {"marker": None}
        monkeypatch.setattr(provider_mod, "AioSandbox", _make_shared_remote_ctor(remote_files_a, marker_a))

        uploads_dir = get_paths().sandbox_uploads_dir("t-peer-race", user_id="u1")
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / "report.txt").write_text("stale-host-copy", encoding="utf-8")

        worker1_in_init = threading.Event()
        worker2_blocked_on_claim = threading.Event()
        orig_init_1 = provider_1._initialize_remote_sandbox
        orig_claim_2 = store_2.claim

        def paused_init_1(sandbox: Any, **kwargs: Any) -> None:
            worker1_in_init.set()
            assert worker2_blocked_on_claim.wait(timeout=5)
            orig_init_1(sandbox, **kwargs)
            # Simulate live agent write immediately after initialization completes.
            remote_files_a["uploads/report.txt"] = b"live-peer-write"

        def spy_claim_2(sid: str, *, for_destroy: bool = False) -> bool:
            res = orig_claim_2(sid, for_destroy=for_destroy)
            if not res:
                worker2_blocked_on_claim.set()
            return res

        monkeypatch.setattr(provider_1, "_initialize_remote_sandbox", paused_init_1)
        monkeypatch.setattr(store_2, "claim", spy_claim_2)

        errors: list[Exception] = []
        results: dict[str, str] = {}

        def run_worker(name: str, prov: VeFaaSSandboxProvider) -> None:
            try:
                results[name] = prov.acquire("t-peer-race", user_id="u1")
            except Exception as exc:  # pragma: no cover - surfaced via assertion
                errors.append(exc)

        try:
            t1 = threading.Thread(target=run_worker, args=("w1", provider_1))
            t2 = threading.Thread(target=run_worker, args=("w2", provider_2))
            t1.start()
            assert worker1_in_init.wait(timeout=5)
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
            assert not errors, f"Unexpected errors: {errors}"
            assert results == {"w1": sid_a, "w2": sid_a}
            assert remote_files_a["uploads/report.txt"] == b"live-peer-write"
        finally:
            provider_1.shutdown()
            provider_2.shutdown()

        # Case B (stale observation before claim): Worker B's first probe sees missing, then Worker A finishes
        # initialization, writes a live file, and releases ownership before Worker B claims. Worker B's post-claim
        # re-probe observes the marker and skips restoration.
        server_b = _FakeVeFaaSServer()
        sid_b = derive_sandbox_scope_token(user_id="u1", thread_id="t-stale-probe")
        server_b.sandboxes["vefaas-shared-2"] = {
            "Id": "vefaas-shared-2",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        provider_b, _, _ = _install_provider(monkeypatch, tmp_path / "peer-b", server=server_b)
        remote_files_b: dict[str, bytes] = {}
        marker_b: dict[str, bytes | None] = {"marker": None}
        monkeypatch.setattr(provider_mod, "AioSandbox", _make_shared_remote_ctor(remote_files_b, marker_b))

        uploads_dir_b = get_paths().sandbox_uploads_dir("t-stale-probe", user_id="u1")
        uploads_dir_b.mkdir(parents=True, exist_ok=True)
        (uploads_dir_b / "report.txt").write_text("stale-host-copy", encoding="utf-8")

        orig_claim_b = provider_b._ownership.claim

        def peer_finishes_before_claim(sid: str, *, for_destroy: bool = False) -> bool:
            # Peer finishes initialization and writes a live file just before this worker's claim succeeds.
            marker_b["marker"] = f"{sid_b}\n".encode()
            remote_files_b["uploads/report.txt"] = b"live-after-first-probe"
            return orig_claim_b(sid, for_destroy=for_destroy)

        monkeypatch.setattr(provider_b._ownership, "claim", peer_finishes_before_claim)
        try:
            acquired_b = provider_b.acquire("t-stale-probe", user_id="u1")
            assert acquired_b == sid_b
            assert remote_files_b["uploads/report.txt"] == b"live-after-first-probe"
        finally:
            provider_b.shutdown()

        # Case C (same-process separate stores): two providers with separate MemoryOwnershipStores
        # sharing the same remote endpoint/function/sandbox_id serialize via _remote_init_lock.
        server_c = _FakeVeFaaSServer()
        sid_c = derive_sandbox_scope_token(user_id="u1", thread_id="t-inproc-lock")
        server_c.sandboxes["vefaas-shared-3"] = {
            "Id": "vefaas-shared-3",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_c,
            },
        }
        provider_c1, _, _ = _install_provider(monkeypatch, tmp_path / "peer-c", server=server_c)
        provider_c2, _, _ = _install_provider(monkeypatch, tmp_path / "peer-c", server=server_c)
        remote_files_c: dict[str, bytes] = {}
        marker_c: dict[str, bytes | None] = {"marker": None}
        monkeypatch.setattr(provider_mod, "AioSandbox", _make_shared_remote_ctor(remote_files_c, marker_c))

        uploads_dir_c = get_paths().sandbox_uploads_dir("t-inproc-lock", user_id="u1")
        uploads_dir_c.mkdir(parents=True, exist_ok=True)
        (uploads_dir_c / "report.txt").write_text("stale-host-copy", encoding="utf-8")

        c1_in_init = threading.Event()
        release_c1 = threading.Event()
        orig_init_c1 = provider_c1._initialize_remote_sandbox

        def paused_init_c1(sandbox: Any, **kwargs: Any) -> None:
            c1_in_init.set()
            assert release_c1.wait(timeout=5)
            orig_init_c1(sandbox, **kwargs)
            remote_files_c["uploads/report.txt"] = b"live-inproc-write"

        monkeypatch.setattr(provider_c1, "_initialize_remote_sandbox", paused_init_c1)

        c_errors: list[Exception] = []
        c_results: dict[str, str] = {}

        def run_c(name: str, prov: VeFaaSSandboxProvider) -> None:
            try:
                c_results[name] = prov.acquire("t-inproc-lock", user_id="u1")
            except Exception as exc:  # pragma: no cover - surfaced via assertion
                c_errors.append(exc)

        try:
            tc1 = threading.Thread(target=run_c, args=("c1", provider_c1))
            tc2 = threading.Thread(target=run_c, args=("c2", provider_c2))
            tc1.start()
            assert c1_in_init.wait(timeout=5)
            tc2.start()
            # Give c2 a moment to contend on _remote_init_lock while c1 is initializing.
            time.sleep(0.05)
            release_c1.set()
            tc1.join(timeout=5)
            tc2.join(timeout=5)
            assert not c_errors, f"Unexpected errors: {c_errors}"
            assert c_results == {"c1": sid_c, "c2": sid_c}
            assert remote_files_c["uploads/report.txt"] == b"live-inproc-write"
        finally:
            provider_c1.shutdown()
            provider_c2.shutdown()

        # Case D (peer holds lease indefinitely without publishing marker): fail closed on timeout
        # rather than stealing ownership and restoring stale files over a live peer.
        server_d = _FakeVeFaaSServer()
        sid_d = derive_sandbox_scope_token(user_id="u1", thread_id="t-peer-timeout")
        server_d.sandboxes["vefaas-shared-4"] = {
            "Id": "vefaas-shared-4",
            "FunctionId": "fn-demo-app",
            "Status": "Running",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_d,
            },
        }
        provider_d, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "peer-d",
            server=server_d,
            sandbox_overrides={"vefaas": {"ready_timeout": 0.05}},
        )
        remote_files_d: dict[str, bytes] = {"uploads/report.txt": b"untouched"}
        marker_d: dict[str, bytes | None] = {"marker": None}
        monkeypatch.setattr(provider_mod, "AioSandbox", _make_shared_remote_ctor(remote_files_d, marker_d))
        monkeypatch.setattr(provider_d._ownership, "claim", lambda _sid, *, for_destroy=False: False)
        try:
            with pytest.raises(RuntimeError, match="Timed out waiting for peer to initialize"):
                provider_d.acquire("t-peer-timeout", user_id="u1")
            assert remote_files_d["uploads/report.txt"] == b"untouched"
        finally:
            provider_d.shutdown()
