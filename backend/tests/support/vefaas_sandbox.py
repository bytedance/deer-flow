"""Shared offline test doubles and setup helpers for BytePlus veFaaS sandbox tests."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from deerflow.community.vefaas_sandbox import VeFaaSClient, VeFaaSSandboxProvider
from deerflow.community.vefaas_sandbox import provider as provider_mod
from deerflow.config.sandbox_config import SandboxConfig
from deerflow.sandbox.sandbox_provider import hold_sandbox_shutdown_ownership


class FakeAioSandbox:
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

    def release_command_scope(self, scope_id: str) -> None:
        del scope_id

    def close(self) -> None:
        self.closed = True


class FakeVeFaaSServer:
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


def make_vefaas_app_config(
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


def install_vefaas_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    server: FakeVeFaaSServer | None = None,
    sandbox_overrides: dict[str, Any] | None = None,
    ready_result: bool = True,
) -> tuple[VeFaaSSandboxProvider, FakeVeFaaSServer, list[FakeAioSandbox]]:
    fake_server = server or FakeVeFaaSServer()
    mock_http = httpx.Client(transport=httpx.MockTransport(fake_server.handler))
    app_cfg = make_vefaas_app_config(tmp_path, sandbox_overrides=sandbox_overrides)
    monkeypatch.setattr(provider_mod, "get_app_config", lambda: app_cfg)
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path / "deer-flow-home"))
    monkeypatch.setattr("deerflow.config.paths._paths", None)

    created_aio: list[FakeAioSandbox] = []

    def fake_aio_ctor(**kwargs: Any) -> FakeAioSandbox:
        inst = FakeAioSandbox(**kwargs)
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


__all__ = [
    "FakeAioSandbox",
    "FakeVeFaaSServer",
    "install_vefaas_provider",
    "make_vefaas_app_config",
]
