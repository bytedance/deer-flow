"""Offline unit tests for the BytePlus veFaaS Cloud Sandbox community provider.

All control-plane tests drive ``VeFaaSClient`` through ``httpx.MockTransport``
(no live network calls, no cloud credentials required).
"""

from __future__ import annotations

import datetime
import io
import json
import tarfile
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

    def execute_command(self, command: str) -> str:
        self.commands.append(command)
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
                if all(record["Metadata"].get(k) == v for k, v in wanted_meta.items()):
                    items.append(
                        {
                            "Id": record["Id"],
                            "FunctionId": record["FunctionId"],
                            "Status": record["Status"],
                            "Pending": record["Pending"],
                            "Metadata": dict(record["Metadata"]),
                        }
                    )
            return httpx.Response(
                200,
                json={"ResponseMetadata": {"RequestId": "req-list"}, "Result": {"Sandboxes": items, "Total": len(items)}},
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

        # Function-level 404s indicate misconfiguration and must not report sandbox absence.
        server.describe_error = (404, "FunctionNotFound", "function does not exist")
        with pytest.raises(VeFaaSApiError):
            client.describe_sandbox("fn-1", "missing-id")

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
            # Initial acquire uploads the shared skills projection once.
            assert len(aio.uploaded_files) == 1
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
