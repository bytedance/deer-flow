"""``BoxliteSandbox`` — DeerFlow :class:`Sandbox` backed by a BoxLite micro-VM.

DeerFlow's ``Sandbox`` contract is synchronous; BoxLite's SDK is async-native and
its box handles are event-loop-affine. The provider (:mod:`.boxlite_provider`)
owns a single private asyncio loop on a dedicated daemon thread and injects a
``run`` callable here that marshals each coroutine onto that loop via
``run_coroutine_threadsafe``. Every operation therefore runs on the one loop the
box was started on, and stays safe no matter which ``asyncio.to_thread`` worker
DeerFlow invokes us from.

Scaffold status: only :meth:`execute_command` is implemented. See
https://github.com/bytedance/deer-flow/issues/3936.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, TypeVar

from deerflow.sandbox.sandbox import Sandbox

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from boxlite import SimpleBox

    from deerflow.sandbox.search import GrepMatch

logger = logging.getLogger(__name__)

T = TypeVar("T")

_NOT_IMPLEMENTED = (
    "BoxliteSandbox.{method}() is not implemented yet. This provider is a scaffold for approach review — only execute_command is wired. Track or claim the file operations at https://github.com/bytedance/deer-flow/issues/3936."
)


class BoxliteSandbox(Sandbox):
    """Adapter that delegates to a running BoxLite ``SimpleBox``.

    Args:
        id: DeerFlow-side sandbox id (the BoxLite box id).
        box: A started async ``SimpleBox``. The provider owns its lifecycle;
            this adapter stops it on :meth:`close`.
        run: Callable that runs a coroutine on the provider's private event loop
            and returns its result (blocking the caller thread).
        default_env: Static environment merged into every command, overridden by
            per-call ``env`` (request-scoped secrets).
    """

    def __init__(
        self,
        id: str,
        box: SimpleBox,
        run: Callable[[Awaitable[T]], T],
        *,
        default_env: dict[str, str] | None = None,
    ) -> None:
        super().__init__(id)
        self._box = box
        self._run = run
        self._default_env = dict(default_env or {})
        self._lock = threading.Lock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self._run(self._box.stop())
        except Exception as e:
            logger.warning("Error stopping BoxLite sandbox %s: %s", self.id, e)

    def execute_command(
        self,
        command: str,
        env: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> str:
        """Run ``command`` through a shell inside the box and return its output.

        DeerFlow passes a bash command *string*, whereas BoxLite's ``exec`` takes
        argv, so the command is handed to ``sh -lc`` (mirrors e2b's
        ``commands.run``). Per-call ``env`` is layered over the static config
        environment and scoped to this command only.
        """
        merged_env = {**self._default_env, **(env or {})} or None
        with self._lock:
            if self._closed:
                return "Error: sandbox has been closed"
            box = self._box
        try:
            result = self._run(box.exec("sh", "-lc", command, env=merged_env, timeout=timeout))
        except Exception as e:
            logger.error("Failed to execute command in BoxLite sandbox %s: %s", self.id, e)
            return f"Error: {e}"

        stdout = result.stdout or ""
        stderr = result.stderr or ""
        if stdout and stderr:
            output = f"{stdout}\n{stderr}"
        else:
            output = stdout or stderr
        if result.exit_code not in (0, None) and not output:
            output = f"Command exited with code {result.exit_code}"
        return output if output else "(no output)"

    # ── Not implemented yet (scaffold) ──────────────────────────────────
    # Planned: map DeerFlow's ``/mnt/user-data`` virtual prefix into the box and
    # implement these via exec (cat / tee / base64) plus the shared helpers in
    # ``deerflow.sandbox.search``, mirroring ``community/e2b_sandbox``. The
    # traversal guards and prefix contract carry over unchanged. See #3936.

    def read_file(self, path: str) -> str:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="read_file"))

    def download_file(self, path: str) -> bytes:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="download_file"))

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="list_dir"))

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="write_file"))

    def glob(
        self,
        path: str,
        pattern: str,
        *,
        include_dirs: bool = False,
        max_results: int = 200,
    ) -> tuple[list[str], bool]:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="glob"))

    def grep(
        self,
        path: str,
        pattern: str,
        *,
        glob: str | None = None,
        literal: bool = False,
        case_sensitive: bool = False,
        max_results: int = 100,
    ) -> tuple[list[GrepMatch], bool]:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="grep"))

    def update_file(self, path: str, content: bytes) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED.format(method="update_file"))
