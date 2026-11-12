"""Recovered boxes exercise the installed optional SDK without starting a VM."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from deerflow.community.boxlite.provider import BoxliteProvider


@pytest.fixture
def sdk_runtime(monkeypatch):
    sdk = pytest.importorskip("boxlite", reason="Install deerflow-harness[boxlite] on a supported SDK platform")
    exec_signature = inspect.signature(sdk.Box.exec)
    list_signature = inspect.signature(sdk.Boxlite.list_info)
    get_signature = inspect.signature(sdk.Boxlite.get)
    stop_signature = inspect.signature(sdk.Box.stop)
    events = []
    commands = []

    class NativeExecution:
        def __init__(self, health_check, fail_wait):
            self.health_check = health_check
            self.fail_wait = fail_wait
            self.stderr_started = asyncio.Event()
            self.stdout_done = self.stderr_done = False

        def stdout(self):
            async def lines():
                yield b"ok\n" if self.health_check else b"output\n"
                # Reading stdout alone would block: both SDK output streams must be drained concurrently.
                await self.stderr_started.wait()
                self.stdout_done = True

            return lines()

        def stderr(self):
            async def lines():
                self.stderr_started.set()
                if not self.health_check:
                    yield "error\n"
                self.stderr_done = True

            return lines()

        async def wait(self):
            assert self.stdout_done and self.stderr_done
            if self.fail_wait:
                raise RuntimeError("execution wait failed")
            return SimpleNamespace(exit_code=0 if self.health_check else 7, error_message=None)

    class NativeBox:
        id = "recovered-native-box"

        async def __aenter__(self):
            return self

        async def exec(self, *args, **kwargs):
            # Bind against the installed native API rather than a permissive hand-written SDK signature.
            bound = exec_signature.bind(self, *args, **kwargs)
            bound.apply_defaults()
            commands.append(bound.arguments)
            events.append(("exec", asyncio.get_running_loop(), threading.get_ident()))
            health_check = bound.arguments["command"] == "sh" and bound.arguments["args"] == ["-lc", "echo ok"]
            return NativeExecution(health_check, bound.arguments["command"] == "wait-error")

        async def stop(self):
            stop_signature.bind(self)
            events.append(("stop", asyncio.get_running_loop(), threading.get_ident()))

    class NativeRuntime:
        existing = True

        async def list_info(self):
            list_signature.bind(self)
            events.append(("list", asyncio.get_running_loop(), threading.get_ident()))
            return [SimpleNamespace(name="deer-flow-boxlite-existing"), SimpleNamespace(name="foreign-box")]

        async def get(self, name):
            get_signature.bind(self, name)
            assert name == "deer-flow-boxlite-existing"
            events.append(("get", asyncio.get_running_loop(), threading.get_ident()))
            return native_box if self.existing else None

        async def create(self, *args, **kwargs):
            raise AssertionError("Recovery must never create a VM")

        async def get_or_create(self, *args, **kwargs):
            raise AssertionError("Recovery must use get, not get_or_create")

    native_box = NativeBox()
    runtime = NativeRuntime()

    class RuntimeFactory:
        @staticmethod
        def default():
            return runtime

    # Only the native runtime boundary is replaced. SimpleBox and the old SyncBox wrappers remain real SDK code.
    monkeypatch.setattr(sdk, "Boxlite", RuntimeFactory)
    monkeypatch.setattr(importlib.import_module("boxlite.boxlite"), "Boxlite", RuntimeFactory)
    monkeypatch.setattr(
        "deerflow.community.boxlite.provider.get_app_config",
        lambda: SimpleNamespace(sandbox=SimpleNamespace(idle_timeout=0, environment={"DEFAULT": "value"})),
    )
    return SimpleNamespace(sdk=sdk, runtime=runtime, box=native_box, events=events, commands=commands)


def test_recovered_box_reclaims_executes_and_stops_on_the_private_loop(sdk_runtime):
    provider = BoxliteProvider()
    sync_runtime = None
    try:
        adopted = provider._warm_pool["existing"][0]
        sync_runtime = getattr(adopted._box, "_runtime", None)
        assert provider._reclaim_warm_pool("existing", ("user", "thread")) == "existing"
        with ThreadPoolExecutor(max_workers=1) as worker:
            output = worker.submit(adopted.execute_command, "run-tool", {"CALL": "value"}, 3).result(timeout=5)
        assert "output\n" in output and "error\n" in output and "Exit Code: 7" in output

        options = {"env": {"KEY": "value"}, "user": "1000", "timeout": 2, "cwd": "/work"}
        result = provider._loop.run(adopted._box.exec("tool", "argument", **options), timeout=5)
        assert isinstance(result, sdk_runtime.sdk.ExecResult)
        assert (result.stdout, result.stderr, result.exit_code) == ("output\n", "error\n", 7)
        assert sdk_runtime.commands[-1] == {
            "self": sdk_runtime.box,
            "command": "tool",
            "args": ["argument"],
            "env": [("KEY", "value")],
            "tty": False,
            "user": "1000",
            "timeout_secs": 2,
            "cwd": "/work",
        }

        async def sdk_control():
            async def create(options, name=None):
                return sdk_runtime.box

            control = sdk_runtime.sdk.SimpleBox(image="python:3.12-slim", runtime=SimpleNamespace(create=create))
            await control.start()
            return await control.exec("tool", "argument", **options)

        assert result == provider._loop.run(sdk_control(), timeout=5)
        failed_wait = provider._loop.run(adopted._box.exec("wait-error"), timeout=5)
        assert (failed_wait.stdout, failed_wait.stderr, failed_wait.exit_code) == ("output\n", "error\n", -1)
        private_loop = provider._loop._loop
        private_thread = provider._loop._thread.ident
        provider.shutdown()
        assert sdk_runtime.events[-1][0] == "stop"
        assert all(loop is private_loop and thread == private_thread for _, loop, thread in sdk_runtime.events)
    finally:
        provider.shutdown()
        # Reap the original implementation's creator-thread-owned greenlet after a red regression.
        if sync_runtime is not None and getattr(sync_runtime, "_started", False):
            sync_runtime.stop()


def test_recovery_skips_a_box_removed_after_listing_without_creating_a_replacement(sdk_runtime):
    sdk_runtime.runtime.existing = False
    provider = BoxliteProvider()
    try:
        assert provider._warm_pool == {}
        assert [event[0] for event in sdk_runtime.events] == ["list", "get"]
    finally:
        provider.shutdown()
