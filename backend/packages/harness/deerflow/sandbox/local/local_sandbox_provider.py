from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

_singleton: LocalSandbox | None = None


class LocalSandboxProvider(SandboxProvider):
    def acquire(self, thread_id: str | None = None) -> str:
        global _singleton
        if _singleton is None:
            _singleton = LocalSandbox("local")
        return _singleton.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "local":
            if _singleton is None:
                self.acquire()
            return _singleton
        return None

    def release(self, sandbox_id: str) -> None:
        # LocalSandbox uses singleton pattern - no cleanup needed.
        # Note: This method is intentionally not called by SandboxMiddleware
        # to allow sandbox reuse across multiple turns in a thread.
        # For Docker-based providers (e.g., AioSandboxProvider), cleanup
        # happens at application shutdown via the shutdown() method.
        pass
