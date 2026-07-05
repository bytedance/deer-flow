"""``BoxliteProvider`` — DeerFlow :class:`SandboxProvider` backed by BoxLite.

Integrates `BoxLite <https://github.com/boxlite-ai/boxlite>`_ — a daemonless,
OCI-native micro-VM runtime — as a DeerFlow sandbox backend. See
https://github.com/bytedance/deer-flow/issues/3936.

Config is read off :class:`SandboxConfig` (``extra="allow"``), so BoxLite keys
may appear under ``sandbox:`` in ``config.yaml`` even though they are not declared
on the model — see this package's ``__init__`` docstring for the full set. The
provider creates one micro-VM per ``(user, thread)`` and reuses it within the
process; warm pooling, idle reaping and remote modes are out of scope for now.
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import threading
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, TypeVar

from deerflow.config import get_app_config
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.constants import DEFAULT_SKILLS_CONTAINER_PATH
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

from .box import BoxliteBox

if TYPE_CHECKING:
    from boxlite import SimpleBox

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_IMAGE = "python:3.12-slim"
# DeerFlow's virtual prefixes, materialised on the box rootfs at start so the
# Sandbox file APIs (which address /mnt/user-data/...) resolve natively.
_VIRTUAL_DIRS = (
    f"{VIRTUAL_PATH_PREFIX}/workspace",
    f"{VIRTUAL_PATH_PREFIX}/uploads",
    f"{VIRTUAL_PATH_PREFIX}/outputs",
    DEFAULT_SKILLS_CONTAINER_PATH,
)


def _import_simplebox() -> type[SimpleBox]:
    """Import BoxLite's async ``SimpleBox`` lazily.

    Kept out of module import so the harness (and every other provider) installs
    without BoxLite; the dependency is only needed once this provider is selected.
    """
    try:
        from boxlite import SimpleBox
    except ImportError as e:  # pragma: no cover - depends on the optional dependency
        raise ImportError("BoxliteProvider requires the 'boxlite' package. Install it with: pip install boxlite.") from e
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


class BoxliteProvider(SandboxProvider):
    """Run each DeerFlow sandbox as a BoxLite micro-VM."""

    uses_thread_data_mounts = False
    needs_upload_permission_adjustment = True

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._boxes: dict[str, BoxliteBox] = {}
        self._thread_boxes: dict[tuple[str, str], str] = {}
        self._shutdown_called = False
        self._config = self._load_config()
        self._loop = _EventLoopThread()
        atexit.register(self.shutdown)

    def _load_config(self) -> dict[str, Any]:
        sandbox_config = get_app_config().sandbox

        def _opt(name: str, default: Any = None) -> Any:
            return getattr(sandbox_config, name, default)

        # $VARS in config.yaml are already resolved by AppConfig.resolve_env_variables
        # (which raises on a missing var), so the environment dict is used as-is.
        return {
            "image": _opt("image") or DEFAULT_IMAGE,
            "memory_mib": _opt("memory_mib"),
            "cpus": _opt("cpus"),
            "environment": dict(_opt("environment") or {}),
        }

    @staticmethod
    def _thread_key(thread_id: str, user_id: str | None) -> tuple[str, str]:
        return (user_id or "", thread_id)

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        if thread_id is not None:
            key = self._thread_key(thread_id, user_id)
            with self._lock:
                existing = self._thread_boxes.get(key)
                if existing is not None and existing in self._boxes:
                    return existing

        box = self._create_box()

        with self._lock:
            self._boxes[box.id] = box
            if thread_id is not None:
                self._thread_boxes[self._thread_key(thread_id, user_id)] = box.id
        return box.id

    def _create_box(self) -> BoxliteBox:
        simplebox_cls = _import_simplebox()
        mkdir_cmd = "mkdir -p " + " ".join(_VIRTUAL_DIRS)

        async def _make() -> SimpleBox:
            box = simplebox_cls(
                image=self._config["image"],
                memory_mib=self._config["memory_mib"],
                cpus=self._config["cpus"],
            )
            await box.start()
            # Materialise DeerFlow's virtual prefixes so file ops resolve natively.
            await box.exec("sh", "-lc", mkdir_cmd)
            return box

        box = self._loop.run(_make())
        logger.info("Created BoxLite box %s (image=%s)", box.id, self._config["image"])
        return BoxliteBox(box.id, box, self._loop.run, default_env=self._config["environment"])

    def get(self, sandbox_id: str) -> Sandbox | None:
        with self._lock:
            return self._boxes.get(sandbox_id)

    def release(self, sandbox_id: str) -> None:
        with self._lock:
            box = self._boxes.pop(sandbox_id, None)
            for key in [k for k, sid in self._thread_boxes.items() if sid == sandbox_id]:
                self._thread_boxes.pop(key, None)
        if box is not None:
            box.close()

    def reset(self) -> None:
        with self._lock:
            self._boxes.clear()
            self._thread_boxes.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown_called:
                return
            self._shutdown_called = True
            active = list(self._boxes.values())
            self._boxes.clear()
            self._thread_boxes.clear()

        for box in active:
            try:
                box.close()
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Error closing BoxLite box %s during shutdown: %s", box.id, e)
        self._loop.close()
