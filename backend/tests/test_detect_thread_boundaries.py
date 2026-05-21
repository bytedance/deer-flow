from __future__ import annotations

import json
import textwrap
from pathlib import Path

from support.detectors import thread_boundaries as detector


def _write_python(path: Path, source: str) -> Path:
    path.write_text(textwrap.dedent(source).strip() + "\n", encoding="utf-8")
    return path


def test_scan_file_detects_async_thread_and_tool_boundaries(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import asyncio
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor
        from langchain.tools import tool
        from langchain_core.tools import StructuredTool

        @tool
        async def async_tool(value: int) -> str:
            return str(value)

        async def handler(model):
            await asyncio.to_thread(str, "x")
            model.invoke("blocking")
            time.sleep(1)

        def sync_entry():
            asyncio.run(handler(None))
            pool = ThreadPoolExecutor(max_workers=1)
            pool.submit(str, "x")
            threading.Thread(target=sync_entry).start()
            return StructuredTool.from_function(
                name="factory_tool",
                description="factory",
                coroutine=async_tool,
            )
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    categories = {finding.category for finding in findings}
    async_tool_finding = next(finding for finding in findings if finding.category == "ASYNC_TOOL_DEFINITION")

    assert "ASYNC_TOOL_DEFINITION" in categories
    assert async_tool_finding.function == "async_tool"
    assert async_tool_finding.async_context is True
    assert "ASYNC_THREAD_OFFLOAD" in categories
    assert "SYNC_INVOKE_IN_ASYNC" in categories
    assert "BLOCKING_CALL_IN_ASYNC" in categories
    assert "SYNC_ASYNC_BRIDGE" in categories
    assert "THREAD_POOL" in categories
    assert "EXECUTOR_SUBMIT" in categories
    assert "RAW_THREAD" in categories
    assert "ASYNC_ONLY_TOOL_FACTORY" in categories


def test_scan_file_ignores_unqualified_threads_and_generic_method_names(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        class Thread:
            pass

        class Timer:
            pass

        async def handler(form, runner):
            form.submit()
            runner.invoke("not a langchain model")

        def sync_entry(runner):
            Thread()
            Timer()
            runner.ainvoke("not a langchain model")
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    categories = {finding.category for finding in findings}

    assert "RAW_THREAD" not in categories
    assert "RAW_TIMER_THREAD" not in categories
    assert "EXECUTOR_SUBMIT" not in categories
    assert "SYNC_INVOKE_IN_ASYNC" not in categories
    assert "ASYNC_INVOKE_IN_SYNC" not in categories


def test_scan_file_uses_import_evidence_for_thread_and_executor_aliases(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from concurrent.futures import ThreadPoolExecutor as Pool
        from threading import Thread as WorkerThread, Timer

        def sync_entry():
            pool = Pool(max_workers=1)
            pool.submit(str, "x")
            WorkerThread(target=sync_entry).start()
            Timer(1, sync_entry).start()
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    categories = {finding.category for finding in findings}

    assert "THREAD_POOL" in categories
    assert "EXECUTOR_SUBMIT" in categories
    assert "RAW_THREAD" in categories
    assert "RAW_TIMER_THREAD" in categories


def test_scan_paths_ignores_virtualenv_like_directories(tmp_path):
    scanned_file = _write_python(
        tmp_path / "app.py",
        """
        import asyncio

        def main():
            return asyncio.run(asyncio.sleep(0))
        """,
    )
    ignored_dir = tmp_path / ".venv"
    ignored_dir.mkdir()
    _write_python(
        ignored_dir / "ignored.py",
        """
        import threading

        thread = threading.Thread(target=lambda: None)
        """,
    )

    findings = detector.scan_paths([tmp_path], repo_root=tmp_path)

    assert any(finding.path == scanned_file.name for finding in findings)
    assert all(".venv" not in finding.path for finding in findings)


def test_json_output_and_min_severity_filter(tmp_path, capsys):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import asyncio

        async def handler(model):
            await asyncio.to_thread(str, "x")
            model.invoke("blocking")
        """,
    )

    exit_code = detector.main(["--format", "json", "--min-severity", "WARN", str(source_file)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    categories = {finding["category"] for finding in payload}
    assert categories == {"SYNC_INVOKE_IN_ASYNC"}


def test_parse_errors_are_reported_as_findings(tmp_path):
    source_file = _write_python(
        tmp_path / "broken.py",
        """
        def broken(:
            pass
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)

    assert len(findings) == 1
    assert findings[0].category == "PARSE_ERROR"
    assert findings[0].severity == "WARN"
    assert findings[0].column == 11
    assert f"{source_file.name}:1:12" in detector.format_text(findings)
