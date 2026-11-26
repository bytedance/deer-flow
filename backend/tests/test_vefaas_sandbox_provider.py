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
from support.vefaas_sandbox import (
    FakeAioSandbox as _FakeAioSandbox,
)
from support.vefaas_sandbox import (
    FakeVeFaaSServer as _FakeVeFaaSServer,
)
from support.vefaas_sandbox import (
    install_vefaas_provider as _install_provider,
)
from support.vefaas_sandbox import (
    make_vefaas_app_config as _make_app_config,
)

from deerflow.community.aio_sandbox.ownership import MemoryOwnershipStore, OwnershipBackendError, RenewOutcome
from deerflow.community.provider_credentials import REDACTION_MARKER
from deerflow.community.vefaas_sandbox import (
    VeFaaSApiError,
    VeFaaSClient,
    VeFaaSPrecacheTicket,
    VeFaaSSandboxNotFoundError,
    VeFaaSSandboxProvider,
    VeFaaSSnapshotNotFoundError,
    VeFaaSSnapshotRecord,
    sign_v4_headers,
)
from deerflow.community.vefaas_sandbox import provider as provider_mod
from deerflow.sandbox.identity import derive_sandbox_scope_token

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
            mock_store.owner.return_value = None
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
            mock_store.owner.return_value = None

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


# ── Phase 2: Snapshots, Pause/Resume & Image Precache ────────────────────


class TestVeFaaSClientSnapshotsPausePrecache:
    def _make_client(self, server: _FakeVeFaaSServer) -> VeFaaSClient:
        return VeFaaSClient(
            endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
            region="ap-southeast-1",
            access_key="AK-TEST-KEY",
            secret_key="SK-TEST-SECRET",
            httpx_client=httpx.Client(transport=httpx.MockTransport(server.handler)),
        )

    def test_create_sandbox_passes_snapshot_id_and_auto_pause_config(self) -> None:
        server = _FakeVeFaaSServer()
        client = self._make_client(server)
        try:
            remote_id = client.create_sandbox(
                "fn-demo",
                snapshot_id="snap-base-1",
                auto_pause_config={"Enable": True, "SnapshotType": "full"},
            )
            assert remote_id == "vefaas-sb-1"
            action, payload, _ = server.requests[-1]
            assert action == "CreateSandbox"
            assert payload["SnapshotId"] == "snap-base-1"
            assert payload["AutoPauseConfig"] == {"Enable": True, "SnapshotType": "full"}

            # When omitted, neither field is serialized.
            client.create_sandbox("fn-demo")
            _, plain_payload, _ = server.requests[-1]
            assert "SnapshotId" not in plain_payload
            assert "AutoPauseConfig" not in plain_payload
        finally:
            client.close()

    def test_pause_and_resume_sandbox_payloads_and_status_helpers(self) -> None:
        server = _FakeVeFaaSServer()
        server.pause_status_sequence = ["Pausing", "Paused"]
        server.resume_status_sequence = ["Resuming", "Running"]
        client = self._make_client(server)
        try:
            remote_id = client.create_sandbox("fn-demo")
            client.pause_sandbox("fn-demo", remote_id)

            first_desc = client.describe_sandbox("fn-demo", remote_id)
            assert first_desc is not None
            assert first_desc.is_transitioning and not first_desc.is_paused
            assert first_desc.paused_at == "2026-11-23T01:00:00Z"

            second_desc = client.describe_sandbox("fn-demo", remote_id)
            assert second_desc is not None
            assert second_desc.is_paused and not second_desc.is_running and not second_desc.is_terminal_failure

            resume_status = client.resume_sandbox(
                "fn-demo",
                remote_id,
                snapshot_id="snap-99",
                timeout_minutes=90,
                async_resume=True,
            )
            assert resume_status == "Resuming"
            action, payload, _ = server.requests[-1]
            assert action == "ResumeSandbox"
            assert payload == {
                "FunctionId": "fn-demo",
                "SandboxId": remote_id,
                "SnapshotId": "snap-99",
                "Timeout": 90,
                "TimeoutUnit": "minute",
                "Async": True,
            }

            with pytest.raises(VeFaaSSandboxNotFoundError):
                client.pause_sandbox("fn-demo", "vefaas-missing")
        finally:
            client.close()

    def test_snapshot_crud_pagination_idempotency_and_fail_closed(self) -> None:
        server = _FakeVeFaaSServer()
        client = self._make_client(server)
        try:
            remote_id = client.create_sandbox("fn-demo")
            created_ids = [
                client.create_sandbox_snapshot(
                    "fn-demo",
                    remote_id,
                    snapshot_type="disk",
                    retention_days=7,
                    metadata={"k": f"v{i}"},
                )
                for i in range(5)
            ]
            assert len(created_ids) == 5
            create_reqs = [payload for action, payload, _ in server.requests if action == "CreateSandboxSnapshot"]
            assert create_reqs[0] == {
                "FunctionId": "fn-demo",
                "SandboxId": remote_id,
                "Type": "disk",
                "RetentionDays": 7,
                "Metadata": {"k": "v0"},
            }

            snap = client.describe_sandbox_snapshot("fn-demo", created_ids[0])
            assert isinstance(snap, VeFaaSSnapshotRecord)
            assert snap.id == created_ids[0]
            assert snap.is_ready
            assert snap.retention_days == 7
            assert snap.metadata == {"k": "v0"}

            # Authoritative SnapshotNotFound returns None.
            assert client.describe_sandbox_snapshot("fn-demo", "snap-does-not-exist") is None

            # Pagination fetches all 5 across 3 pages.
            listed = client.list_sandbox_snapshots("fn-demo", page_size=2)
            assert [s.id for s in listed] == created_ids
            list_calls = [payload for action, payload, _ in server.requests if action == "ListSandboxSnapshots"]
            assert [c["PageNumber"] for c in list_calls] == [1, 2, 3]

            # Delete is idempotent on SnapshotNotFound.
            client.delete_sandbox_snapshot("fn-demo", created_ids[0])
            client.delete_sandbox_snapshot("fn-demo", created_ids[0])
            assert client.describe_sandbox_snapshot("fn-demo", created_ids[0]) is None
        finally:
            client.close()

        # Fail closed on malformed DescribeSandboxSnapshot response (not SnapshotNotFound).
        def malformed_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"ResponseMetadata": {"RequestId": "req-bad"}, "Result": {"Snapshot": {}}})

        bad_client = VeFaaSClient(
            endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
            region="ap-southeast-1",
            access_key="ak",
            secret_key="sk",
            httpx_client=httpx.Client(transport=httpx.MockTransport(malformed_handler)),
        )
        try:
            with pytest.raises(VeFaaSApiError, match="valid snapshot record"):
                bad_client.describe_sandbox_snapshot("fn-demo", "snap-1")
        finally:
            bad_client.close()

        # Generic 404 with non-snapshot error code must raise VeFaaSApiError, not return None.
        def generic_404_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={"ResponseMetadata": {"RequestId": "req-404", "Error": {"Code": "FunctionNotFound", "Message": "fn missing"}}},
            )

        err_client = VeFaaSClient(
            endpoint="https://vefaas.ap-southeast-1.byteplusapi.com",
            region="ap-southeast-1",
            access_key="ak",
            secret_key="sk",
            httpx_client=httpx.Client(transport=httpx.MockTransport(generic_404_handler)),
        )
        try:
            with pytest.raises(VeFaaSApiError) as exc_info:
                err_client.describe_sandbox_snapshot("fn-missing", "snap-1")
            assert not isinstance(exc_info.value, VeFaaSSnapshotNotFoundError)
        finally:
            err_client.close()

    def test_precache_sandbox_images_and_ticket_parsing(self) -> None:
        server = _FakeVeFaaSServer()
        server.precache_status_sequence = ["Running", "Succeeded"]
        client = self._make_client(server)
        try:
            with pytest.raises(ValueError, match="sequence"):
                client.precache_sandbox_images("img:latest")  # type: ignore[arg-type]
            with pytest.raises(ValueError, match="non-empty"):
                client.precache_sandbox_images([])
            with pytest.raises(ValueError, match="non-empty"):
                client.precache_sandbox_images(["img:v1", "   "])

            ticket_id = client.precache_sandbox_images([" img:v1 ", "img:v2", "img:v1"], client_token="tok-1")
            assert ticket_id == "ticket-1"
            action, payload, _ = server.requests[-1]
            assert action == "PrecacheSandboxImages"
            assert payload == {"ImageUrls": ["img:v1", "img:v2"], "ClientToken": "tok-1"}

            t1 = client.get_sandbox_image_precache_ticket(ticket_id)
            assert isinstance(t1, VeFaaSPrecacheTicket)
            assert not t1.is_succeeded and not t1.is_terminal_failure
            t2 = client.get_sandbox_image_precache_ticket(ticket_id)
            assert t2.is_succeeded
            assert t2.duration == 12
        finally:
            client.close()


class TestVeFaaSPhase2ConfigValidation:
    @pytest.mark.parametrize(
        ("vefaas_override", "expected_error"),
        [
            ({"snapshot_id": "   "}, "snapshot_id"),
            ({"snapshot_id": 123}, "snapshot_id"),
            ({"snapshot_type": "memory"}, "snapshot_type"),
            ({"snapshot_type": ""}, "snapshot_type"),
            ({"snapshot_retention_days": 0}, "snapshot_retention_days"),
            ({"snapshot_retention_days": 366}, "snapshot_retention_days"),
            ({"snapshot_retention_days": True}, "snapshot_retention_days"),
            ({"snapshot_timeout": 0}, "snapshot_timeout"),
            ({"snapshot_timeout": True}, "snapshot_timeout"),
            ({"max_snapshots_per_sandbox": 0}, "max_snapshots_per_sandbox"),
            ({"max_snapshots_per_sandbox": 101}, "max_snapshots_per_sandbox"),
            ({"pause_on_idle": "yes"}, "pause_on_idle"),
            ({"auto_pause": 1}, "auto_pause"),
            ({"snapshot_on_idle": "true"}, "snapshot_on_idle"),
            ({"precache_on_startup": "false"}, "precache_on_startup"),
            ({"precache_images": "cr.example.com/app:latest"}, "precache_images"),
            ({"precache_images": ["cr.example.com/app:latest", ""]}, "precache_images"),
        ],
    )
    def test_rejects_invalid_phase2_config_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        vefaas_override: dict[str, Any],
        expected_error: str,
    ) -> None:
        with pytest.raises(ValueError, match=expected_error):
            _install_provider(monkeypatch, tmp_path, sandbox_overrides={"vefaas": vefaas_override})

    def test_accepts_and_normalizes_valid_phase2_config(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={
                "vefaas": {
                    "snapshot_id": " snap-base-01 ",
                    "pause_on_idle": True,
                    "auto_pause": True,
                    "snapshot_on_idle": True,
                    "snapshot_type": "FULL",
                    "snapshot_retention_days": 14,
                    "snapshot_timeout": 90,
                    "max_snapshots_per_sandbox": 5,
                    "precache_images": ["img:1", " img:2 ", "img:1"],
                    "precache_on_startup": False,
                }
            },
        )
        try:
            assert provider._config["snapshot_id"] == "snap-base-01"
            assert provider._config["pause_on_idle"] is True
            assert provider._config["auto_pause"] is True
            assert provider._config["snapshot_on_idle"] is True
            assert provider._config["snapshot_type"] == "full"
            assert provider._config["snapshot_retention_days"] == 14
            assert provider._config["snapshot_timeout"] == 90.0
            assert provider._config["max_snapshots_per_sandbox"] == 5
            assert provider._config["precache_images"] == ["img:1", "img:2"]
            assert provider._config["precache_on_startup"] is False
        finally:
            provider.shutdown()


class TestVeFaaSPauseResumeLifecycle:
    def test_pause_on_idle_pauses_warm_sandbox_and_subsequent_acquire_resumes_preserving_state(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        from deerflow.config.paths import get_paths

        server = _FakeVeFaaSServer()
        server.pause_status_sequence = ["Pausing", "Paused"]
        server.resume_status_sequence = ["Resuming", "Running"]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"pause_on_idle": True}},
        )
        # Share in-memory files across AioSandbox handles to simulate persisted sandbox disk.
        persisted_files: dict[str, bytes] = {}

        class _PersistingAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_files

        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAio)
        try:
            sid = provider.acquire("t-pause", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            # Simulate live workspace file written during turn 1 + stale host copy.
            persisted_files["live-state"] = b"turn-1-data"
            uploads_dir = get_paths().sandbox_uploads_dir("t-pause", user_id="u1")
            uploads_dir.mkdir(parents=True, exist_ok=True)
            (uploads_dir / "stale.txt").write_text("should-not-overwrite", encoding="utf-8")

            provider.release(sid)
            tracked, _ = provider._warm_pool[sid]
            provider._warm_pool[sid] = (tracked, time.monotonic() - 100.0)
            provider._reap_expired_warm(1.0)

            assert sid not in provider._warm_pool
            assert tracked.sandbox.closed is True
            assert provider._ownership.owner(sid) is None
            assert server.sandboxes[remote_id]["Status"] == "Paused"
            actions = [action for action, _, _ in server.requests]
            assert "PauseSandbox" in actions
            assert "KillSandbox" not in actions

            # Turn 2: acquire discovers Paused sandbox, calls ResumeSandbox, preserves state.
            tars_before_resume = {path for path in persisted_files if path.startswith("/tmp/deerflow-vefaas-")}
            resumed_sid = provider.acquire("t-pause", user_id="u1")
            assert resumed_sid == sid
            resumed_tracked = provider._sandboxes[sid]
            assert resumed_tracked.remote_sandbox_id == remote_id
            assert server.sandboxes[remote_id]["Status"] == "Running"
            resume_reqs = [payload for action, payload, _ in server.requests if action == "ResumeSandbox"]
            assert len(resume_reqs) == 1
            assert resume_reqs[0]["SandboxId"] == remote_id
            assert resume_reqs[0]["Timeout"] == 60
            assert resume_reqs[0]["TimeoutUnit"] == "minute"
            # Must NOT re-create a new sandbox or re-upload stale host files on resume.
            create_reqs = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert len(create_reqs) == 1
            assert persisted_files["live-state"] == b"turn-1-data"
            tars_after_resume = {path for path in persisted_files if path.startswith("/tmp/deerflow-vefaas-")}
            assert tars_after_resume == tars_before_resume
            assert provider_mod._BOOTSTRAP_COMMAND not in resumed_tracked.sandbox.commands
        finally:
            provider.shutdown()

    def test_pause_on_idle_falls_back_to_kill_when_pause_fails_or_never_pauses(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case 1: PauseSandbox returns 403 -> falls back to KillSandbox.
        server1 = _FakeVeFaaSServer()
        server1.pause_error = (403, "UnsupportedOperation", "pause not enabled")
        provider1, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "c1",
            server=server1,
            sandbox_overrides={"vefaas": {"pause_on_idle": True}},
        )
        try:
            sid1 = provider1.acquire("t-pfail", user_id="u1")
            remote_id1 = provider1._sandboxes[sid1].remote_sandbox_id
            provider1.release(sid1)
            entry1, _ = provider1._warm_pool[sid1]
            provider1._warm_pool[sid1] = (entry1, time.monotonic() - 100.0)
            provider1._reap_expired_warm(1.0)

            assert remote_id1 not in server1.sandboxes
            assert sid1 not in provider1._warm_pool
            assert provider1._ownership.owner(sid1) is None
            assert not provider1._pending_destroys
            actions1 = [action for action, _, _ in server1.requests]
            assert "PauseSandbox" in actions1 and "KillSandbox" in actions1
        finally:
            provider1.shutdown()

        # Case 2: PauseSandbox accepted, but DescribeSandbox stays Running -> falls back to KillSandbox.
        server2 = _FakeVeFaaSServer()
        server2.pause_status_sequence = ["Running"]
        provider2, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "c2",
            server=server2,
            sandbox_overrides={"vefaas": {"pause_on_idle": True}},
        )
        try:
            sid2 = provider2.acquire("t-pstuck", user_id="u1")
            remote_id2 = provider2._sandboxes[sid2].remote_sandbox_id
            provider2.release(sid2)
            entry2, _ = provider2._warm_pool[sid2]
            provider2._warm_pool[sid2] = (entry2, time.monotonic() - 100.0)
            provider2._reap_expired_warm(1.0)

            assert remote_id2 not in server2.sandboxes
            assert not provider2._pending_destroys
        finally:
            provider2.shutdown()

    def test_dirty_or_peer_owned_sandbox_is_never_paused_or_snapshotted(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case 1: dirty sandbox in warm pool -> killed directly, never paused or snapshotted.
        server = _FakeVeFaaSServer()
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "dirty",
            server=server,
            sandbox_overrides={"vefaas": {"pause_on_idle": True, "snapshot_on_idle": True}},
        )
        try:
            sid = provider.acquire("t-dirty", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            provider.release(sid)
            entry, _ = provider._warm_pool[sid]
            entry.sandbox.requires_container_recycle = True
            provider._warm_pool[sid] = (entry, time.monotonic() - 100.0)
            provider._reap_expired_warm(1.0)

            assert remote_id not in server.sandboxes
            actions = [action for action, _, _ in server.requests]
            assert "PauseSandbox" not in actions
            assert "CreateSandboxSnapshot" not in actions
            assert "KillSandbox" in actions
        finally:
            provider.shutdown()

        # Case 2: peer owns lease -> never paused, snapshotted, or killed.
        server_peer = _FakeVeFaaSServer()
        provider_peer, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "peer",
            server=server_peer,
            sandbox_overrides={"vefaas": {"pause_on_idle": True, "snapshot_on_idle": True}},
        )
        try:
            sid_p = provider_peer.acquire("t-peer-own", user_id="u1")
            remote_id_p = provider_peer._sandboxes[sid_p].remote_sandbox_id
            provider_peer.release(sid_p)
            entry_p, _ = provider_peer._warm_pool[sid_p]
            provider_peer._warm_pool[sid_p] = (entry_p, time.monotonic() - 100.0)
            monkeypatch.setattr(provider_peer._ownership, "claim", lambda _sid, *, for_destroy=False: False)
            provider_peer._reap_expired_warm(1.0)

            assert remote_id_p in server_peer.sandboxes
            assert server_peer.sandboxes[remote_id_p]["Status"] == "Running"
            actions_p = [action for action, _, _ in server_peer.requests]
            assert "PauseSandbox" not in actions_p
            assert "CreateSandboxSnapshot" not in actions_p
            assert "KillSandbox" not in actions_p
        finally:
            provider_peer.shutdown()

    def test_discover_waits_for_pausing_sandbox_and_handles_resume_races_and_errors(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: ListSandboxes returns Pausing -> settles to Paused -> resumes without duplicate CreateSandbox.
        server = _FakeVeFaaSServer()
        sid = derive_sandbox_scope_token(user_id="u1", thread_id="t-pausing")
        server.sandboxes["vefaas-pausing-1"] = {
            "Id": "vefaas-pausing-1",
            "FunctionId": "fn-demo-app",
            "Status": "Pausing",
            "_status_queue": ["Pausing", "Paused"],
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid,
            },
        }
        provider, _, _ = _install_provider(monkeypatch, tmp_path / "case-a", server=server)

        class _PreInitAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{sid}\n".encode()

        monkeypatch.setattr(provider_mod, "AioSandbox", _PreInitAio)
        try:
            acquired = provider.acquire("t-pausing", user_id="u1")
            assert acquired == sid
            assert provider._sandboxes[sid].remote_sandbox_id == "vefaas-pausing-1"
            assert not any(action == "CreateSandbox" for action, _, _ in server.requests)
            assert sum(1 for action, _, _ in server.requests if action == "ResumeSandbox") == 1
        finally:
            provider.shutdown()

        # Case B: Concurrent resume by two providers -> only ONE ResumeSandbox issued.
        server_b = _FakeVeFaaSServer()
        sid_b = derive_sandbox_scope_token(user_id="u1", thread_id="t-conc-resume")
        server_b.sandboxes["vefaas-paused-2"] = {
            "Id": "vefaas-paused-2",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        p1, _, _ = _install_provider(monkeypatch, tmp_path / "case-b", server=server_b)
        p2, _, _ = _install_provider(monkeypatch, tmp_path / "case-b", server=server_b)
        # Share ownership store between p1 and p2 (distinct owner IDs).
        p2._ownership = p1._ownership

        class _PreInitAioB(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{sid_b}\n".encode()

        monkeypatch.setattr(provider_mod, "AioSandbox", _PreInitAioB)
        errors_b: list[Exception] = []
        results_b: dict[str, str] = {}

        def run_acquire(name: str, prov: VeFaaSSandboxProvider) -> None:
            try:
                results_b[name] = prov.acquire("t-conc-resume", user_id="u1")
            except Exception as exc:  # pragma: no cover
                errors_b.append(exc)

        try:
            t1 = threading.Thread(target=run_acquire, args=("p1", p1))
            t2 = threading.Thread(target=run_acquire, args=("p2", p2))
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
            assert not errors_b, f"Unexpected errors: {errors_b}"
            assert results_b == {"p1": sid_b, "p2": sid_b}
            assert sum(1 for action, _, _ in server_b.requests if action == "ResumeSandbox") == 1
            assert not any(action == "CreateSandbox" for action, _, _ in server_b.requests)
        finally:
            p1.shutdown()
            p2.shutdown()

        # Case C: ResumeSandbox fails with 500 -> fail closed, release ownership, no duplicate CreateSandbox.
        server_c = _FakeVeFaaSServer()
        server_c.resume_error = (500, "InternalError", "backend busy")
        sid_c = derive_sandbox_scope_token(user_id="u1", thread_id="t-resume-err")
        server_c.sandboxes["vefaas-paused-3"] = {
            "Id": "vefaas-paused-3",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_c,
            },
        }
        provider_c, _, _ = _install_provider(monkeypatch, tmp_path / "case-c", server=server_c)
        try:
            with pytest.raises(VeFaaSApiError, match="backend busy"):
                provider_c.acquire("t-resume-err", user_id="u1")
            assert provider_c._ownership.owner(sid_c) is None
            assert not any(action == "CreateSandbox" for action, _, _ in server_c.requests)
        finally:
            provider_c.shutdown()

        # Case D: Paused sandbox expires (SandboxNotFound) right when ResumeSandbox fires -> creates fresh sandbox.
        server_d = _FakeVeFaaSServer()
        sid_d = derive_sandbox_scope_token(user_id="u1", thread_id="t-resume-404")
        server_d.sandboxes["vefaas-paused-4"] = {
            "Id": "vefaas-paused-4",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_d,
            },
        }
        server_d.resume_error = (404, "SandboxNotFound", "expired while paused")
        provider_d, _, _ = _install_provider(monkeypatch, tmp_path / "case-d", server=server_d)
        try:
            acquired_d = provider_d.acquire("t-resume-404", user_id="u1")
            assert acquired_d == sid_d
            assert sum(1 for action, _, _ in server_d.requests if action == "CreateSandbox") == 1
        finally:
            provider_d.shutdown()

    def test_auto_pause_config_sent_on_create_sandbox(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": True, "snapshot_type": "full"}},
        )
        try:
            provider.acquire("t-autopause", user_id="u1")
            create_reqs = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert len(create_reqs) == 1
            assert create_reqs[0]["AutoPauseConfig"] == {"Enable": True, "SnapshotType": "full"}
        finally:
            provider.shutdown()


class TestVeFaaSSnapshotLifecycleAndIsolation:
    def test_snapshot_on_idle_captures_prunes_destroys_and_restores_with_tenant_isolation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating", "Ready"]
        sid_u1 = derive_sandbox_scope_token(user_id="u1", thread_id="t-snap")
        sid_u2 = derive_sandbox_scope_token(user_id="u2", thread_id="t-snap")

        # Pre-seed 2 older ready snapshots for u1 and 1 ready snapshot for u2.
        server.snapshots["snap-u1-old-1"] = {
            "SnapshotId": "snap-u1-old-1",
            "SandboxId": "vefaas-old-1",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-22T00:01:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_u1,
            },
        }
        server.snapshots["snap-u1-old-2"] = {
            "SnapshotId": "snap-u1-old-2",
            "SandboxId": "vefaas-old-2",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-22T00:02:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_u1,
            },
        }
        server.snapshots["snap-u2-other"] = {
            "SnapshotId": "snap-u2-other",
            "SandboxId": "vefaas-u2-1",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T23:59:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_u2,
            },
        }

        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={
                "vefaas": {
                    "snapshot_on_idle": True,
                    "snapshot_type": "disk",
                    "snapshot_retention_days": 7,
                    "max_snapshots_per_sandbox": 2,
                }
            },
        )
        try:
            # First acquire for u1 restores newest ready u1 snapshot (snap-u1-old-2), NEVER u2's newer snapshot!
            acquired_u1 = provider.acquire("t-snap", user_id="u1")
            assert acquired_u1 == sid_u1
            first_create = [payload for action, payload, _ in server.requests if action == "CreateSandbox"][0]
            assert first_create["SnapshotId"] == "snap-u1-old-2"

            # Release and expire warm pool -> creates new snapshot snap-1, prunes snap-u1-old-1, preserves u2's snapshot, kills sandbox.
            remote_1 = provider._sandboxes[sid_u1].remote_sandbox_id
            provider.release(sid_u1)
            entry, _ = provider._warm_pool[sid_u1]
            provider._warm_pool[sid_u1] = (entry, time.monotonic() - 100.0)
            provider._reap_expired_warm(1.0)

            assert remote_1 not in server.sandboxes
            assert "snap-1" in server.snapshots
            assert "snap-u1-old-2" in server.snapshots
            assert "snap-u1-old-1" not in server.snapshots
            assert "snap-u2-other" in server.snapshots
            assert server.snapshots["snap-1"]["RetentionDays"] == 7
            assert server.snapshots["snap-1"]["Metadata"][provider_mod.META_KEY_SANDBOX_ID] == sid_u1

            # Next acquire for u1 boots from the newly captured snap-1.
            provider.acquire("t-snap", user_id="u1")
            creates = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert creates[-1]["SnapshotId"] == "snap-1"

            # Acquire for u3 (no snapshots) creates without SnapshotId.
            provider.acquire("t-snap", user_id="u3")
            creates = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert "SnapshotId" not in creates[-1]
        finally:
            provider.shutdown()

    def test_base_snapshot_and_expired_thread_snapshot_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.validate_snapshot_on_create = True
        server.snapshots["snap-base"] = {
            "SnapshotId": "snap-base",
            "SandboxId": "template",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-20T00:00:00Z",
            "Metadata": {},
        }
        sid = derive_sandbox_scope_token(user_id="u1", thread_id="t-snap-race")
        server.snapshots["snap-ephemeral"] = {
            "SnapshotId": "snap-ephemeral",
            "SandboxId": "old",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T00:00:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid,
            },
        }

        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "fallback",
            server=server,
            sandbox_overrides={"vefaas": {"snapshot_id": "snap-base", "snapshot_on_idle": True}},
        )
        # Simulate snap-ephemeral expiring right between ListSandboxSnapshots and CreateSandbox.
        orig_find = provider._find_latest_ready_snapshot

        def find_then_expire(fn_id: str, sb_id: str) -> str | None:
            found = orig_find(fn_id, sb_id)
            if found == "snap-ephemeral":
                server.snapshots.pop("snap-ephemeral", None)
            return found

        monkeypatch.setattr(provider, "_find_latest_ready_snapshot", find_then_expire)
        try:
            acquired = provider.acquire("t-snap-race", user_id="u1")
            assert acquired == sid
            creates = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert [c.get("SnapshotId") for c in creates] == ["snap-ephemeral", "snap-base"]
        finally:
            provider.shutdown()

        # Operator-configured invalid base snapshot_id must fail closed.
        server_bad = _FakeVeFaaSServer()
        server_bad.validate_snapshot_on_create = True
        provider_bad, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "bad-base",
            server=server_bad,
            sandbox_overrides={"vefaas": {"snapshot_id": "snap-nonexistent"}},
        )
        try:
            with pytest.raises(VeFaaSSnapshotNotFoundError):
                provider_bad.acquire("t-bad-base", user_id="u1")
        finally:
            provider_bad.shutdown()

    def test_snapshot_failure_during_idle_reap_still_kills_sandbox(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_create_error = (500, "SnapshotQuotaExceeded", "quota reached")
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )
        try:
            sid = provider.acquire("t-snap-err", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            provider.release(sid)
            entry, _ = provider._warm_pool[sid]
            provider._warm_pool[sid] = (entry, time.monotonic() - 100.0)
            provider._reap_expired_warm(1.0)

            assert remote_id not in server.sandboxes
            assert provider._ownership.owner(sid) is None
            assert not provider._pending_destroys
        finally:
            provider.shutdown()

    def test_public_snapshot_helpers_and_dirty_rejection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating", "Ready"]
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)
        provider._snapshot_watch_interval = 0.01
        try:
            sid = provider.acquire("t-pub-snap", user_id="u1")
            snap_ready = provider.create_snapshot(sid, snapshot_type="full", retention_days=10, wait=True)
            assert snap_ready.is_ready
            assert snap_ready.snapshot_type == "full"
            assert snap_ready.retention_days == 10

            snap_async = provider.create_snapshot(sid, wait=False)
            assert snap_async.status == "Creating"

            listed = provider.list_snapshots(sid)
            assert {s.id for s in listed} == {snap_ready.id, snap_async.id}

            provider.delete_snapshot(snap_ready.id)
            assert [s.id for s in provider.list_snapshots(sid)] == [snap_async.id]

            # Dirty sandbox must be rejected for snapshots.
            provider._sandboxes[sid].sandbox.requires_container_recycle = True
            with pytest.raises(RuntimeError, match="corrupted"):
                provider.create_snapshot(sid)

            with pytest.raises(RuntimeError, match="not tracked"):
                provider.create_snapshot("unknown-sandbox")

            # Wait for the async snapshot watcher to observe Ready and clear the teardown fence.
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider._snapshotting_remote_ids
        finally:
            provider.shutdown()


class TestVeFaaSImagePrecache:
    def test_precache_images_fire_and_forget_wait_and_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.precache_status_sequence = ["Running", "Succeeded"]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"precache_images": ["cr.example.com/aio:v1"]}},
        )
        try:
            pending_ticket = provider.precache_images(wait=False)
            assert pending_ticket.ticket_id == "ticket-1"
            assert pending_ticket.status == "Pending"
            assert not any(action == "GetSandboxImagePrecacheTicket" for action, _, _ in server.requests)

            done_ticket = provider.precache_images(wait=True)
            assert done_ticket.is_succeeded
            assert any(action == "GetSandboxImagePrecacheTicket" for action, _, _ in server.requests)

            server.precache_status_sequence = ["Failed"]
            with pytest.raises(RuntimeError, match="failed"):
                provider.precache_images(["cr.example.com/aio:bad"], wait=True)
        finally:
            provider.shutdown()

    def test_precache_on_startup_runs_in_background_and_joins_on_shutdown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        submitted = threading.Event()
        orig_handler = server.handler

        def tracking_handler(req: httpx.Request) -> httpx.Response:
            resp = orig_handler(req)
            if req.url.params.get("Action") == "PrecacheSandboxImages":
                submitted.set()
            return resp

        server.handler = tracking_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={
                "vefaas": {
                    "precache_images": ["cr.example.com/aio:v1", "cr.example.com/aio:v2"],
                    "precache_on_startup": True,
                }
            },
        )
        try:
            assert submitted.wait(timeout=5)
            precache_reqs = [payload for action, payload, _ in server.requests if action == "PrecacheSandboxImages"]
            assert len(precache_reqs) == 1
            assert precache_reqs[0]["ImageUrls"] == ["cr.example.com/aio:v1", "cr.example.com/aio:v2"]
        finally:
            provider.shutdown()
        assert provider._precache_thread is not None
        assert not provider._precache_thread.is_alive()

    def test_reclaim_warm_pool_resumes_auto_paused_instance_instead_of_killing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: auto_pause=True -> server auto-pauses sandbox while in warm pool; next acquire resumes it.
        server = _FakeVeFaaSServer()
        server.resume_status_sequence = ["Resuming", "Running"]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "auto-pause",
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        persisted_files: dict[str, bytes] = {}

        class _PersistingAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_files

        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAio)
        # HTTP readiness fails while remote instance is Paused and succeeds once Running.
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid = provider.acquire("t-auto-paused", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            persisted_files["live-state"] = b"auto-paused-data"
            provider.release(sid)
            assert sid in provider._warm_pool

            # Simulate veFaaS auto-pausing the warm sandbox server-side.
            server.sandboxes[remote_id]["Status"] = "Paused"
            server.sandboxes[remote_id]["PausedAt"] = "2026-11-23T02:00:00Z"

            reacquired = provider.acquire("t-auto-paused", user_id="u1")
            assert reacquired == sid
            assert provider._sandboxes[sid].remote_sandbox_id == remote_id
            assert server.sandboxes[remote_id]["Status"] == "Running"
            assert persisted_files["live-state"] == b"auto-paused-data"
            assert not any(action == "KillSandbox" for action, _, _ in server.requests)
            assert sum(1 for action, _, _ in server.requests if action == "ResumeSandbox") == 1
            assert sum(1 for action, _, _ in server.requests if action == "CreateSandbox") == 1
        finally:
            provider.shutdown()

        # Case B: auto_pause=False -> sandbox paused externally; failed HTTP probe still hands off to resume.
        server_ext = _FakeVeFaaSServer()
        provider_ext, _, _ = _install_provider(monkeypatch, tmp_path / "ext-pause", server=server_ext)
        persisted_ext: dict[str, bytes] = {}

        class _PersistingAioExt(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_ext

        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioExt)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_ext.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_ext = provider_ext.acquire("t-ext-paused", user_id="u1")
            remote_ext = provider_ext._sandboxes[sid_ext].remote_sandbox_id
            provider_ext.release(sid_ext)
            server_ext.sandboxes[remote_ext]["Status"] = "Paused"

            assert provider_ext.acquire("t-ext-paused", user_id="u1") == sid_ext
            assert not any(action == "KillSandbox" for action, _, _ in server_ext.requests)
            assert sum(1 for action, _, _ in server_ext.requests if action == "ResumeSandbox") == 1
        finally:
            provider_ext.shutdown()

    def test_snapshot_retirement_renews_teardown_lease_and_aborts_kill_when_peer_adopts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: controlled clock advances past TTL during snapshot polling; teardown lease stays alive.
        now = [100.0]

        def fake_clock() -> float:
            return now[0]

        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating", "Creating", "Ready"]
        orig_handler = server.handler
        peer_take_attempts: list[bool] = []
        store = MemoryOwnershipStore(owner_id="worker-retire", ttl_seconds=10.0, time_source=fake_clock)
        peer_store = MemoryOwnershipStore(owner_id="worker-peer", ttl_seconds=10.0, time_source=fake_clock)
        # Share the underlying lease table across worker-retire and worker-peer.
        peer_store._leases = store._leases
        peer_store._lock = store._lock

        sid_holder: list[str] = []

        def advancing_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                # Advance 6s per poll (18s total > 10s TTL); without lease refresh, peer take() would succeed.
                now[0] += 6.0
                if sid_holder:
                    peer_take_attempts.append(peer_store.take(sid_holder[0]))
            return orig_handler(req)

        server.handler = advancing_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "renew",
            server=server,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )
        provider._ownership = store
        try:
            sid = provider.acquire("t-long-snap", user_id="u1")
            sid_holder.append(sid)
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            provider.release(sid)
            entry, _ = provider._warm_pool[sid]
            provider._warm_pool[sid] = (entry, time.monotonic() - 100.0)
            provider._reap_expired_warm(1.0)

            assert len(peer_take_attempts) >= 2
            assert all(taken is False for taken in peer_take_attempts)
            assert remote_id not in server.sandboxes
            assert store.owner(sid) is None
        finally:
            provider.shutdown()

        # Case B: store loses our teardown lease and a peer takes ownership mid-snapshot -> abort KillSandbox!
        server_b = _FakeVeFaaSServer()
        server_b.snapshot_status_sequence = ["Creating", "Ready"]
        orig_handler_b = server_b.handler
        store_b = MemoryOwnershipStore(owner_id="worker-retire-b", ttl_seconds=60.0)
        peer_b = MemoryOwnershipStore(owner_id="worker-peer-b", ttl_seconds=60.0)
        peer_b._leases = store_b._leases
        peer_b._lock = store_b._lock
        sid_b_holder: list[str] = []
        stole_once = {"done": False}

        def peer_steals_mid_snapshot(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot" and not stole_once["done"] and sid_b_holder:
                stole_once["done"] = True
                # Simulate backend flush + peer adoption while snapshot was in flight.
                store_b._leases.clear()
                assert peer_b.take(sid_b_holder[0]) is True
            return orig_handler_b(req)

        server_b.handler = peer_steals_mid_snapshot  # type: ignore[method-assign]
        provider_b, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "lost",
            server=server_b,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )
        provider_b._ownership = store_b
        try:
            sid_b = provider_b.acquire("t-lost-snap", user_id="u1")
            sid_b_holder.append(sid_b)
            remote_b = provider_b._sandboxes[sid_b].remote_sandbox_id
            provider_b.release(sid_b)
            entry_b, _ = provider_b._warm_pool[sid_b]
            provider_b._warm_pool[sid_b] = (entry_b, time.monotonic() - 100.0)
            provider_b._reap_expired_warm(1.0)

            assert stole_once["done"] is True
            # Must NOT kill the peer's running sandbox or clear the peer's lease!
            assert remote_b in server_b.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server_b.requests)
            assert store_b.owner(sid_b) == "worker-peer-b"
            assert not provider_b._pending_destroys
        finally:
            provider_b.shutdown()

    @pytest.mark.parametrize("from_warm_pool", [False, True])
    def test_manual_snapshot_defers_shutdown_until_snapshot_settles(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        from_warm_pool: bool,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating", "Ready"]
        orig_handler = server.handler
        creating_seen = threading.Event()
        allow_ready = threading.Event()

        def gated_handler(req: httpx.Request) -> httpx.Response:
            resp = orig_handler(req)
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                body = resp.json()["Result"]["Snapshot"]
                if body["Status"] == "Creating":
                    creating_seen.set()
                    assert allow_ready.wait(timeout=5)
            return resp

        server.handler = gated_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)
        try:
            sid = provider.acquire("t-manual-snap", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            remote_aio = provider._sandboxes[sid].sandbox
            if from_warm_pool:
                provider.release(sid)
                assert sid in provider._warm_pool

            with ThreadPoolExecutor(max_workers=1) as pool:
                snap_future = pool.submit(provider.create_snapshot, sid, wait=True)
                try:
                    assert creating_seen.wait(timeout=5)
                    # Concurrent shutdown must stay retryable and leave the snapshot source alive!
                    with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="snapshot"):
                        provider.shutdown()
                    assert not remote_aio.closed
                    assert remote_id in server.sandboxes
                    assert not any(action == "KillSandbox" for action, _, _ in server.requests)
                    assert provider._client is not None and not provider._client._closed
                finally:
                    allow_ready.set()
                snap = snap_future.result(timeout=5)

            assert snap.is_ready
            assert snap.sandbox_id == remote_id
            # Once snapshot settles, retrying shutdown tears down the source sandbox cleanly.
            provider.shutdown()
            assert remote_id not in server.sandboxes
            assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1
        finally:
            allow_ready.set()
            provider.shutdown()

    @pytest.mark.parametrize("from_warm_pool", [False, True])
    def test_sync_manual_snapshot_keeps_ownership_lease_renewed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        from_warm_pool: bool,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating", "Ready"]
        orig_handler = server.handler
        creating_seen = threading.Event()
        allow_ready = threading.Event()

        def gated_handler(req: httpx.Request) -> httpx.Response:
            resp = orig_handler(req)
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                body = resp.json()["Result"]["Snapshot"]
                if body["Status"] == "Creating":
                    creating_seen.set()
                    assert allow_ready.wait(timeout=5)
            return resp

        server.handler = gated_handler  # type: ignore[method-assign]
        clock = {"now": 100.0}
        owner_store = MemoryOwnershipStore(owner_id="worker-snap-owner", ttl_seconds=10.0, time_source=lambda: clock["now"])
        peer_store = MemoryOwnershipStore(owner_id="worker-snap-peer", ttl_seconds=10.0, time_source=lambda: clock["now"])
        peer_store._leases = owner_store._leases
        peer_store._lock = owner_store._lock

        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)
        provider._ownership = owner_store
        try:
            sid = provider.acquire("t-sync-snap-renew", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            if from_warm_pool:
                provider.release(sid)
                assert sid in provider._warm_pool

            with ThreadPoolExecutor(max_workers=1) as pool:
                snap_future = pool.submit(provider.create_snapshot, sid, wait=True)
                try:
                    assert creating_seen.wait(timeout=5)
                    # Synchronous wait must NOT suppress lease renewal via _acquire_inflight.
                    assert sid not in provider._acquire_inflight
                    assert remote_id in provider._snapshotting_remote_ids

                    # Renew before original TTL (110.0) expires -> extends lease to 116.0.
                    clock["now"] = 106.0
                    provider._renew_leases_once()

                    # Past original TTL (112.0 > 110.0): owner lease is still live and blocks peer teardown.
                    clock["now"] = 112.0
                    assert owner_store.owner(sid) == "worker-snap-owner"
                    assert peer_store.claim(sid, for_destroy=True) is False
                finally:
                    allow_ready.set()
                snap = snap_future.result(timeout=5)

            assert snap.is_ready
            provider.shutdown()
            assert remote_id not in server.sandboxes
            assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1
        finally:
            allow_ready.set()
            provider.shutdown()

    @pytest.mark.parametrize("from_warm_pool", [False, True])
    def test_async_snapshot_retains_fence_across_shutdown_and_warm_reap_until_settled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        from_warm_pool: bool,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating"]
        orig_handler = server.handler
        transient_503_seen = threading.Event()
        creating_seen = threading.Event()
        allow_ready = threading.Event()
        describe_calls = {"count": 0}

        def gated_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                describe_calls["count"] += 1
                if describe_calls["count"] == 1:
                    transient_503_seen.set()
                    return httpx.Response(
                        503,
                        json={"ResponseMetadata": {"RequestId": "req-snap-503", "Error": {"Code": "ServiceUnavailable", "Message": "transient 503"}}},
                    )
                if not allow_ready.is_set():
                    creating_seen.set()
                    return orig_handler(req)
                payload = json.loads(req.content.decode("utf-8"))
                snap_rec = server.snapshots.get(payload["SnapshotId"])
                if snap_rec is not None:
                    snap_rec["Status"] = "Ready"
                    snap_rec["_status_queue"] = ["Ready"]
            return orig_handler(req)

        server.handler = gated_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"idle_timeout": 10},
        )
        provider._snapshot_watch_interval = 0.01
        try:
            sid = provider.acquire("t-async-snap", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            remote_aio = provider._sandboxes[sid].sandbox
            if from_warm_pool:
                provider.release(sid)
                assert sid in provider._warm_pool

            snap = provider.create_snapshot(sid, wait=False)
            assert snap.status == "Creating"
            assert snap.sandbox_id == remote_id
            assert not provider._acquire_inflight
            assert transient_503_seen.wait(timeout=5)
            assert creating_seen.wait(timeout=5)
            assert remote_id in provider._snapshotting_remote_ids

            if from_warm_pool:
                # Warm-pool idle reaping and replica eviction must skip the fenced source.
                provider._warm_pool[sid] = (provider._warm_pool[sid][0], time.monotonic() - 120.0)
                provider._reap_expired_warm(idle_timeout=10)
                assert provider._evict_oldest_warm() is None
                assert sid in provider._warm_pool
                assert remote_id in server.sandboxes
                assert not any(action == "KillSandbox" for action, _, _ in server.requests)

            # Shutdown must defer teardown and keep the client open until the watcher sees settlement.
            with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="snapshot"):
                provider.shutdown()
            assert not remote_aio.closed
            assert remote_id in server.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server.requests)
            assert provider._client is not None and not provider._client._closed

            # Let the snapshot settle to Ready; watcher releases the fence and shutdown succeeds.
            allow_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider._snapshotting_remote_ids

            provider.shutdown()
            assert remote_id not in server.sandboxes
            assert not provider._snapshot_watchers
            assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1
        finally:
            allow_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            provider.shutdown()

    def test_timed_out_sync_snapshot_retains_fence_until_watcher_confirms_settlement(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating"]
        orig_handler = server.handler
        allow_terminal = threading.Event()
        watcher_polled_creating = threading.Event()
        sync_finished = threading.Event()

        def gated_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                if allow_terminal.is_set():
                    payload = json.loads(req.content.decode("utf-8"))
                    snap_rec = server.snapshots.get(payload["SnapshotId"])
                    if snap_rec is not None:
                        snap_rec["Status"] = "Failed"
                        snap_rec["_status_queue"] = ["Failed"]
                elif sync_finished.is_set():
                    watcher_polled_creating.set()
            return orig_handler(req)

        server.handler = gated_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)
        provider._snapshot_watch_interval = 0.01
        try:
            sid = provider.acquire("t-timeout-snap", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            remote_aio = provider._sandboxes[sid].sandbox

            # Synchronous wait times out while remote snapshot is still Creating.
            with pytest.raises(TimeoutError, match="Timed out waiting for veFaaS snapshot"):
                provider.create_snapshot(sid, wait=True, timeout=0.01)
            sync_finished.set()

            assert not provider._acquire_inflight
            assert remote_id in provider._snapshotting_remote_ids
            assert watcher_polled_creating.wait(timeout=5)

            # Shutdown must remain deferred while the watcher continues polling.
            with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="snapshot"):
                provider.shutdown()
            assert not remote_aio.closed
            assert remote_id in server.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server.requests)

            # Once control plane reports terminal failure, watcher clears the fence and shutdown succeeds.
            allow_terminal.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider._snapshotting_remote_ids

            provider.shutdown()
            assert remote_id not in server.sandboxes
            assert not provider._snapshot_watchers
            assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1
        finally:
            allow_terminal.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            provider.shutdown()

    @pytest.mark.parametrize("auto_pause", [True, False])
    def test_paused_warm_reacquire_with_list_sandboxes_503_retains_tracking_and_resumes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        auto_pause: bool,
    ) -> None:
        server = _FakeVeFaaSServer()
        orig_handler = server.handler
        list_outage = {"active": False}

        def list_503_handler(req: httpx.Request) -> httpx.Response:
            if list_outage["active"] and req.url.params.get("Action") == "ListSandboxes":
                return httpx.Response(
                    503,
                    json={"ResponseMetadata": {"RequestId": "req-list-503", "Error": {"Code": "ServiceUnavailable", "Message": "transient 503"}}},
                )
            return orig_handler(req)

        server.handler = list_503_handler  # type: ignore[method-assign]
        persisted_files: dict[str, bytes] = {}

        class _PersistingAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_files

        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": auto_pause}},
        )
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAio)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid = provider.acquire("t-list-503", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            persisted_files["state"] = b"kept"
            provider.release(sid)
            assert sid in provider._warm_pool

            server.sandboxes[remote_id]["Status"] = "Paused"
            list_calls_before = sum(1 for action, _, _ in server.requests if action == "ListSandboxes")
            list_outage["active"] = True

            # Known paused warm sandbox resumes directly without depending on ListSandboxes.
            assert provider.acquire("t-list-503", user_id="u1") == sid
            assert provider._sandboxes[sid].remote_sandbox_id == remote_id
            assert server.sandboxes[remote_id]["Status"] == "Running"
            assert persisted_files["state"] == b"kept"
            assert sum(1 for action, _, _ in server.requests if action == "CreateSandbox") == 1
            assert sum(1 for action, _, _ in server.requests if action == "ResumeSandbox") == 1
            assert sum(1 for action, _, _ in server.requests if action == "ListSandboxes") == list_calls_before
        finally:
            list_outage["active"] = False
            provider.shutdown()

        assert remote_id not in server.sandboxes
        assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1

    @pytest.mark.parametrize("failing_action", ["DescribeSandbox", "ResumeSandbox"])
    @pytest.mark.parametrize("auto_pause", [True, False])
    def test_paused_warm_reacquire_transient_503_keeps_cleanup_record_for_shutdown_and_retry(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        failing_action: str,
        auto_pause: bool,
    ) -> None:
        # Subcase A: failed acquire leaves warm entry tracked so shutdown kills it after recovery.
        server = _FakeVeFaaSServer()
        persisted_a: dict[str, bytes] = {}

        class _PersistingAioA(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_a

        provider, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "shutdown-path",
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": auto_pause}},
        )
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioA)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid = provider.acquire("t-503-shutdown", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            provider.release(sid)
            server.sandboxes[remote_id]["Status"] = "Paused"

            if failing_action == "DescribeSandbox":
                server.describe_error = (503, "ServiceUnavailable", "transient describe 503")
            else:
                server.resume_error = (503, "ServiceUnavailable", "transient resume 503")

            with pytest.raises(VeFaaSApiError):
                provider.acquire("t-503-shutdown", user_id="u1")

            # Warm tracking record must remain intact after failed acquire.
            assert sid in provider._warm_pool
            assert provider._warm_pool[sid][0].remote_sandbox_id == remote_id
            assert remote_id in server.sandboxes

            # Once the service recovers, shutdown MUST send KillSandbox and delete the paused instance.
            server.describe_error = None
            server.resume_error = None
            provider.shutdown()
            assert remote_id not in server.sandboxes
            assert sum(1 for action, _, _ in server.requests if action == "KillSandbox") == 1
        finally:
            server.describe_error = None
            server.resume_error = None
            provider.shutdown()

        # Subcase B: retry acquire after recovery resumes the SAME paused sandbox without duplicates.
        server_b = _FakeVeFaaSServer()
        persisted_b: dict[str, bytes] = {}

        class _PersistingAioB(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_b

        provider_b, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "retry-path",
            server=server_b,
            sandbox_overrides={"vefaas": {"auto_pause": auto_pause}},
        )
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioB)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_b.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_b = provider_b.acquire("t-503-retry", user_id="u1")
            remote_b = provider_b._sandboxes[sid_b].remote_sandbox_id
            persisted_b["live"] = b"retry-preserved"
            provider_b.release(sid_b)
            server_b.sandboxes[remote_b]["Status"] = "Paused"

            if failing_action == "DescribeSandbox":
                server_b.describe_error = (503, "ServiceUnavailable", "transient describe 503")
            else:
                server_b.resume_error = (503, "ServiceUnavailable", "transient resume 503")

            with pytest.raises(VeFaaSApiError):
                provider_b.acquire("t-503-retry", user_id="u1")
            assert sid_b in provider_b._warm_pool

            server_b.describe_error = None
            server_b.resume_error = None
            assert provider_b.acquire("t-503-retry", user_id="u1") == sid_b
            assert provider_b._sandboxes[sid_b].remote_sandbox_id == remote_b
            assert server_b.sandboxes[remote_b]["Status"] == "Running"
            assert persisted_b["live"] == b"retry-preserved"
            assert sum(1 for action, _, _ in server_b.requests if action == "CreateSandbox") == 1
            assert not any(action == "KillSandbox" for action, _, _ in server_b.requests)
        finally:
            server_b.describe_error = None
            server_b.resume_error = None
            provider_b.shutdown()

    def test_paused_warm_reacquire_handles_absent_unadoptable_and_peer_handoff(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Paused warm sandbox disappears (SandboxNotFound on ResumeSandbox) -> pops warm & creates replacement.
        server_a = _FakeVeFaaSServer()
        orig_handler_a = server_a.handler

        def expire_on_resume(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "ResumeSandbox":
                payload = json.loads(req.content.decode("utf-8"))
                server_a.sandboxes.pop(payload["SandboxId"], None)
            return orig_handler_a(req)

        server_a.handler = expire_on_resume  # type: ignore[method-assign]
        provider_a, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "absent",
            server=server_a,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_a.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_a = provider_a.acquire("t-warm-absent", user_id="u1")
            old_remote = provider_a._sandboxes[sid_a].remote_sandbox_id
            provider_a.release(sid_a)
            server_a.sandboxes[old_remote]["Status"] = "Paused"

            assert provider_a.acquire("t-warm-absent", user_id="u1") == sid_a
            new_remote = provider_a._sandboxes[sid_a].remote_sandbox_id
            assert new_remote != old_remote
            assert old_remote not in server_a.sandboxes
            assert new_remote in server_a.sandboxes
            assert sum(1 for action, _, _ in server_a.requests if action == "CreateSandbox") == 2
        finally:
            provider_a.shutdown()

        # Case B: Resumed warm sandbox has mismatched/invalid init marker -> destroyed via _pending_destroys, never leaked.
        server_b = _FakeVeFaaSServer()
        persisted_b: dict[str, bytes] = {}

        class _CorruptibleAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_b

        provider_b, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "invalid-marker",
            server=server_b,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        monkeypatch.setattr(provider_mod, "AioSandbox", _CorruptibleAio)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_b.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_b = provider_b.acquire("t-warm-invalid", user_id="u1")
            corrupted_remote = provider_b._sandboxes[sid_b].remote_sandbox_id
            provider_b.release(sid_b)
            server_b.sandboxes[corrupted_remote]["Status"] = "Paused"
            # Corrupt init marker on the paused instance; fresh replacement receives its own marker.
            persisted_b[provider_mod._INIT_MARKER_PATH] = b"wrong-sandbox-id\n"

            class _FreshMarkerAio(_FakeAioSandbox):
                def __init__(self, **kwargs: Any) -> None:
                    super().__init__(**kwargs)
                    remote_hdr = self.request_headers.get(provider_mod.INSTANCE_ROUTING_HEADER)
                    if remote_hdr == corrupted_remote:
                        self.uploaded_files = persisted_b

            monkeypatch.setattr(provider_mod, "AioSandbox", _FreshMarkerAio)
            assert provider_b.acquire("t-warm-invalid", user_id="u1") == sid_b
            replacement_remote = provider_b._sandboxes[sid_b].remote_sandbox_id
            assert replacement_remote != corrupted_remote
            assert corrupted_remote not in server_b.sandboxes
            assert replacement_remote in server_b.sandboxes
            kill_targets = [payload["SandboxId"] for action, payload, _ in server_b.requests if action == "KillSandbox"]
            assert corrupted_remote in kill_targets
        finally:
            provider_b.shutdown()

        # Case C: After transient ResumeSandbox 503, a peer takes ownership -> original provider's shutdown must NOT kill it.
        server_c = _FakeVeFaaSServer()
        store_owner = MemoryOwnershipStore(owner_id="worker-a", ttl_seconds=60.0)
        store_peer = MemoryOwnershipStore(owner_id="worker-b", ttl_seconds=60.0)
        store_peer._leases = store_owner._leases
        store_peer._lock = store_owner._lock
        # Simulate a shared store (e.g. Redis) where worker-a closing its connection does not clear worker-b's leases.
        monkeypatch.setattr(store_owner, "close", lambda: None)

        provider_c, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "peer-takeover",
            server=server_c,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        provider_c._ownership = store_owner
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_c.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_c = provider_c.acquire("t-peer-handoff", user_id="u1")
            remote_c = provider_c._sandboxes[sid_c].remote_sandbox_id
            provider_c.release(sid_c)
            server_c.sandboxes[remote_c]["Status"] = "Paused"
            server_c.resume_error = (503, "ServiceUnavailable", "transient resume 503")

            with pytest.raises(VeFaaSApiError):
                provider_c.acquire("t-peer-handoff", user_id="u1")
            assert sid_c in provider_c._warm_pool

            # Service recovers and peer claims ownership of the sandbox.
            server_c.resume_error = None
            assert store_peer.claim(sid_c) is True

            provider_c.shutdown()
            assert remote_c in server_c.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server_c.requests)
            assert store_owner.owner(sid_c) == "worker-b"
        finally:
            server_c.resume_error = None
            provider_c.shutdown()

        # Case D: Concurrent shutdown while resuming a paused warm sandbox rolls back cleanly.
        server_d = _FakeVeFaaSServer()
        orig_handler_d = server_d.handler
        resume_entered = threading.Event()
        allow_resume = threading.Event()

        def gated_resume_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "ResumeSandbox":
                resume_entered.set()
                assert allow_resume.wait(timeout=5)
            return orig_handler_d(req)

        server_d.handler = gated_resume_handler  # type: ignore[method-assign]
        persisted_d: dict[str, bytes] = {}

        class _PersistingAioD(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_d

        provider_d, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "shutdown-race",
            server=server_d,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioD)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server_d.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid_d = provider_d.acquire("t-warm-shutdown-race", user_id="u1")
            remote_d = provider_d._sandboxes[sid_d].remote_sandbox_id
            provider_d.release(sid_d)
            server_d.sandboxes[remote_d]["Status"] = "Paused"

            with ThreadPoolExecutor(max_workers=1) as pool:
                reacquire_future = pool.submit(provider_d.acquire, "t-warm-shutdown-race", user_id="u1")
                try:
                    assert resume_entered.wait(timeout=5)
                    # Concurrent shutdown sees the in-flight acquire, kills the tracked warm sandbox,
                    # and reports incomplete until the acquire thread exits.
                    with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="acquire"):
                        provider_d.shutdown()
                finally:
                    allow_resume.set()
                with pytest.raises(RuntimeError, match="shut down"):
                    reacquire_future.result(timeout=5)

            # Retrying shutdown once the acquire thread exits succeeds with zero leaked remote sandbox.
            provider_d.shutdown()
            assert remote_d not in server_d.sandboxes
            assert not provider_d._sandboxes
            assert not provider_d._warm_pool
            assert not provider_d._pending_destroys
            assert sum(1 for action, _, _ in server_d.requests if action == "CreateSandbox") == 1
            assert any(action == "KillSandbox" for action, _, _ in server_d.requests)
        finally:
            allow_resume.set()
            provider_d.shutdown()

    def test_auto_paused_warm_sandbox_hands_off_ownership_to_peer_and_rejects_teardown(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Worker A retains an auto-paused sandbox in its warm pool and keeps renewing its normal
        # `own:` lease. Worker B receives the next turn, takes ownership, resumes the sandbox, and Worker A
        # forgets it on renewal without killing it.
        server = _FakeVeFaaSServer()
        store_a = MemoryOwnershipStore(owner_id="worker-a", ttl_seconds=60.0)
        store_b = MemoryOwnershipStore(owner_id="worker-b", ttl_seconds=60.0)
        store_b._leases = store_a._leases
        store_b._lock = store_a._lock
        monkeypatch.setattr(store_a, "close", lambda: None)
        monkeypatch.setattr(store_b, "close", lambda: None)

        persisted_files: dict[str, bytes] = {}

        class _PersistingAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_files

        worker_a, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "worker-a",
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        worker_b, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "worker-b",
            server=server,
            sandbox_overrides={"vefaas": {"auto_pause": True}},
        )
        worker_a._ownership = store_a
        worker_b._ownership = store_b
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAio)
        monkeypatch.setattr(
            provider_mod,
            "wait_for_sandbox_ready",
            lambda _url, timeout=30, headers=None: bool(headers and server.sandboxes.get(headers.get(provider_mod.INSTANCE_ROUTING_HEADER, ""), {}).get("Status") == "Running"),
        )
        try:
            sid = worker_a.acquire("t-auto-pause-handoff", user_id="u1")
            remote_id = worker_a._sandboxes[sid].remote_sandbox_id
            persisted_files["state"] = b"kept-across-workers"
            worker_a.release(sid)
            assert sid in worker_a._warm_pool
            # Worker A keeps renewing its normal lease while veFaaS auto-pauses the remote sandbox.
            server.sandboxes[remote_id]["Status"] = "Paused"
            worker_a._renew_leases_once()
            assert store_a.owner(sid) == "worker-a"

            # Next turn lands on Worker B: must hand off normal ownership and resume without timing out.
            adopted_sid = worker_b.acquire("t-auto-pause-handoff", user_id="u1")
            assert adopted_sid == sid
            assert worker_b._sandboxes[sid].remote_sandbox_id == remote_id
            assert store_b.owner(sid) == "worker-b"
            assert sum(1 for action, _, _ in server.requests if action == "CreateSandbox") == 1
            assert sum(1 for action, _, _ in server.requests if action == "ResumeSandbox") == 1
            assert persisted_files["state"] == b"kept-across-workers"

            # Worker A observes LOST on its next renewal and forgets the sandbox without killing it.
            worker_a._renew_leases_once()
            assert sid not in worker_a._warm_pool
            worker_a.shutdown()
            assert remote_id in server.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server.requests)
        finally:
            worker_a.shutdown()
            worker_b.shutdown()

        # Case B: Destructive teardown lease (`del:`) held by Worker A MUST still reject Worker B's resume.
        server_del = _FakeVeFaaSServer()
        sid_del = derive_sandbox_scope_token(user_id="u1", thread_id="t-peer-del-paused")
        server_del.sandboxes["vefaas-del-paused"] = {
            "Id": "vefaas-del-paused",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_del,
            },
        }
        store_del_a = MemoryOwnershipStore(owner_id="worker-del-a", ttl_seconds=60.0)
        store_del_b = MemoryOwnershipStore(owner_id="worker-del-b", ttl_seconds=60.0)
        store_del_b._leases = store_del_a._leases
        store_del_b._lock = store_del_a._lock
        assert store_del_a.claim(sid_del, for_destroy=True) is True

        worker_del_b, _, _ = _install_provider(monkeypatch, tmp_path / "worker-del-b", server=server_del)
        worker_del_b._ownership = store_del_b
        try:
            with pytest.raises(provider_mod._PeerTeardownError, match="destroyed by a peer"):
                worker_del_b.acquire("t-peer-del-paused", user_id="u1")
            assert not any(action == "ResumeSandbox" for action, _, _ in server_del.requests)
            assert not any(action == "CreateSandbox" for action, _, _ in server_del.requests)
            assert store_del_a.owner(sid_del) == "worker-del-a"
        finally:
            worker_del_b.shutdown()

    def test_resume_refreshes_ownership_lease_across_long_running_and_http_readiness_waits(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Resume status polling + HTTP readiness together exceed the ownership TTL.
        # Poll-tick refresh and the resume lease heartbeat keep ownership alive so a peer cannot
        # obtain a destructive claim and kill the sandbox mid-resume.
        server = _FakeVeFaaSServer()
        sid = derive_sandbox_scope_token(user_id="u1", thread_id="t-resume-long-ttl")
        server.sandboxes["vefaas-long-resume"] = {
            "Id": "vefaas-long-resume",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid,
            },
        }
        server.resume_status_sequence = ["Resuming", "Resuming", "Running"]
        clock = {"now": 100.0}
        owner_store = MemoryOwnershipStore(owner_id="worker-resumer", ttl_seconds=10.0, time_source=lambda: clock["now"])
        peer_store = MemoryOwnershipStore(owner_id="worker-peer", ttl_seconds=10.0, time_source=lambda: clock["now"])
        peer_store._leases = owner_store._leases
        peer_store._lock = owner_store._lock

        orig_handler = server.handler

        def advancing_handler(req: httpx.Request) -> httpx.Response:
            resp = orig_handler(req)
            if req.url.params.get("Action") == "DescribeSandbox":
                body = resp.json().get("Result", {})
                if body.get("Status") == "Resuming":
                    # Advance clock by 6s per poll (12s total > 10s TTL) to verify poll-tick renewal.
                    clock["now"] += 6.0
            return resp

        server.handler = advancing_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(monkeypatch, tmp_path / "long-resume", server=server)
        provider._ownership = owner_store
        provider._ownership_config = provider._ownership_config.model_copy(update={"renewal_interval_seconds": 0.01})

        class _PreInitAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{sid}\n".encode()

        monkeypatch.setattr(provider_mod, "AioSandbox", _PreInitAio)

        readiness_peer_claims: list[bool] = []
        heartbeat_renewed = threading.Event()
        orig_renew = owner_store.renew

        def tracking_renew(target_sid: str) -> RenewOutcome:
            outcome = orig_renew(target_sid)
            heartbeat_renewed.set()
            return outcome

        monkeypatch.setattr(owner_store, "renew", tracking_renew)

        def slow_ready(_url: str, timeout: int = 30, headers: Any = None) -> bool:
            del timeout, headers
            # Advance past TTL in two steps during HTTP readiness while the background heartbeat refreshes.
            for _ in range(2):
                heartbeat_renewed.clear()
                clock["now"] += 6.0
                assert heartbeat_renewed.wait(timeout=5)
                readiness_peer_claims.append(peer_store.claim(sid, for_destroy=True))
            return True

        monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", slow_ready)
        try:
            acquired = provider.acquire("t-resume-long-ttl", user_id="u1")
            assert acquired == sid
            assert provider._sandboxes[sid].remote_sandbox_id == "vefaas-long-resume"
            assert clock["now"] >= 124.0
            assert readiness_peer_claims == [False, False]
            assert owner_store.owner(sid) == "worker-resumer"
        finally:
            provider.shutdown()

        # Case B: If ownership is lost to a peer's destructive claim before HTTP readiness completes,
        # strict verification refuses adoption with ownership_claimed=True and raises _PeerTeardownError.
        server_lost = _FakeVeFaaSServer()
        sid_lost = derive_sandbox_scope_token(user_id="u1", thread_id="t-resume-lost-lease")
        server_lost.sandboxes["vefaas-lost-resume"] = {
            "Id": "vefaas-lost-resume",
            "FunctionId": "fn-demo-app",
            "Status": "Paused",
            "Pending": False,
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_lost,
            },
        }
        clock_b = {"now": 200.0}
        owner_b = MemoryOwnershipStore(owner_id="worker-resumer-b", ttl_seconds=10.0, time_source=lambda: clock_b["now"])
        peer_b = MemoryOwnershipStore(owner_id="worker-destroyer-b", ttl_seconds=60.0, time_source=lambda: clock_b["now"])
        peer_b._leases = owner_b._leases
        peer_b._lock = owner_b._lock

        provider_b, _, _ = _install_provider(monkeypatch, tmp_path / "lost-resume", server=server_lost)
        provider_b._ownership = owner_b
        provider_b._ownership_config = provider_b._ownership_config.model_copy(update={"renewal_interval_seconds": 60.0})

        class _PreInitAioB(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{sid_lost}\n".encode()

        monkeypatch.setattr(provider_mod, "AioSandbox", _PreInitAioB)

        def steal_during_ready(_url: str, timeout: int = 30, headers: Any = None) -> bool:
            del timeout, headers
            # Simulate worker stall past TTL + peer obtaining a destructive teardown lease.
            clock_b["now"] += 15.0
            assert peer_b.claim(sid_lost, for_destroy=True) is True
            return True

        monkeypatch.setattr(provider_mod, "wait_for_sandbox_ready", steal_during_ready)
        try:
            with pytest.raises(provider_mod._PeerTeardownError, match="destroyed by a peer|Lost ownership"):
                provider_b.acquire("t-resume-lost-lease", user_id="u1")
            assert sid_lost not in provider_b._sandboxes
            assert peer_b.owner(sid_lost) == "worker-destroyer-b"
        finally:
            provider_b.shutdown()

    def test_manual_snapshot_rejects_peer_owned_handle_and_fences_peer_teardown_across_workers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Stale local handle after peer takeover must be rejected before CreateSandboxSnapshot.
        server_a = _FakeVeFaaSServer()
        store_a1 = MemoryOwnershipStore(owner_id="worker-snap-a1", ttl_seconds=60.0)
        store_a2 = MemoryOwnershipStore(owner_id="worker-snap-a2", ttl_seconds=60.0)
        store_a2._leases = store_a1._leases
        store_a2._lock = store_a1._lock
        monkeypatch.setattr(store_a1, "close", lambda: None)
        monkeypatch.setattr(store_a2, "close", lambda: None)

        persisted_a: dict[str, bytes] = {}

        class _PersistingAioA(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_a

        worker_a1, _, _ = _install_provider(monkeypatch, tmp_path / "stale-a1", server=server_a)
        worker_a2, _, _ = _install_provider(monkeypatch, tmp_path / "stale-a2", server=server_a)
        worker_a1._ownership = store_a1
        worker_a2._ownership = store_a2
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioA)
        try:
            sid_a = worker_a1.acquire("t-stale-snap", user_id="u1")
            remote_a = worker_a1._sandboxes[sid_a].remote_sandbox_id
            worker_a1.release(sid_a)
            assert sid_a in worker_a1._warm_pool

            # Worker 2 takes over ownership while Worker 1 still holds its stale warm handle.
            assert worker_a2.acquire("t-stale-snap", user_id="u1") == sid_a
            assert store_a2.owner(sid_a) == "worker-snap-a2"
            assert sid_a in worker_a1._warm_pool

            with pytest.raises(RuntimeError, match="owned by a peer"):
                worker_a1.create_snapshot(sid_a, wait=True)
            assert not any(action == "CreateSandboxSnapshot" for action, _, _ in server_a.requests)
            assert store_a1.owner(provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_a)) is None
        finally:
            worker_a1.shutdown()
            worker_a2.shutdown()

        # Case B: Async snapshot started by Worker 1 reserves cross-worker fence refreshed past TTL;
        # even if Worker 2 subsequently takes `own:` on sandbox_id, Worker 2's warm reap/eviction and
        # shutdown MUST defer until Worker 1's snapshot settles and releases the cross-worker fence.
        server_b = _FakeVeFaaSServer()
        server_b.snapshot_status_sequence = ["Creating"]
        orig_handler_b = server_b.handler
        creating_seen = threading.Event()
        allow_ready = threading.Event()
        clock_b = {"now": 100.0}

        def gated_handler_b(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                if allow_ready.is_set():
                    payload = json.loads(req.content.decode("utf-8"))
                    snap_rec = server_b.snapshots.get(payload["SnapshotId"])
                    if snap_rec is not None:
                        snap_rec["Status"] = "Ready"
                        snap_rec["_status_queue"] = ["Ready"]
                else:
                    creating_seen.set()
            return orig_handler_b(req)

        server_b.handler = gated_handler_b  # type: ignore[method-assign]
        store_b1 = MemoryOwnershipStore(owner_id="worker-snap-b1", ttl_seconds=10.0, time_source=lambda: clock_b["now"])
        store_b2 = MemoryOwnershipStore(owner_id="worker-snap-b2", ttl_seconds=60.0, time_source=lambda: clock_b["now"])
        store_b2._leases = store_b1._leases
        store_b2._lock = store_b1._lock
        monkeypatch.setattr(store_b1, "close", lambda: None)
        monkeypatch.setattr(store_b2, "close", lambda: None)

        persisted_b: dict[str, bytes] = {}

        class _PersistingAioB(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                self.uploaded_files = persisted_b

        worker_b1, _, _ = _install_provider(monkeypatch, tmp_path / "fence-b1", server=server_b)
        worker_b2, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "fence-b2",
            server=server_b,
            sandbox_overrides={"idle_timeout": 10, "vefaas": {"pause_on_idle": True}},
        )
        worker_b1._ownership = store_b1
        worker_b2._ownership = store_b2
        worker_b1._snapshot_watch_interval = 0.01
        monkeypatch.setattr(provider_mod, "AioSandbox", _PersistingAioB)
        try:
            sid_b = worker_b1.acquire("t-peer-snap-fence", user_id="u1")
            remote_b = worker_b1._sandboxes[sid_b].remote_sandbox_id
            fence_key_b = provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_b)

            snap_b = worker_b1.create_snapshot(sid_b, wait=False)
            assert snap_b.status == "Creating"
            assert creating_seen.wait(timeout=5)
            assert store_b1.owner(fence_key_b) == "worker-snap-b1"

            # Advance clock past initial 10s TTL in two 6s steps; watcher refreshes fence_key_b.
            wait_evt = threading.Event()
            for _ in range(2):
                clock_b["now"] += 6.0
                creating_seen.clear()
                assert creating_seen.wait(timeout=5)
            assert store_b1.owner(fence_key_b) == "worker-snap-b1"

            # Worker 2 takes over sandbox_id, releases it to warm pool, and tries idle reap + eviction + shutdown.
            assert worker_b2.acquire("t-peer-snap-fence", user_id="u1") == sid_b
            assert store_b2.owner(sid_b) == "worker-snap-b2"
            worker_b2.release(sid_b)
            assert sid_b in worker_b2._warm_pool
            worker_b2._warm_pool[sid_b] = (worker_b2._warm_pool[sid_b][0], time.monotonic() - 120.0)
            worker_b2._reap_expired_warm(idle_timeout=10)
            assert worker_b2._evict_oldest_warm() is None
            assert sid_b in worker_b2._warm_pool
            assert not any(action in {"KillSandbox", "PauseSandbox"} for action, _, _ in server_b.requests)

            with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="snapshot"):
                worker_b2.shutdown()
            assert remote_b in server_b.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server_b.requests)

            # Once Worker 1's snapshot settles, fence_key_b is cleared and Worker 2's shutdown succeeds.
            allow_ready.set()
            deadline = time.monotonic() + 5.0
            while worker_b1._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not worker_b1._snapshotting_remote_ids
            assert store_b1.owner(fence_key_b) is None

            worker_b2.shutdown()
            assert remote_b not in server_b.sandboxes
            assert sum(1 for action, _, _ in server_b.requests if action == "KillSandbox") == 1
        finally:
            allow_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while worker_b1._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            worker_b1.shutdown()
            worker_b2.shutdown()

    @pytest.mark.parametrize("pause_on_idle", [False, True])
    def test_deferred_warm_teardown_keeps_sandbox_handle_open(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        pause_on_idle: bool,
    ) -> None:
        provider, server, _ = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"idle_timeout": 10, "vefaas": {"pause_on_idle": pause_on_idle}},
        )
        try:
            sid = provider.acquire("t-defer-open", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            tracked = provider._sandboxes[sid]
            provider.release(sid)
            assert sid in provider._warm_pool

            # First fence check (pre-claim) sees None; second check (post-claim) raises transient backend error.
            orig_owner = provider._ownership.owner
            fence_key = provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_id)
            fence_checks = {"count": 0}

            def flaky_owner(key: str) -> str | None:
                if key == fence_key:
                    fence_checks["count"] += 1
                    if fence_checks["count"] == 2:
                        raise OwnershipBackendError("transient redis outage on second fence check")
                return orig_owner(key)

            monkeypatch.setattr(provider._ownership, "owner", flaky_owner)
            assert provider._destroy_warm_entry(sid, tracked, reason="idle_timeout") is False
            assert fence_checks["count"] == 2
            assert sid in provider._warm_pool
            assert tracked.sandbox.closed is False
            assert not any(action in {"KillSandbox", "PauseSandbox"} for action, _, _ in server.requests)

            # Next acquire reclaims the healthy warm sandbox with an open AioSandbox handle.
            monkeypatch.setattr(provider._ownership, "owner", orig_owner)
            reclaimed_sid = provider.acquire("t-defer-open", user_id="u1")
            assert reclaimed_sid == sid
            reclaimed_aio = provider.get(sid)
            assert reclaimed_aio is tracked.sandbox
            assert reclaimed_aio is not None and reclaimed_aio.closed is False
        finally:
            provider.shutdown()

    def test_uncertain_snapshot_submission_retains_fence_until_reconciled(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Server accepts CreateSandboxSnapshot (creating snap-1 in Creating) then times out reading response.
        server_a = _FakeVeFaaSServer()
        server_a.snapshot_status_sequence = ["Creating"]
        orig_handler_a = server_a.handler
        reconcile_polled = threading.Event()
        allow_ready = threading.Event()

        def timeout_after_accept_handler(req: httpx.Request) -> httpx.Response:
            action = req.url.params.get("Action")
            if action == "CreateSandboxSnapshot":
                # Accept snapshot on server first, then fail transport with ReadTimeout.
                orig_handler_a(req)
                raise httpx.ReadTimeout("timed out reading CreateSandboxSnapshot response")
            if action == "ListSandboxSnapshots":
                if allow_ready.is_set():
                    for snap_rec in server_a.snapshots.values():
                        snap_rec["Status"] = "Ready"
                        snap_rec["_status_queue"] = ["Ready"]
                else:
                    reconcile_polled.set()
            return orig_handler_a(req)

        server_a.handler = timeout_after_accept_handler  # type: ignore[method-assign]
        provider_a, _, _ = _install_provider(monkeypatch, tmp_path / "uncertain-a", server=server_a)
        provider_a._snapshot_watch_interval = 0.01
        try:
            sid_a = provider_a.acquire("t-uncertain-snap", user_id="u1")
            remote_a = provider_a._sandboxes[sid_a].remote_sandbox_id
            fence_key_a = provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_a)

            with pytest.raises(VeFaaSApiError, match="CreateSandboxSnapshot"):
                provider_a.create_snapshot(sid_a, wait=True)

            assert remote_a in provider_a._snapshotting_remote_ids
            assert provider_a._ownership.owner(fence_key_a) == provider_a._owner_id
            assert reconcile_polled.wait(timeout=5)

            # Shutdown must defer teardown while the accepted snapshot is still Creating.
            with pytest.raises(provider_mod._VeFaaSShutdownIncompleteError, match="snapshot"):
                provider_a.shutdown()
            assert remote_a in server_a.sandboxes
            assert not any(action == "KillSandbox" for action, _, _ in server_a.requests)

            # Once the snapshot settles to Ready, reconciler releases both fences and shutdown succeeds.
            allow_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider_a._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider_a._snapshotting_remote_ids
            assert provider_a._ownership.owner(fence_key_a) is None

            provider_a.shutdown()
            assert remote_a not in server_a.sandboxes
            assert sum(1 for action, _, _ in server_a.requests if action == "KillSandbox") == 1
        finally:
            allow_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider_a._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            provider_a.shutdown()

        # Case B: ReadTimeout where server never created a snapshot -> reconciler confirms none and releases fence.
        server_b = _FakeVeFaaSServer()
        orig_handler_b = server_b.handler

        def timeout_before_accept_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "CreateSandboxSnapshot":
                raise httpx.ReadTimeout("timed out before reaching server")
            return orig_handler_b(req)

        server_b.handler = timeout_before_accept_handler  # type: ignore[method-assign]
        provider_b, _, _ = _install_provider(monkeypatch, tmp_path / "uncertain-b", server=server_b)
        provider_b._snapshot_watch_interval = 0.01
        try:
            sid_b = provider_b.acquire("t-uncertain-none", user_id="u1")
            remote_b = provider_b._sandboxes[sid_b].remote_sandbox_id
            fence_key_b = provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_b)

            with pytest.raises(VeFaaSApiError):
                provider_b.create_snapshot(sid_b, wait=True)

            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider_b._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider_b._snapshotting_remote_ids
            assert provider_b._ownership.owner(fence_key_b) is None
            provider_b.shutdown()
            assert remote_b not in server_b.sandboxes
        finally:
            provider_b.shutdown()

        # Case C: Definitive 4xx rejection releases fences immediately without spawning a watcher.
        server_c = _FakeVeFaaSServer()
        server_c.snapshot_create_error = (400, "InvalidParameter", "bad snapshot request")
        provider_c, _, _ = _install_provider(monkeypatch, tmp_path / "uncertain-c", server=server_c)
        try:
            sid_c = provider_c.acquire("t-definitive-400", user_id="u1")
            remote_c = provider_c._sandboxes[sid_c].remote_sandbox_id
            with pytest.raises(VeFaaSApiError):
                provider_c.create_snapshot(sid_c, wait=True)
            assert not provider_c._snapshotting_remote_ids
            assert not provider_c._snapshot_watchers
            assert provider_c._ownership.owner(provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_c)) is None
        finally:
            provider_c.shutdown()

    def test_snapshot_fence_release_serialized_with_concurrent_reservation(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        server.snapshot_status_sequence = ["Creating"]
        orig_handler = server.handler
        allow_snap1_ready = threading.Event()
        allow_snap2_ready = threading.Event()

        def two_snap_handler(req: httpx.Request) -> httpx.Response:
            if req.url.params.get("Action") == "DescribeSandboxSnapshot":
                payload = json.loads(req.content.decode("utf-8"))
                snap_id = payload["SnapshotId"]
                snap_rec = server.snapshots.get(snap_id)
                if snap_rec is not None:
                    if snap_id == "snap-1" and allow_snap1_ready.is_set():
                        snap_rec["Status"] = "Ready"
                        snap_rec["_status_queue"] = ["Ready"]
                    elif snap_id == "snap-2" and allow_snap2_ready.is_set():
                        snap_rec["Status"] = "Ready"
                        snap_rec["_status_queue"] = ["Ready"]
            return orig_handler(req)

        server.handler = two_snap_handler  # type: ignore[method-assign]
        provider, _, _ = _install_provider(monkeypatch, tmp_path, server=server)
        provider._snapshot_watch_interval = 0.01
        try:
            sid = provider.acquire("t-fence-serialize", user_id="u1")
            remote_id = provider._sandboxes[sid].remote_sandbox_id
            fence_key = provider_mod.VeFaaSSandboxProvider._snapshot_fence_key(remote_id)

            release_entered = threading.Event()
            allow_release = threading.Event()
            orig_release = provider._ownership.release

            def gated_release(key: str) -> None:
                if key == fence_key and not allow_release.is_set():
                    release_entered.set()
                    assert allow_release.wait(timeout=5)
                orig_release(key)

            monkeypatch.setattr(provider._ownership, "release", gated_release)

            # Snapshot 1 starts and then settles while its fence release pauses mid-delete.
            snap1 = provider.create_snapshot(sid, wait=False)
            assert snap1.id == "snap-1"
            allow_snap1_ready.set()
            assert release_entered.wait(timeout=5)

            # Snapshot 2 tries to reserve the same remote fence while Snapshot 1 is deleting it.
            with ThreadPoolExecutor(max_workers=1) as pool:
                snap2_future = pool.submit(provider.create_snapshot, sid, wait=False)
                # Give Snapshot 2 a moment to contend on _snapshot_fence_lock before releasing Snapshot 1.
                threading.Event().wait(0.03)
                assert not snap2_future.done()
                allow_release.set()
                snap2 = snap2_future.result(timeout=5)

            assert snap2.id == "snap-2"
            # Snapshot 1's completion must NOT have deleted Snapshot 2's active cross-worker fence.
            assert provider._ownership.owner(fence_key) == provider._owner_id
            assert provider._remote_snapshot_fences.get(remote_id) == 1

            allow_snap2_ready.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            assert not provider._snapshotting_remote_ids
            assert provider._ownership.owner(fence_key) is None
        finally:
            allow_snap1_ready.set()
            allow_snap2_ready.set()
            allow_release.set()
            wait_evt = threading.Event()
            deadline = time.monotonic() + 5.0
            while provider._snapshotting_remote_ids and time.monotonic() < deadline:
                wait_evt.wait(0.01)
            provider.shutdown()

    def test_snapshot_lookup_and_pruning_use_server_filters_and_handle_multipage_fallback(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Case A: Server honors Metadata.* + Status filters -> O(1) single-page lookup despite 120 other-tenant snapshots.
        server_a = _FakeVeFaaSServer()
        sid_a = derive_sandbox_scope_token(user_id="u-filter", thread_id="t-filter")
        for idx in range(120):
            server_a.snapshots[f"snap-other-{idx:03d}"] = {
                "SnapshotId": f"snap-other-{idx:03d}",
                "SandboxId": f"vefaas-other-{idx}",
                "FunctionId": "fn-demo-app",
                "Status": "Ready",
                "SnapshotType": "disk",
                "CreatedAt": f"2026-11-23T00:{idx // 60:02d}:{idx % 60:02d}Z",
                "Metadata": {
                    provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                    provider_mod.META_KEY_SANDBOX_ID: f"other-scope-{idx}",
                },
            }
        server_a.snapshots["snap-target-latest"] = {
            "SnapshotId": "snap-target-latest",
            "SandboxId": "vefaas-prev-a",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T05:00:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_a,
            },
        }
        provider_a, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "filter-a",
            server=server_a,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )
        try:
            assert provider_a.acquire("t-filter", user_id="u-filter") == sid_a
            list_reqs = [payload for action, payload, _ in server_a.requests if action == "ListSandboxSnapshots"]
            assert len(list_reqs) == 1
            assert list_reqs[0]["PageNumber"] == 1
            filter_map = {f["Name"]: f["Values"] for f in list_reqs[0]["Filters"]}
            assert filter_map == {
                f"Metadata.{provider_mod.META_KEY_PROVIDER}": [provider_mod.META_VAL_PROVIDER],
                f"Metadata.{provider_mod.META_KEY_SANDBOX_ID}": [sid_a],
                "Status": ["Ready"],
            }
            create_reqs = [payload for action, payload, _ in server_a.requests if action == "CreateSandbox"]
            assert create_reqs[-1]["SnapshotId"] == "snap-target-latest"
        finally:
            provider_a.shutdown()

        # Case B: Backend rejects Metadata.* filters with 400 -> caches fallback, paginates across 3 pages
        # (120 unrelated snapshots on pages 1-3 + matching snapshot on page 3), and restores + prunes accurately.
        server_b = _FakeVeFaaSServer()
        server_b.reject_snapshot_metadata_filters = True
        sid_b = derive_sandbox_scope_token(user_id="u-page", thread_id="t-page")
        for idx in range(115):
            server_b.snapshots[f"snap-noise-{idx:03d}"] = {
                "SnapshotId": f"snap-noise-{idx:03d}",
                "SandboxId": f"vefaas-noise-{idx}",
                "FunctionId": "fn-demo-app",
                "Status": "Ready",
                "SnapshotType": "disk",
                "CreatedAt": f"2026-11-23T00:{idx // 60:02d}:{idx % 60:02d}Z",
                "Metadata": {
                    provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                    provider_mod.META_KEY_SANDBOX_ID: f"noise-scope-{idx}",
                },
            }
        server_b.snapshots["snap-page3-old"] = {
            "SnapshotId": "snap-page3-old",
            "SandboxId": "vefaas-prev-b1",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T04:00:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        server_b.snapshots["snap-page3-new"] = {
            "SnapshotId": "snap-page3-new",
            "SandboxId": "vefaas-prev-b2",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T06:00:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid_b,
            },
        }
        provider_b, _, _ = _install_provider(
            monkeypatch,
            tmp_path / "filter-b",
            server=server_b,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True, "max_snapshots_per_sandbox": 1}},
        )
        try:
            assert provider_b.acquire("t-page", user_id="u-page") == sid_b
            assert provider_b._snapshot_metadata_filter_supported is False
            create_reqs_b = [payload for action, payload, _ in server_b.requests if action == "CreateSandbox"]
            assert create_reqs_b[-1]["SnapshotId"] == "snap-page3-new"

            # Subsequent prune call skips the unsupported Metadata.* filter (no extra 400) and prunes only sid_b's older snapshot.
            reqs_before = len(server_b.requests)
            provider_b._prune_old_snapshots("fn-demo-app", sid_b, keep=1)
            prune_list_reqs = [payload for action, payload, _ in server_b.requests[reqs_before:] if action == "ListSandboxSnapshots"]
            assert len(prune_list_reqs) == 3  # 117 Ready snapshots across 3 pages of 50
            assert all(payload.get("Filters") == [{"Name": "Status", "Values": ["Ready"]}] for payload in prune_list_reqs)
            assert "snap-page3-old" not in server_b.snapshots
            assert "snap-page3-new" in server_b.snapshots
            assert "snap-noise-000" in server_b.snapshots
        finally:
            provider_b.shutdown()

    def test_snapshot_restore_with_preserved_init_marker_refreshes_skills_and_uploads_without_overwriting_workspace(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        server = _FakeVeFaaSServer()
        sid = derive_sandbox_scope_token(user_id="u-snap-sync", thread_id="t-snap-sync")
        server.snapshots["snap-with-marker"] = {
            "SnapshotId": "snap-with-marker",
            "SandboxId": "vefaas-prev-sync",
            "FunctionId": "fn-demo-app",
            "Status": "Ready",
            "SnapshotType": "disk",
            "CreatedAt": "2026-11-23T07:00:00Z",
            "Metadata": {
                provider_mod.META_KEY_PROVIDER: provider_mod.META_VAL_PROVIDER,
                provider_mod.META_KEY_SANDBOX_ID: sid,
            },
        }

        provider, _, created_aio = _install_provider(
            monkeypatch,
            tmp_path,
            server=server,
            sandbox_overrides={"vefaas": {"snapshot_on_idle": True}},
        )

        # Populate host thread dirs (new upload + stale workspace) and a post-snapshot shared skill.
        from deerflow.config.paths import get_paths

        paths = get_paths()
        uploads_dir = paths.sandbox_uploads_dir("t-snap-sync", user_id="u-snap-sync")
        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / "post-snapshot.txt").write_text("fresh upload", encoding="utf-8")

        work_dir = paths.sandbox_work_dir("t-snap-sync", user_id="u-snap-sync")
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "stale-host.txt").write_text("do not overwrite snapshot workspace", encoding="utf-8")

        skills_dir = tmp_path / "skills" / "public" / "updated-skill"
        skills_dir.mkdir(parents=True, exist_ok=True)
        (skills_dir / "SKILL.md").write_text(
            "---\nname: updated-skill\ndescription: Post-snapshot updated skill\n---\n# Updated Skill\n",
            encoding="utf-8",
        )

        class _SnapshotRestoredAio(_FakeAioSandbox):
            def __init__(self, **kwargs: Any) -> None:
                super().__init__(**kwargs)
                # Simulate a disk/full snapshot that preserved /tmp/.deerflow-vefaas-initialized.
                self.uploaded_files[provider_mod._INIT_MARKER_PATH] = f"{sid}\n".encode()

        monkeypatch.setattr(provider_mod, "AioSandbox", lambda **kwargs: created_aio.append(inst := _SnapshotRestoredAio(**kwargs)) or inst)
        try:
            acquired = provider.acquire("t-snap-sync", user_id="u-snap-sync")
            assert acquired == sid
            create_reqs = [payload for action, payload, _ in server.requests if action == "CreateSandbox"]
            assert create_reqs[-1]["SnapshotId"] == "snap-with-marker"

            aio = created_aio[-1]
            # Inspect every tar.gz uploaded during snapshot restore.
            uploaded_members: set[str] = set()
            for remote_path, content in aio.uploaded_files.items():
                if remote_path.endswith(".tar.gz"):
                    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                        uploaded_members.update(archive.getnames())

            assert "uploads/post-snapshot.txt" in uploaded_members
            assert "public/updated-skill/SKILL.md" in uploaded_members
            assert "workspace/stale-host.txt" not in uploaded_members
        finally:
            provider.shutdown()


# ── 10. Prewarm Integration ──────────────────────────────────────────────


class TestPrewarmIntegration:
    @pytest.mark.anyio
    async def test_prewarm_claims_single_vefaas_sandbox_and_releases_to_warm_pool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from langchain_core.messages import HumanMessage

        from deerflow.sandbox import prewarm
        from deerflow.sandbox.lease import (
            ensure_sandbox_lease_owner,
            get_sandbox_lease_manager,
            register_sandbox_prewarm_cleanup,
            release_sandbox_execution_lease_async,
        )
        from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
        from deerflow.sandbox.tools import ensure_sandbox_initialized_async

        provider, server, _aio = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 600},
        )
        app_cfg = _make_app_config(
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 600},
        )
        monkeypatch.setattr(prewarm, "get_app_config", lambda: app_cfg)
        set_sandbox_provider(provider)
        try:
            context: dict[str, Any] = {"user_id": "u-prewarm", "thread_id": "t-prewarm", "app_config": app_cfg}
            ensure_sandbox_lease_owner(context)
            register_sandbox_prewarm_cleanup(context)
            rt = SimpleNamespace(context=context, state={})

            prewarm.start_sandbox_prewarm({"messages": [HumanMessage(content="```sh\npytest tests\n```")]}, rt)
            handle = context["__deerflow_sandbox_prewarm"]
            expected_sid = derive_sandbox_scope_token(user_id="u-prewarm", thread_id="t-prewarm")
            assert await handle.task == expected_sid

            sandbox = await ensure_sandbox_initialized_async(rt)
            assert sandbox.id == expected_sid
            assert handle.claimed is True
            assert sum(1 for a, _, _ in server.requests if a == "CreateSandbox") == 1

            await release_sandbox_execution_lease_async(context)
            assert get_sandbox_lease_manager(provider).binding_for(context["sandbox_lease_owner_id"]) is None
            assert expected_sid in provider._warm_pool
            assert not prewarm._permits
        finally:
            reset_sandbox_provider()
            provider.shutdown()

    @pytest.mark.anyio
    async def test_unused_vefaas_prewarm_releases_to_warm_pool_and_frees_budget(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from langchain_core.messages import HumanMessage

        from deerflow.sandbox import prewarm
        from deerflow.sandbox.lease import (
            ensure_sandbox_lease_owner,
            get_sandbox_lease_manager,
            register_sandbox_prewarm_cleanup,
            release_sandbox_execution_lease_async,
        )
        from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider

        provider, server, _aio = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 600},
        )
        app_cfg = _make_app_config(
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 600},
        )
        monkeypatch.setattr(prewarm, "get_app_config", lambda: app_cfg)
        set_sandbox_provider(provider)
        try:
            context: dict[str, Any] = {"user_id": "u-unused", "thread_id": "t-unused", "app_config": app_cfg}
            ensure_sandbox_lease_owner(context)
            register_sandbox_prewarm_cleanup(context)
            rt = SimpleNamespace(context=context, state={})

            prewarm.start_sandbox_prewarm({"messages": [HumanMessage(content="```python\nprint(1)\n```")]}, rt)
            handle = context["__deerflow_sandbox_prewarm"]
            expected_sid = derive_sandbox_scope_token(user_id="u-unused", thread_id="t-unused")
            assert await handle.task == expected_sid
            assert handle.claimed is False

            # No tool called — execution lease cleanup drains startup, releases the sandbox
            # to the warm pool, clears the lease binding, and frees the speculative permit.
            await release_sandbox_execution_lease_async(context)
            assert provider.get(expected_sid) is None
            assert expected_sid in provider._warm_pool
            assert get_sandbox_lease_manager(provider).binding_for(context["sandbox_lease_owner_id"]) is None
            assert not prewarm._permits
        finally:
            reset_sandbox_provider()
            provider.shutdown()
        assert any(a == "KillSandbox" for a, _, _ in server.requests)

    @pytest.mark.anyio
    async def test_vefaas_explicit_skill_policy_uses_eager_sync_not_prewarm(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from langchain_core.messages import HumanMessage

        from deerflow.sandbox.lease import (
            ensure_sandbox_lease_owner,
            register_sandbox_prewarm_cleanup,
            release_sandbox_execution_lease_async,
        )
        from deerflow.sandbox.middleware import SandboxMiddleware
        from deerflow.sandbox.sandbox_provider import reset_sandbox_provider, set_sandbox_provider
        from deerflow.skills.projection import SkillProjectionPaths

        provider, server, _aio = _install_provider(
            monkeypatch,
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 0},
        )
        app_cfg = _make_app_config(
            tmp_path,
            sandbox_overrides={"prewarm": True, "prewarm_max_concurrent": 1, "idle_timeout": 0},
        )
        set_sandbox_provider(provider)

        public_dir = tmp_path / "proj" / "public"
        custom_dir = tmp_path / "proj" / "custom"
        legacy_dir = tmp_path / "proj" / "legacy"
        integrations_dir = tmp_path / "proj" / "integrations"
        (public_dir / "demo-skill").mkdir(parents=True)
        (public_dir / "demo-skill" / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
        custom_dir.mkdir(parents=True)
        legacy_dir.mkdir(parents=True)
        integrations_dir.mkdir(parents=True)
        projection = SkillProjectionPaths(
            public=public_dir,
            custom=custom_dir,
            legacy=legacy_dir,
            integrations=integrations_dir,
        )

        sync_calls: list[str] = []
        orig_sync = provider.sync_agent_skills

        def spy_sync(sandbox_id: str, **kwargs: Any) -> None:
            sync_calls.append(sandbox_id)
            orig_sync(sandbox_id, **kwargs)

        monkeypatch.setattr(provider, "sync_agent_skills", spy_sync)

        middleware = SandboxMiddleware(lazy_init=True)
        monkeypatch.setattr(middleware, "_prepare_agent_skill_projection", lambda *args, **kwargs: projection)

        context: dict[str, Any] = {"user_id": "u-skills", "thread_id": "t-skills", "app_config": app_cfg}
        ensure_sandbox_lease_owner(context)
        register_sandbox_prewarm_cleanup(context)
        rt = SimpleNamespace(context=context)
        state: dict[str, Any] = {"messages": [HumanMessage(content="```sh\npytest tests\n```")]}
        try:
            updates = await middleware.abefore_agent(state, rt)
            expected_sid = derive_sandbox_scope_token(user_id="u-skills", thread_id="t-skills")
            assert updates == {"sandbox": {"sandbox_id": expected_sid}}
            assert sync_calls == [expected_sid]

            state.update(updates)
            await middleware.abefore_model(state, rt)
            # Eager path already populated state["sandbox"], so speculative prewarm is skipped.
            assert "__deerflow_sandbox_prewarm" not in context
            assert sum(1 for a, _, _ in server.requests if a == "CreateSandbox") == 1
        finally:
            await release_sandbox_execution_lease_async(context)
            reset_sandbox_provider()
            provider.shutdown()
