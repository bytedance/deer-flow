"""CSV header acceptance through the public, workspace-scoped checklist."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.subagents import acceptance_checks as checks


@pytest.fixture
def parser_clock(monkeypatch):
    import time

    original_monotonic = time.monotonic
    clock = Mock(return_value=0)
    monkeypatch.setattr(checks, "time", SimpleNamespace(monotonic=clock))
    yield clock
    # Deadline simulations must leave event loops and other threads on the real clock.
    assert time.monotonic is original_monotonic


@pytest.fixture
def check_csv(tmp_path):
    def check(content, columns=None, path="report.csv", **kwargs):
        if content is not None:
            (tmp_path / "report.csv").write_bytes(content)
        criterion = f"file:{path} csv-columns:{json.dumps(columns or ['id', 'name'])}"
        return checks.check_acceptance_criteria(
            [criterion],
            runtime=SimpleNamespace(state={"sandbox": {"sandbox_id": "local"}}),
            thread_data={"workspace_path": str(tmp_path)},
            **kwargs,
        )

    return check


@pytest.mark.parametrize("content", [b"id,name\n1,A", b"\xef\xbb\xbfid,name\r\n", b'"id","name",extra\n', b"id,name", b"id,name\n" + b"\xff" * 60_000], ids=["plain", "bom", "quoted", "no-newline", "large-invalid-body"])
def test_header_holds_without_validating_body(check_csv, content):
    assert check_csv(content)["all_hold"] is True


@pytest.mark.parametrize("content", [b"", b"\n", b"\xef\xbb\xbf", b"id,other\n", b"id,name,name\n", b"id,name,\n", b"ID,name\n", b"id, name\n", b'"id","name\n', b"id,\xff\n"])
def test_invalid_or_missing_header_does_not_hold(check_csv, content):
    leaf = check_csv(content)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)


def test_quoted_columns_and_multiline_header(check_csv):
    assert check_csv(b'"last,name","line\nbreak","a""b"\r\n', ["last,name", "line\nbreak", 'a"b'])["all_hold"] is True


@pytest.mark.parametrize("size,checked", [(50_000, True), (50_001, False)])
def test_header_byte_limit(check_csv, size, checked):
    leaf = check_csv(b"id,name," + b"x" * (size - 9) + b"\n" + b"1" * 60_000)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (checked, checked)


def test_partial_header_cannot_hold(check_csv):
    leaf = check_csv(b"id,name", size_prober=lambda *args: 100)["leaves"][0]
    assert leaf["checked"] is False


def test_missing_file_is_negative(check_csv):
    leaf = check_csv(None)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)


@pytest.mark.parametrize("path", ["../outside.csv", "/mnt/user-data/uploads/report.csv"])
def test_outside_shared_workspace_never_reads(check_csv, path):
    probe = Mock(side_effect=AssertionError("out of scope"))
    assert check_csv(b"id,name\n", path=path, size_prober=probe)["leaves"][0]["checked"] is False
    probe.assert_not_called()


@pytest.mark.parametrize("payload", ["[]", '["id","id"]', "[1]", "null", '[""]', '["id",]', "id,name"])
def test_invalid_criteria_are_unverified(payload):
    criterion = f"file:report.csv csv-columns:{payload}"
    verdict = checks.check_acceptance_criteria([criterion])
    assert verdict["unchecked"] == [criterion]
    assert verdict["all_hold"] is False


def test_admission_uses_csv_path():
    assert checks.parse_file_criterion('file:report.csv csv-columns:["id"]') == ("file_csv_columns", "report.csv")


@pytest.mark.parametrize("column", ["\ud800", "\udfff", "id\ud800"])
def test_surrogate_columns_are_invalid_before_file_access(check_csv, column):
    probe = Mock(side_effect=AssertionError("invalid criteria must not access files"))
    verdict = check_csv(b"id,name\n", [column], size_prober=probe)
    assert verdict["leaves"][0]["checked"] is False
    json.dumps(verdict, ensure_ascii=False).encode("utf-8")
    probe.assert_not_called()


def test_escaped_surrogate_pair_is_a_valid_unicode_column(check_csv):
    assert check_csv("id,\U0001f600\n".encode(), ["\U0001f600"])["all_hold"] is True


@pytest.mark.parametrize("header", [b'"id"x,name\n', b'"line\nbreak"x,name\r\n', b'"id"x,name\r'])
@pytest.mark.parametrize("large_body", [False, True])
def test_definite_malformed_header_is_negative_regardless_of_body(check_csv, header, large_body):
    leaf = check_csv(header + (b"x" * 60_000 if large_body else b""))["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)
    assert leaf["detail"] == "invalid CSV header"


def test_truncated_quoted_header_remains_unverified(check_csv):
    leaf = check_csv(b'"id\n' + b"x" * 60_000)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)
    assert leaf["detail"] == "CSV header incomplete within the read cap"


@pytest.mark.parametrize("size,checked", [(50_000, True), (50_001, False)])
def test_malformed_header_respects_byte_budget(check_csv, size, checked):
    leaf = check_csv(b'"id"x,' + b"x" * (size - 7) + b"\n" + b"x" * 60_000)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (checked, False)


def test_malformed_header_respects_parser_deadline(check_csv, monkeypatch, parser_clock):
    reader = checks.csv.reader

    def delayed_parse(*args, **kwargs):
        parser_clock.return_value = 6
        return reader(*args, **kwargs)

    monkeypatch.setattr(checks.csv, "reader", delayed_parse)
    leaf = check_csv(b'"id"x,name\n')["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)
    assert leaf["detail"] == "CSV header deadline exceeded"


def test_revoked_access_prevents_metadata(check_csv, monkeypatch):
    from deerflow.sandbox.exceptions import SandboxError

    monkeypatch.setattr("deerflow.authz.sandbox_authz.authorize_sandbox_execution", Mock(side_effect=SandboxError("denied")))
    probe = Mock(side_effect=AssertionError("must authorize first"))
    assert check_csv(b"id,name\n", size_prober=probe)["leaves"][0]["checked"] is False
    probe.assert_not_called()


@pytest.mark.parametrize("content", [b'id,name\n"unterminated', b"id,name\r1,A\r", b"id,name\r\n1,A\r\n"])
def test_only_first_logical_record_is_checked(check_csv, content):
    assert check_csv(content)["all_hold"] is True


def test_unknown_size_does_not_read(check_csv, monkeypatch):
    reader = Mock(side_effect=AssertionError("no size evidence"))
    monkeypatch.setattr(checks, "_read_bounded_file_content", reader)
    assert check_csv(b"id,name\n", size_prober=lambda *args: None)["leaves"][0]["checked"] is False
    reader.assert_not_called()


def test_expired_read_is_unverified(check_csv, monkeypatch, parser_clock):
    def delayed(*args, **kwargs):
        parser_clock.return_value = 6
        return b"id,name\n"

    monkeypatch.setattr(checks, "_read_bounded_file_content", delayed)
    assert check_csv(b"id,name\n")["leaves"][0]["checked"] is False


@pytest.mark.parametrize("failure", [None, OSError("unreadable")])
def test_read_failure_remains_unverified(check_csv, monkeypatch, failure):
    reader = Mock(side_effect=failure) if failure else Mock(return_value=None)
    monkeypatch.setattr(checks, "_read_bounded_file_content", reader)
    assert check_csv(b"id,name\n")["leaves"][0]["checked"] is False


def test_remote_transport_checks_deadline_and_completion(monkeypatch, tmp_path):
    import base64

    payload = "JSON\n" + base64.b64encode(b"id,name\n\n000").decode() + "\nEND\n"
    sandbox = Mock()
    sandbox.execute_command.return_value = payload
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)

    def check():
        return checks.check_acceptance_criteria(
            ['file:report.csv csv-columns:["id","name"]'],
            runtime=SimpleNamespace(state=None),
            thread_data={"workspace_path": str(tmp_path)},
            size_prober=lambda *args: 8,
        )

    assert check()["all_hold"] is True
    command = sandbox.execute_command.call_args
    assert command.kwargs["timeout"] == 10
    assert "/usr/bin/timeout 5" in command.args[0]
    assert command.args[0].endswith("50001")
    sandbox.execute_command.return_value = payload[:-5]
    assert check()["leaves"][0]["checked"] is False
    sandbox.execute_command.return_value = "JSON\n" + base64.b64encode(b"id,name\n\n124").decode() + "\nEND\n"
    assert check()["leaves"][0]["checked"] is False
    sandbox.read_file.assert_not_called()


def test_parser_resource_limit_is_unverified(check_csv, monkeypatch):
    monkeypatch.setattr(checks.csv, "reader", Mock(side_effect=checks.csv.Error("field larger than field limit (2)")))
    assert check_csv(b"id,name\n")["leaves"][0]["checked"] is False


def test_missing_workspace_is_unverified():
    verdict = checks.check_acceptance_criteria(['file:report.csv csv-columns:["id"]'])
    assert verdict["leaves"][0]["checked"] is False


def test_directory_is_unverified(check_csv, tmp_path):
    (tmp_path / "report.csv").mkdir()
    assert check_csv(None)["leaves"][0]["checked"] is False


def test_local_read_rechecks_authorization(check_csv, monkeypatch):
    from deerflow.sandbox.exceptions import SandboxError

    authorize = Mock(side_effect=[None, SandboxError("revoked")])
    monkeypatch.setattr("deerflow.authz.sandbox_authz.authorize_sandbox_execution", authorize)
    assert check_csv(b"id,name\n")["leaves"][0]["checked"] is False
    assert authorize.call_count == 2


@pytest.mark.parametrize(
    "content,columns,checked,holds",
    [
        (b"\xef\xbb\xbfid,name\r\n", ["id", "name"], True, True),
        (b'"last,name","line\nbreak"\n', ["last,name", "line\nbreak"], True, True),
        (b"id,name,name\n", ["id"], True, False),
        (b"", ["id"], True, False),
        (b"id,name\n" + b"x" * 60_000, ["id", "name"], True, True),
        (b'"' + b"x" * 50_001, ["id"], False, False),
        (b'"id"x,name\n' + b"x" * 60_000, ["id"], True, False),
    ],
    ids=["bom", "multiline", "duplicate", "empty", "large-body", "oversized-header", "malformed-header-large-body"],
)
def test_remote_csv_uses_real_bounded_transport(tmp_path, monkeypatch, content, columns, checked, holds):
    import shlex
    import subprocess
    import sys

    if sys.platform != "linux":
        pytest.skip("Requires Linux sandbox command tools")
    (tmp_path / "report.csv").write_bytes(content)

    class ShellSandbox:
        def execute_command(self, command, **kwargs):
            assert kwargs["env"]
            args = shlex.split(command)
            prefix = "/mnt/user-data/workspace"
            args = [str(tmp_path) + arg[len(prefix) :] if arg == prefix or arg.startswith(prefix + "/") else arg for arg in args]
            return subprocess.run(args, capture_output=True, text=True, check=True, timeout=15).stdout

        def read_file(self, *args, **kwargs):
            pytest.fail("CSV acceptance must not fall back to unbounded reads")

    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: ShellSandbox())
    verdict = checks.check_acceptance_criteria(
        [f"file:report.csv csv-columns:{json.dumps(columns)}"],
        runtime=SimpleNamespace(state=None),
        thread_data={"workspace_path": str(tmp_path)},
    )
    leaf = verdict["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (checked, holds)


def test_header_budget_counts_utf8_bytes(check_csv):
    verdict = check_csv(("id,name," + "\u4e2d" * 16_665 + "\n").encode())
    assert verdict["leaves"][0]["checked"] is False


def test_header_without_newline_at_exact_cap_holds(check_csv):
    assert check_csv(b"id,name," + b"x" * (50_000 - 8))["all_hold"] is True


def test_required_columns_allow_reordering(check_csv):
    assert check_csv(b"extra,name,id\n")["all_hold"] is True


@pytest.mark.parametrize("parse_seconds,holds", [(0, True), (6, False)])
def test_remote_read_latency_does_not_consume_parser_deadline(monkeypatch, tmp_path, parse_seconds, holds, parser_clock):
    import base64

    sandbox = Mock()

    def delayed_read(*args, **kwargs):
        parser_clock.return_value = 6
        return "JSON\n" + base64.b64encode(b"id,name\n\n000").decode() + "\nEND\n"

    sandbox.execute_command.side_effect = delayed_read
    monkeypatch.setattr("deerflow.sandbox.tools.ensure_sandbox_initialized", lambda runtime: sandbox)
    reader = checks.csv.reader

    def delayed_parse(*args, **kwargs):
        header = next(reader(*args, **kwargs))
        parser_clock.return_value += parse_seconds
        return iter([header])

    monkeypatch.setattr(checks.csv, "reader", delayed_parse)
    verdict = checks.check_acceptance_criteria(
        ['file:report.csv csv-columns:["id","name"]'],
        runtime=SimpleNamespace(state=None),
        thread_data={"workspace_path": str(tmp_path)},
        size_prober=lambda *args: 8,
    )
    leaf = verdict["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (holds, holds)
    if not holds:
        assert leaf["detail"] == "CSV header deadline exceeded"
    command = sandbox.execute_command.call_args
    assert command.kwargs["timeout"] == 10
    assert "/usr/bin/timeout 5" in command.args[0]
    sandbox.read_file.assert_not_called()


@pytest.mark.parametrize("columns", [["z", "id", "a"], ['a"b', "line\nbreak", " id "]], ids=["ordered", "escaped"])
def test_missing_columns_detail_names_exact_columns(check_csv, columns):
    leaf = check_csv(b"id,name\n", columns)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)
    missing = sorted(set(columns) - {"id", "name"})
    assert leaf["detail"] == f"CSV header is missing required columns: {json.dumps(missing)}"


def test_missing_columns_detail_remains_bounded(check_csv):
    leaf = check_csv(b"id,name\n", ["a" * 100, "b" * 100])["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (True, False)
    assert len(leaf["detail"]) == 160
    assert leaf["detail"].endswith("...")


@pytest.mark.parametrize("suffix", [b"\n", b"", b"\n" + b"1" * 60_000], ids=["complete", "eof", "large-body"])
def test_over_budget_header_detail_is_distinct(check_csv, suffix):
    content = b"id,name," + b"x" * (50_001 - 8 - (1 if suffix.startswith(b"\n") else 0)) + suffix
    leaf = check_csv(content)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)
    assert leaf["detail"] == "CSV header exceeds the 50000-byte read budget"


def test_truncated_header_detail_remains_incomplete(check_csv):
    leaf = check_csv(b"id,name," + b"x" * 60_000)["leaves"][0]
    assert (leaf["checked"], leaf["holds"]) == (False, False)
    assert leaf["detail"] == "CSV header incomplete within the read cap"
