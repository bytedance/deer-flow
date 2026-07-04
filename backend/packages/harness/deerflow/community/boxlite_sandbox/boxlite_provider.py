"""``BoxliteSandboxProvider`` — DeerFlow :class:`SandboxProvider` for BoxLite.

Scaffold / RFC: https://github.com/bytedance/deer-flow/issues/3936.

Config is read off :class:`SandboxConfig` (``extra="allow"``), so BoxLite keys
may appear under ``sandbox:`` in ``config.yaml`` even though they are not
declared on the model — see this package's ``__init__`` docstring for the full
set. The first pass creates one micro-VM per ``(user, thread)`` and reuses it
within the process; warm pooling, idle reaping, mount syncing and
remote/provisioner modes are intentionally out of scope here.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import threading
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, TypeVar

from deerflow.config import get_app_config
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .boxlite_sandbox import BoxliteSandbox

if TYPE_CHECKING:
    from boxlite import SimpleBox

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_IMAGE = "python:3.12-slim"


def _import_simplebox() -> type[SimpleBox]:
    """Import BoxLite's async ``SimpleBox`` lazily.

    Kept out of module import so the harness (and every other provider) installs
    without BoxLite; the dependency is only needed once this provider is actually
    selected.
    """
    try:
        from boxlite import SimpleBox
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("BoxliteSandboxProvider requires the 'boxlite' package. Install it with: pip install boxlite.") from e
    return SimpleBox


class _EventLoopThread:
    """A private asyncio event loop running on a dedicated daemon thread.

    BoxLite is async-native and its box handles are loop-affine, while DeerFlow's
    ``Sandbox`` contract is synchronous and may be invoked from arbitrary
    ``asyncio.to_thread`` workers. Owning one loop here and marshalling every
    coroutine onto it via ``run_coroutine_threadsafe`` gives a stable, thread-safe
    bridge without BoxLite's greenlet sync facade (which refuses to run inside an
    async context and is thread-affine).
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="boxlite-loop", daemon=True)
        self._thread.start()

    def run(self, coro: Awaitable[T], *, timeout: float | None = None) -> T:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        if not self._loop.is_running():
            self._loop.close()


class BoxliteSandboxProvider(SandboxProvider):
    """Run each DeerFlow sandbox as a BoxLite micro-VM."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sandboxes: dict[str, BoxliteSandbox] = {}
        self._thread_sandboxes: dict[tuple[str, str], str] = {}
        self._shutdown_called = False
        self._config = self._load_config()
        self._loop = _EventLoopThread()
        atexit.register(self.shutdown)

    def _load_config(self) -> dict[str, Any]:
        sandbox_config = get_app_config().sandbox

        def _opt(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        return {
            "image": _opt("image") or DEFAULT_IMAGE,
            "memory_mib": _opt("memory_mib"),
            "cpus": _opt("cpus"),
            "environment": self._resolve_env_vars(_opt("environment") or {}),
        }

    @staticmethod
    def _resolve_env_vars(env_config: dict[str, str]) -> dict[str, str]:
        resolved: dict[str, str] = {}
        for key, value in env_config.items():
            if isinstance(value, str) and value.startswith("$"):
                resolved[key] = os.environ.get(value[1:], "")
            else:
                resolved[key] = "" if value is None else str(value)
        return resolved

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        if thread_id is not None:
            key = self._thread_key(thread_id, user_id)
            with self._lock:
                existing = self._thread_sandboxes.get(key)
                if existing is not None and existing in self._sandboxes:
                    return existing

        sandbox = self._create_sandbox()

        with self._lock:
            self._sandboxes[sandbox.id] = sandbox
            if thread_id is not None:
                self._thread_sandboxes[self._thread_key(thread_id, user_id)] = sandbox.id
        return sandbox.id

    def _create_sandbox(self) -> BoxliteSandbox:
        simplebox_cls = _import_simplebox()

        async def _make() -> SimpleBox:
            box = simplebox_cls(
                image=self._config["image"],
                memory_mib=self._config["memory_mib"],
                cpus=self._config["cpus"],
            )
            await box.start()
            return box

        box = self._loop.run(_make())
        logger.info("Created BoxLite sandbox %s (image=%s)", box.id, self._config["image"])
        return BoxliteSandbox(
            box.id,
            box,
            self._loop.run,
            default_env=self._config["environment"],
        )

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._sandboxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            sandbox = self._sandboxes.pop(sandbox_id, None)
            for key in [k for k, sid in self._thread_sandboxes.items() if sid == sandbox_id]:
                self._thread_sandboxes.pop(key, None)
        if sandbox is not None:
            sandbox.close()

    def reset(self) -> None:
        with self._lock:
            self._sandboxes.clear()
            self._thread_sandboxes.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            active = list(self._sandboxes.values())
            self._sandboxes.clear()
            self._thread_sandboxes.clear()

        for sandbox in active:
            try:
                sandbox.close()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Error closing BoxLite sandbox %s during shutdown: %s", sandbox.id, e)
        self._loop.close()
