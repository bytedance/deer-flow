"""Explicit JSON file criteria through the public acceptance entry point."""

import base64
import os
import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.subagents.acceptance_checks import check_acceptance_criteria, parse_file_criterion


@pytest.mark.parametrize("sandbox_id", ["local", "local:thread-1"])
@pytest.mark.parametrize("content", [b"{}", b"{invalid", None])
def test_local_json_rechecks_revoked_sandbox_grant(tmp_path, monkeypatch, sandbox_id, content):
    """Retained sandbox IDs do not retain grants; revocation prevents file reads and syntax verdicts."""
    from deerflow.authz.rbac import RbacAuthorizationProvider
    from deerflow.config.authorization_config import AuthorizationConfig

    config = SimpleNamespace(authorization=AuthorizationConfig(enabled=True))
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": "*"}}})
    monkeypatch.setattr("deerflow.config.get_app_config", lambda: config)
    monkeypatch.setattr("deerflow.authz.sandbox_authz.resolve_authorization_provider", lambda config: provider)
    runtime = SimpleNamespace(
        state={"sandbox": {"sandbox_id": sandbox_id}},
        context={"thread_id": "thread-1", "user_id": "user-1", "user_role": "user"},
    )
    if content is not None:
        (tmp_path / "report.json").write_bytes(content)
    criterion = "file:report.json json-valid"

    def check():
        return check_acceptance_criteria([criterion], runtime=runtime, thread_data={"workspace_path": str(tmp_path)})

    assert check()["leaves"][0]["checked"] is True
    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": []}}})
    open_file = Mock(wraps=os.open)
    monkeypatch.setattr(os, "open", open_file)
    verdict = check()
    open_file.assert_not_called()
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (False, False)
    assert verdict["unchecked"] == [criterion]
    assert runtime.state["sandbox"]["sandbox_id"] == sandbox_id

    provider = RbacAuthorizationProvider(roles={"user": {"sandbox": {"allow": "*"}}})
    restored = check()["leaves"][0]
    assert (restored["checked"], restored["holds"]) == (True, content == b"{}")
    if content is None:
        open_file.assert_not_called()
    else:
        open_file.assert_called_once()


def test_json_file_is_checked_explicitly(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "report.json").write_bytes(b'{"items": [1, true, null]}')
    runtime = SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}})
    criterion = "file:report.json json-valid"
    verdict = check_acceptance_criteria([criterion], runtime=runtime, thread_data={"workspace_path": str(workspace)})

    assert parse_file_criterion(criterion) == ("file_json_valid", "report.json")
    assert verdict["leaves"][0]["checked"] is True
    assert verdict["leaves"][0]["holds"] is True
    assert verdict["all_hold"] is True


@pytest.mark.parametrize("content", [b"NaN", b"Infinity", b"-Infinity", b'{"value": NaN}'])
def test_nonstandard_constants_do_not_hold(tmp_path, content):
    (tmp_path / "report.json").write_bytes(content)
    verdict = check_acceptance_criteria(
        ["file:report.json json-valid"],
        runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}}),
        thread_data={"workspace_path": str(tmp_path)},
    )
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (True, False)


@pytest.fixture
def remote_sandbox(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("Requires Linux sandbox tools")

    class ShellSandbox:
        transform = staticmethod(lambda output: output)
        before_read = staticmethod(lambda: None)

        def execute_command(self, command, **kwargs):
            assert kwargs["env"]
            args = shlex.split(command)
            if "json-read" in args:
                self.before_read()
            prefix = "/mnt/user-data/workspace"
            args = [str(tmp_path) + arg[len(prefix) :] if arg == prefix or arg.startswith(prefix + "/") else arg for arg in args]
            output = subprocess.run(args, capture_output=True, text=True, check=True, timeout=15).stdout
            return self.transform(output)

        def read_file(self, *args, **kwargs):
            pytest.fail("JSON acceptance must not fall back to unbounded full-content reads")

    sandbox = ShellSandbox()
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime=None: sandbox)
    return sandbox


def test_remote_complete_json_is_checked(tmp_path, remote_sandbox):
    (tmp_path / "report.json").write_bytes(b'{"ok": true}')
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["all_hold"] is True


@pytest.fixture(params=["local", "remote"])
def check_file(request, tmp_path):
    remote = request.param == "remote"
    if remote:
        request.getfixturevalue("remote_sandbox")
    runtime = SimpleNamespace(state=None if remote else {"sandbox": {"sandbox_id": "local"}})

    def check(content, *, criterion="file:report.json json-valid", **kwargs):
        if content is not None:
            (tmp_path / "report.json").write_bytes(content)
        return check_acceptance_criteria([criterion], runtime=runtime, thread_data={"workspace_path": str(tmp_path)}, **kwargs)

    return check


@pytest.mark.parametrize("content", [b"{}", b"[]", b"null", b"true", b"42", b'"text"', b'{"x":1,"x":2}', b"1e400", b"9" * 5000, ' {"城市":"深圳"}\r\n'.encode()])
def test_valid_json_syntax(check_file, content):
    assert check_file(content)["all_hold"] is True


@pytest.mark.parametrize("content", [b"", b"  \r\n", b"{", b'{"a":}', b"[1,]", b"{} {}", b"//comment\n{}", b"\xff", b"\xef\xbb\xbf{}", b"NaN", b"Infinity", b"-Infinity", b'"a\x00b"'])
def test_invalid_complete_json_does_not_hold(check_file, content):
    verdict = check_file(content)
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (True, False)
    assert verdict["unchecked"] == []


@pytest.mark.parametrize(("size", "checked", "holds"), [(49_999, True, True), (50_000, True, True), (50_001, False, False)])
def test_byte_limit(check_file, size, checked, holds):
    verdict = check_file(b'"' + b"x" * (size - 2) + b'"')
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (checked, holds)


def test_multibyte_content_counts_bytes(check_file):
    verdict = check_file(('"' + "中" * 16_667 + '"').encode())
    assert verdict["leaves"][0]["checked"] is False


def test_missing_file_is_negative(check_file):
    verdict = check_file(None)
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (True, False)


def test_parser_depth_limit_is_uncertain(check_file):
    # CPython 3.12's C parser limit differs from the boundary set by sys.setrecursionlimit.
    verdict = check_file(b"[" * 20_000 + b"0" + b"]" * 20_000)
    assert verdict["leaves"][0]["checked"] is False
    assert "resource limit" in verdict["leaves"][0]["detail"]


@pytest.mark.parametrize("size", [None, 1, 3])
def test_unknown_size_or_incomplete_read_is_uncertain(check_file, size):
    verdict = check_file(b"{}", size_prober=lambda *args: size)
    assert verdict["leaves"][0]["checked"] is False


def test_growth_past_limit_is_uncertain(check_file):
    verdict = check_file(b"{}" + b" " * 60_000, size_prober=lambda *args: 2)
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.parametrize("path", ["../outside.json", "/mnt/user-data/uploads/report.json", "/mnt/user-data/workspace/../../other/report.json"])
def test_out_of_scope_is_uncertain(check_file, path):
    verdict = check_file(b"{}", criterion=f"file:{path} json-valid")
    assert verdict["leaves"][0]["checked"] is False
    assert "outside" in verdict["leaves"][0]["detail"]


def test_missing_thread_context_is_uncertain():
    verdict = check_acceptance_criteria(["file:report.json json-valid"])
    assert verdict["leaves"][0]["checked"] is False


def test_directory_is_uncertain(check_file, tmp_path):
    (tmp_path / "report.json").mkdir()
    assert check_file(None)["leaves"][0]["checked"] is False


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX symlinks")
def test_symlink_escape_is_uncertain(check_file, tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(b"{}")
    (tmp_path / "report.json").symlink_to(outside)
    assert check_file(None)["leaves"][0]["checked"] is False


@pytest.mark.skipif(os.name == "nt", reason="Requires POSIX FIFOs")
def test_fifo_is_uncertain_without_opening(check_file, tmp_path):
    os.mkfifo(tmp_path / "report.json")
    assert check_file(None)["leaves"][0]["checked"] is False


def test_remote_incomplete_transport_is_uncertain(tmp_path, remote_sandbox):
    (tmp_path / "report.json").write_bytes(b"{}")
    remote_sandbox.transform = lambda text: text[:-4] if text.startswith("JSON\n") else text
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.parametrize("output", ["Error: permission denied", "JSON\n!invalid!\nEND\n", "JSON\ne30=\nEND\n", "JSON\n" + base64.b64encode(b"{}\n001").decode() + "\nEND\n"])
def test_remote_failed_read_is_not_invalid_json(tmp_path, remote_sandbox, output):
    (tmp_path / "report.json").write_bytes(b"{}")
    remote_sandbox.transform = lambda text: output if text.startswith("JSON\n") else text
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


def test_local_permission_failure_is_uncertain(tmp_path, monkeypatch):
    (tmp_path / "report.json").write_bytes(b"{}")

    def denied(*args, **kwargs):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "open", denied)
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}}), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.parametrize("criterion", ["file:report.json exists", "file:report.json non-empty", "file_written:report.json"])
def test_json_extension_does_not_change_old_rules(check_file, criterion):
    verdict = check_file(b"not JSON", criterion=criterion, content_reader=lambda *args: "not JSON")
    assert verdict["all_hold"] is True


@pytest.mark.parametrize("criterion", ["file:report.json JSON-VALID", "FILE:report.json jſon-valid", "file:/mnt/user-data/workspace/report.json json-valid"])
def test_normalized_spellings_use_same_json_family(check_file, criterion):
    verdict = check_file(b"{}", criterion=criterion)
    assert verdict["all_hold"] is True
    assert verdict["leaves"][0]["family"] == "file_json_valid"


def test_remote_oversize_does_not_read_content(tmp_path, remote_sandbox):
    (tmp_path / "report.json").write_bytes(b" " * 50_001)
    remote_sandbox.before_read = lambda: pytest.fail("Oversize files must not have their content read")
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


def test_remote_file_grows_after_size_probe(tmp_path, remote_sandbox):
    path = tmp_path / "report.json"
    path.write_bytes(b"{}")
    remote_sandbox.before_read = lambda: path.write_bytes(b"{}" + b" " * 100_000)
    verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="Requires non-root POSIX permissions")
def test_remote_permission_denied_is_uncertain(tmp_path, remote_sandbox):
    path = tmp_path / "report.json"
    path.write_bytes(b"{}")
    path.chmod(0)
    try:
        verdict = check_acceptance_criteria(["file:report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
        assert verdict["leaves"][0]["checked"] is False
    finally:
        path.chmod(0o600)


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="Requires non-root POSIX permissions")
@pytest.mark.parametrize(("before_read", "exists"), [(False, True), (False, False), (True, True)])
def test_remote_inaccessible_parent_is_uncertain(tmp_path, remote_sandbox, before_read, exists):
    parent = tmp_path / "locked"
    nested = parent / "nested"
    nested.mkdir(parents=True)
    if exists:
        (nested / "report.json").write_bytes(b"{}")
    if before_read:
        remote_sandbox.before_read = lambda: parent.chmod(0)
    else:
        parent.chmod(0)
    try:
        verdict = check_acceptance_criteria(
            ["file:locked/nested/report.json json-valid"],
            runtime=SimpleNamespace(state=None),
            thread_data={"workspace_path": str(tmp_path)},
        )
        assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (False, False)
    finally:
        parent.chmod(0o700)


@pytest.mark.parametrize("path", ["missing/report.json", "missing/nested/report.json"])
def test_remote_missing_parent_is_negative(tmp_path, remote_sandbox, path):
    verdict = check_acceptance_criteria([f"file:{path} json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert (verdict["leaves"][0]["checked"], verdict["leaves"][0]["holds"]) == (True, False)


@pytest.mark.parametrize("target", ["missing", "outside"])
def test_remote_missing_file_through_symlink_is_uncertain(tmp_path, remote_sandbox, target):
    destination = tmp_path / target if target == "missing" else tmp_path.parent
    (tmp_path / "link").symlink_to(destination, target_is_directory=True)
    verdict = check_acceptance_criteria(["file:link/report.json json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["leaves"][0]["checked"] is False


def test_remote_special_filename_is_literal(tmp_path, remote_sandbox):
    filename = "report '; echo bad; #.json"
    (tmp_path / filename).write_bytes(b"{}")
    verdict = check_acceptance_criteria([f"file:{filename} json-valid"], runtime=SimpleNamespace(state=None), thread_data={"workspace_path": str(tmp_path)})
    assert verdict["all_hold"] is True
