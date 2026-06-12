from __future__ import annotations

import json
import textwrap
from pathlib import Path

from support.detectors import blocking_io_static as detector


def _write_python(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def _payload(path: Path, repo_root: Path) -> list[dict[str, object]]:
    return [finding.to_dict() for finding in detector.scan_file(path, repo_root=repo_root)]


def test_scan_file_detects_direct_blocking_calls_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess
        import time
        import urllib.request
        from pathlib import Path

        async def handler(path: Path):
            time.sleep(1)
            subprocess.run(["echo", "ok"])
            path.read_text(encoding="utf-8")
            with open(path, encoding="utf-8") as handle:
                return urllib.request.urlopen(handle.read())
        """,
    )

    findings = _payload(source_file, tmp_path)
    categories = {finding["blocking_call"]["category"] for finding in findings}
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert categories == {
        "BLOCKING_FILE_IO",
        "BLOCKING_HTTP_IO",
        "BLOCKING_SLEEP",
        "BLOCKING_SUBPROCESS",
    }
    assert {"time.sleep", "subprocess.run", "path.read_text", "open", "urllib.request.urlopen"}.issubset(symbols)
    assert {finding["event_loop_exposure"] for finding in findings} == {"DIRECT_ASYNC"}


def test_scan_file_detects_blocking_calls_in_sync_helper_reached_from_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> bytes:
            return path.read_bytes()

        async def route(path: Path) -> bytes:
            return load_payload(path)
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "BLOCKING_FILE_IO"
    assert findings[0]["location"]["function"] == "load_payload"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"
    assert findings[0]["blocking_call"]["symbol"] == "path.read_bytes"


def test_scan_file_omits_sync_only_blocking_calls_from_default_results(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_detects_self_helper_reached_from_async_method(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class ArtifactRouter:
            def read_payload(self, path):
                return path.read_text(encoding="utf-8")

            async def get(self, path):
                return self.read_payload(path)
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "ArtifactRouter.read_payload"
    assert findings[0]["event_loop_exposure"] == "ASYNC_REACHABLE_SAME_FILE"


def test_json_output_uses_concise_review_record_schema(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess

        async def handler():
            subprocess.run(["echo", "ok"])
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {
            "priority": "HIGH",
            "location": {
                "path": str(source_file),
                "line": 4,
                "column": 5,
                "function": "handler",
            },
            "blocking_call": {
                "category": "BLOCKING_SUBPROCESS",
                "operation": "SUBPROCESS",
                "symbol": "subprocess.run",
            },
            "event_loop_exposure": "DIRECT_ASYNC",
            "reason": "SUBPROCESS is called directly inside an async function.",
            "code": 'subprocess.run(["echo", "ok"])',
        }
    ]
    assert "confidence" not in payload[0]
    assert "severity" not in payload[0]
    assert "event_loop_risk" not in payload[0]


def test_summary_output_writes_json_report(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import subprocess

        async def handler():
            subprocess.run(["echo", "ok"])
        """,
    )
    output_path = tmp_path / "reports" / "blocking-io.json"

    exit_code = detector.main(["--output", str(output_path), str(source_file)])

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "Static blocking IO event-loop risk findings: 1" in stdout
    assert "By category:" in stdout
    assert "BLOCKING_SUBPROCESS" in stdout
    assert "Full JSON report:" in stdout
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert [finding["blocking_call"]["category"] for finding in payload] == ["BLOCKING_SUBPROCESS"]


def test_json_output_ranks_operations_without_confidence_noise(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import shutil

        async def handler(path):
            path.exists()
            path.read_text()
            shutil.rmtree(path)
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    by_symbol = {finding["blocking_call"]["symbol"]: finding for finding in payload}
    assert by_symbol["path.exists"]["blocking_call"]["operation"] == "FILE_METADATA"
    assert by_symbol["path.exists"]["priority"] == "LOW"
    assert by_symbol["path.read_text"]["blocking_call"]["operation"] == "FILE_READ"
    assert by_symbol["path.read_text"]["priority"] == "MEDIUM"
    assert by_symbol["shutil.rmtree"]["blocking_call"]["operation"] == "FILE_TREE_DELETE"
    assert by_symbol["shutil.rmtree"]["priority"] == "HIGH"
    assert {finding["event_loop_exposure"] for finding in payload} == {"DIRECT_ASYNC"}
    assert all("confidence" not in finding for finding in payload)


def test_path_receiver_detection_uses_path_annotations(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        async def typed(path: Path):
            return path.read_text()

        async def constructed():
            return Path("payload.txt").read_text()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert {finding["blocking_call"]["symbol"] for finding in findings} == {"path.read_text", "pathlib.Path.read_text"}
    assert {finding["priority"] for finding in findings} == {"MEDIUM"}


def test_summary_groups_findings_by_priority_and_operation(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()

        async def handler(path: Path) -> str:
            path.exists()
            list(os.walk(path))
            return load_payload(path)
        """,
    )

    exit_code = detector.main([str(source_file)])

    assert exit_code == 0
    stdout = capsys.readouterr().out
    assert "By priority:" in stdout
    assert "HIGH" in stdout
    assert "MEDIUM" in stdout
    assert "By operation:" in stdout
    assert "FILE_ENUMERATION" in stdout
    assert "FILE_METADATA" in stdout
    assert "FILE_READ" in stdout
    assert "By event-loop exposure:" in stdout
    assert "DIRECT_ASYNC" in stdout
    assert "ASYNC_REACHABLE_SAME_FILE" in stdout


def test_source_code_snippet_is_truncated_for_json_output(tmp_path: Path) -> None:
    long_suffix = " + ".join('"chunk"' for _ in range(80))
    source_file = _write_python(
        tmp_path / "sample.py",
        f"""
        async def handler(path):
            return path.read_text() + {long_suffix}
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert len(findings[0]["code"]) <= 203
    assert findings[0]["code"].endswith("...")


def test_cli_default_filters_sync_only_inventory_items(tmp_path: Path, capsys) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from pathlib import Path

        def load_payload(path: Path) -> str:
            return path.read_text()
        """,
    )

    exit_code = detector.main(["--format", "json", str(source_file)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == []


def test_sync_only_agent_middleware_hook_gets_event_loop_exposure(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain.agents.middleware import AgentMiddleware
        from pathlib import Path

        class UploadsMiddleware(AgentMiddleware):
            def before_agent(self, state, runtime):
                return self._load(Path("uploads"))

            def _load(self, path: Path) -> str:
                return path.read_text()
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["location"]["function"] == "UploadsMiddleware._load"
    assert findings[0]["event_loop_exposure"] == "SYNC_AGENT_MIDDLEWARE_HOOK"
    assert "statically reachable from a sync AgentMiddleware hook" in findings[0]["reason"]


def test_sync_agent_middleware_hook_with_async_counterpart_is_not_reported(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain.agents.middleware import AgentMiddleware
        from pathlib import Path

        class UploadsMiddleware(AgentMiddleware):
            def before_agent(self, state, runtime):
                return Path("uploads").read_text()

            async def abefore_agent(self, state, runtime):
                return None
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_scan_file_detects_sync_httpx_client_methods_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import httpx

        async def search() -> str:
            with httpx.Client(timeout=30) as client:
                return client.post("https://example.invalid").text
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "BLOCKING_HTTP_IO"
    assert findings[0]["location"]["function"] == "search"
    assert findings[0]["event_loop_exposure"] == "DIRECT_ASYNC"
    assert findings[0]["blocking_call"]["symbol"] == "httpx.Client.post"


def test_scan_file_detects_chained_sync_http_client_methods_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import httpx
        import requests

        async def fetch() -> tuple[object, object]:
            return (
                httpx.Client().get("https://example.invalid"),
                requests.Session().post("https://example.invalid"),
            )
        """,
    )

    findings = _payload(source_file, tmp_path)
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert symbols == {"httpx.Client.get", "requests.Session.post"}
    assert {finding["blocking_call"]["category"] for finding in findings} == {"BLOCKING_HTTP_IO"}


def test_scan_file_detects_os_walk_and_path_resolve_in_async_code(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import os
        from pathlib import Path

        async def inspect_tree(path: Path) -> list[str]:
            root = path.resolve()
            return [name for _, _, names in os.walk(root) for name in names]
        """,
    )

    findings = _payload(source_file, tmp_path)
    symbols = {finding["blocking_call"]["symbol"] for finding in findings}

    assert symbols == {"path.resolve", "os.walk"}
    assert {finding["blocking_call"]["category"] for finding in findings} == {"BLOCKING_FILE_IO"}


def test_scan_file_does_not_treat_string_replace_as_file_io(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        def _path_variants(path: str) -> set[str]:
            return {path, path.replace("\\\\", "/"), path.replace("/", "\\\\")}

        async def normalize(text: str) -> str:
            return text.replace("a", "b")
        """,
    )

    assert detector.scan_file(source_file, repo_root=tmp_path) == []


def test_parse_errors_are_reported_as_findings(tmp_path: Path) -> None:
    source_file = _write_python(
        tmp_path / "broken.py",
        """
        async def broken(:
            pass
        """,
    )

    findings = _payload(source_file, tmp_path)

    assert len(findings) == 1
    assert findings[0]["blocking_call"]["category"] == "PARSE_ERROR"
    assert findings[0]["priority"] == "MEDIUM"
    assert f"{source_file.name}:1:18" in detector.format_text(detector.scan_file(source_file, repo_root=tmp_path))
