from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from pathlib import Path

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
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
        from deerflow.utils.file_io import run_file_io
        from langchain.tools import tool
        from langchain_core.tools import StructuredTool

        @tool
        async def async_tool(value: int) -> str:
            return str(value)

        async def handler(model):
            await asyncio.to_thread(str, "x")
            await run_file_io(str, "y")
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
    assert "ASYNC_FILE_IO_OFFLOAD" in categories
    assert "SYNC_INVOKE_IN_ASYNC" in categories
    assert "BLOCKING_CALL_IN_ASYNC" in categories
    assert "SYNC_ASYNC_BRIDGE" in categories
    assert "THREAD_POOL" in categories
    assert "EXECUTOR_SUBMIT" in categories
    assert "RAW_THREAD" in categories
    assert "ASYNC_ONLY_TOOL_FACTORY" in categories


def test_scan_file_classifies_default_dedicated_anyio_and_loop_boundaries(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import asyncio as aio
        import anyio
        from concurrent.futures import ThreadPoolExecutor as Pool
        from langchain_core.runnables import run_in_executor as dispatch
        from starlette.concurrency import run_in_threadpool as starlette_worker

        async def offload():
            loop = aio.get_running_loop()
            pool = Pool(max_workers=2)
            await aio.to_thread(str, "direct")
            await loop.run_in_executor(None, str, "stdlib-default")
            await aio.get_event_loop().run_in_executor(None, str, "chained-default")
            await dispatch(None, str, "langchain-default")
            await loop.run_in_executor(pool, str, "dedicated")
            await anyio.to_thread.run_sync(str, "anyio")
            await starlette_worker(str, "starlette")
            loop.set_default_executor(pool)
            pool.submit(str, "submitted")
            other = aio.new_event_loop()
            other.run_until_complete(aio.sleep(0))
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    by_category: dict[str, list[detector.BoundaryFinding]] = {}
    for finding in findings:
        by_category.setdefault(finding.category, []).append(finding)

    assert len(by_category["ASYNC_THREAD_OFFLOAD"]) == 1
    assert len(by_category["RUN_IN_DEFAULT_EXECUTOR"]) == 3
    assert len(by_category["RUN_IN_DEDICATED_EXECUTOR"]) == 1
    assert len(by_category["ANYIO_WORKER_THREAD"]) == 2
    assert len(by_category["SET_DEFAULT_EXECUTOR"]) == 1
    assert len(by_category["EXECUTOR_SUBMIT"]) == 1
    assert len(by_category["NEW_EVENT_LOOP"]) == 1
    assert {finding.boundary_kind for finding in by_category["RUN_IN_DEFAULT_EXECUTOR"]} == {detector.ASYNCIO_DEFAULT_EXECUTOR}
    assert {finding.boundary_kind for finding in by_category["ANYIO_WORKER_THREAD"]} == {detector.ANYIO_WORKER_THREAD}
    assert by_category["RUN_IN_DEDICATED_EXECUTOR"][0].boundary_kind == detector.DEDICATED_EXECUTOR
    assert by_category["NEW_EVENT_LOOP"][0].boundary_kind == detector.SEPARATE_EVENT_LOOP


def test_scan_file_discovers_same_module_thread_helper_wrappers(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from asyncio import to_thread as offload

        async def _worker(func, *args):
            return await offload(func, *args)

        async def caller():
            return await _worker(str, "wrapped")
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    helper = next(finding for finding in findings if finding.category == "THREAD_HELPER_CALL")

    assert helper.function == "caller"
    assert helper.symbol == "_worker"
    assert helper.boundary_kind == detector.ASYNCIO_DEFAULT_EXECUTOR


def test_scan_file_classifies_dedicated_executor_helper_wrappers(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import asyncio
        from concurrent.futures import ThreadPoolExecutor as Pool

        pool = Pool(max_workers=1)

        async def _worker(func, *args):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(pool, func, *args)

        async def caller():
            return await _worker(str, "wrapped")
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    helper = next(finding for finding in findings if finding.category == "THREAD_HELPER_CALL")

    assert helper.function == "caller"
    assert helper.symbol == "_worker"
    assert helper.boundary_kind == detector.DEDICATED_EXECUTOR


def test_scan_file_identifies_sync_langchain_tool_fallbacks(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain_core.tools import BaseTool, StructuredTool, tool

        @tool
        def sync_tool(value: str) -> str:
            return value

        class SyncOnlyTool(BaseTool):
            def _run(self, value: str) -> str:
                return value

        def factory():
            return StructuredTool.from_function(
                func=sync_tool,
                name="factory_tool",
                description="sync only",
            )
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    fallback_categories = {finding.category: finding.boundary_kind for finding in findings if finding.category in {"SYNC_TOOL_DEFINITION", "SYNC_TOOL_CLASS_FALLBACK", "SYNC_ONLY_TOOL_FACTORY"}}

    assert fallback_categories == {
        "SYNC_TOOL_DEFINITION": detector.ASYNCIO_DEFAULT_EXECUTOR,
        "SYNC_TOOL_CLASS_FALLBACK": detector.ASYNCIO_DEFAULT_EXECUTOR,
        "SYNC_ONLY_TOOL_FACTORY": detector.ASYNCIO_DEFAULT_EXECUTOR,
    }


def test_scan_file_identifies_base_chat_model_executor_fallbacks(tmp_path):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        from langchain_core.language_models.chat_models import BaseChatModel as ChatBase

        class SyncModel(ChatBase):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                raise NotImplementedError

        class AsyncModel(ChatBase):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                raise NotImplementedError

            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                raise NotImplementedError

            async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
                if False:
                    yield
        """,
    )

    findings = detector.scan_file(source_file, repo_root=tmp_path)
    model_fallbacks = [finding for finding in findings if finding.category in {"MODEL_AGENERATE_FALLBACK", "MODEL_ASTREAM_FALLBACK"}]

    assert [(finding.function, finding.category) for finding in model_fallbacks] == [
        ("SyncModel", "MODEL_AGENERATE_FALLBACK"),
        ("SyncModel", "MODEL_ASTREAM_FALLBACK"),
    ]
    assert {finding.boundary_kind for finding in model_fallbacks} == {detector.ASYNCIO_DEFAULT_EXECUTOR}


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
    categories = {finding["category"] for finding in payload["static_findings"]}
    assert categories == {"SYNC_INVOKE_IN_ASYNC"}
    assert payload["schema_version"] == 1
    assert payload["summary"]["static_findings"] == 1
    assert payload["runtime"] is None


def test_summary_output_is_concise_and_grouped_by_boundary_kind(tmp_path, capsys):
    source_file = _write_python(
        tmp_path / "sample.py",
        """
        import asyncio
        import anyio

        async def handler():
            await asyncio.to_thread(str, "x")
            await anyio.to_thread.run_sync(str, "y")
        """,
    )

    exit_code = detector.main(["--format", "summary", str(source_file)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Thread-boundary inventory: 2 static findings" in output
    assert "asyncio_default_executor: 1" in output
    assert "anyio_worker_thread: 1" in output
    assert "code:" not in output


def _sync_tool(value: str) -> str:
    return value


async def _async_tool(value: str) -> str:
    return value


class _SyncFallbackModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "sync-fallback"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])


class _NativeAsyncModel(_SyncFallbackModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return self._generate(messages, stop=stop, run_manager=None, **kwargs)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        if False:
            yield


def test_runtime_inventory_identifies_tool_and_model_fallbacks_without_invocation():
    sync_tool = StructuredTool.from_function(
        func=_sync_tool,
        name="sync_tool",
        description="sync",
    )
    async_tool = StructuredTool.from_function(
        coroutine=_async_tool,
        name="async_tool",
        description="async",
    )

    inventory = detector.inspect_runtime_components(
        tools=[sync_tool, async_tool],
        models=[("sync-model", _SyncFallbackModel), ("async-model", _NativeAsyncModel)],
    )

    assert [(tool.name, tool.async_requires_default_executor) for tool in inventory.tools] == [
        ("sync_tool", True),
        ("async_tool", False),
    ]
    assert inventory.tools[0].synchronous_function.endswith("._sync_tool")
    assert inventory.tools[0].async_coroutine is None
    assert inventory.tools[1].async_coroutine.endswith("._async_tool")
    assert [(model.name, model.agenerate_overridden, model.astream_overridden) for model in inventory.models] == [
        ("sync-model", False, False),
        ("async-model", True, True),
    ]
    assert inventory.models[0].inherits_base_chat_model_executor_fallback is True
    assert inventory.models[1].inherits_base_chat_model_executor_fallback is False


@dataclass
class _ConfiguredTool:
    name: str
    use: str


@dataclass
class _ConfiguredModel:
    name: str
    use: str


@dataclass
class _ConfiguredComponents:
    tools: list[_ConfiguredTool]
    models: list[_ConfiguredModel]


def test_configured_runtime_inventory_resolves_symbols_but_never_invokes_them():
    calls: list[tuple[str, str]] = []
    sync_tool = StructuredTool.from_function(
        func=_sync_tool,
        name="resolved_tool",
        description="sync",
    )

    def resolve_tool(path, expected_type):
        calls.append(("tool", path))
        return sync_tool

    def resolve_model(path, base_class):
        calls.append(("model", path))
        return _SyncFallbackModel

    config = _ConfiguredComponents(
        tools=[_ConfiguredTool(name="configured-tool", use="package.tools:tool")],
        models=[_ConfiguredModel(name="configured-model", use="package.models:Model")],
    )

    inventory = detector.inspect_configured_components(
        config,
        resolve_tool=resolve_tool,
        resolve_model=resolve_model,
    )

    assert calls == [
        ("tool", "package.tools:tool"),
        ("model", "package.models:Model"),
    ]
    assert inventory.tools[0].configured_name == "configured-tool"
    assert inventory.models[0].name == "configured-model"
    assert inventory.unresolved == []


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
