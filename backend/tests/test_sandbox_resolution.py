"""A declared sandbox is resolved before state and before the provider."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langgraph.runtime import Runtime
from langgraph.types import Overwrite

from deerflow.sandbox import tools as sandbox_tools
from deerflow.sandbox.middleware import SandboxMiddleware
from deerflow.sandbox.resolution import resolve_declared_sandbox, set_sandbox_resolver
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider, reset_sandbox_provider, set_sandbox_provider
from deerflow.sandbox.search import GrepMatch


class _Declared(Sandbox):
    def execute_command(self, command: str, env: dict[str, str] | None = None, timeout: float | None = None) -> str:
        return "OK"

    def read_file(self, path: str, start_line: int | None = None, end_line: int | None = None) -> str:
        return "content"

    def download_file(self, path: str) -> bytes:
        return b"content"

    def list_dir(self, path: str, max_depth: int = 2) -> list[str]:
        return []

    def write_file(self, path: str, content: str, append: bool = False) -> None:
        return None

    def glob(self, path: str, pattern: str, *, include_dirs: bool = False, max_results: int = 200) -> tuple[list[str], bool]:
        return [], False

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
        return [], False

    def update_file(self, path: str, content: bytes) -> None:
        return None


class _Provider(SandboxProvider):
    def __init__(self) -> None:
        self.acquired: list[str | None] = []
        self.released: list[str] = []
        self.sandbox = _Declared("ordinary-sandbox")

    def acquire(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        del user_id
        self.acquired.append(thread_id)
        return "ordinary-sandbox"

    async def acquire_async(self, thread_id: str | None = None, *, user_id: str | None = None) -> str:
        return self.acquire(thread_id, user_id=user_id)

    def get(self, sandbox_id: str) -> Sandbox | None:
        return self.sandbox if sandbox_id == "ordinary-sandbox" else None

    def release(self, sandbox_id: str) -> None:
        self.released.append(sandbox_id)


@pytest.fixture
def declared():
    sandbox = _Declared("declared-sandbox")
    set_sandbox_resolver(lambda: sandbox)
    try:
        yield sandbox
    finally:
        set_sandbox_resolver(None)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch):
    provider = _Provider()
    set_sandbox_provider(provider)
    monkeypatch.setattr(sandbox_tools, "get_sandbox_provider", lambda: provider)
    try:
        yield provider
    finally:
        reset_sandbox_provider()


def _runtime() -> SimpleNamespace:
    return SimpleNamespace(state={"sandbox": None}, context={"thread_id": "thread-1", "user_id": "user-1"}, config=None)


def test_nothing_is_declared_by_default() -> None:
    assert resolve_declared_sandbox() is None


def test_tools_resolve_the_declared_sandbox_before_state_or_provider(declared, provider) -> None:
    runtime = _runtime()

    assert sandbox_tools.ensure_sandbox_initialized(runtime) is declared
    assert sandbox_tools.sandbox_from_runtime(runtime) is declared
    assert provider.acquired == []


@pytest.mark.asyncio
async def test_async_tools_resolve_the_declared_sandbox(declared, provider) -> None:
    assert await sandbox_tools.ensure_sandbox_initialized_async(_runtime()) is declared
    assert provider.acquired == []


def test_a_resolver_answering_none_leaves_the_ordinary_path_alone(provider) -> None:
    set_sandbox_resolver(lambda: None)
    try:
        assert sandbox_tools.ensure_sandbox_initialized(_runtime()) is provider.sandbox
    finally:
        set_sandbox_resolver(None)
    assert provider.acquired == ["thread-1"]


def test_middleware_binds_the_declared_sandbox_and_never_acquires_or_releases(declared, provider) -> None:
    middleware = SandboxMiddleware(lazy_init=False)
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "user-1"})

    assert middleware.before_agent({}, runtime) == {"sandbox": {"sandbox_id": "declared-sandbox"}}
    assert middleware.before_agent({"sandbox": {"sandbox_id": "declared-sandbox"}}, runtime) is None
    replaced = middleware.before_agent({"sandbox": {"sandbox_id": "stale"}}, runtime)
    assert isinstance(replaced["sandbox"], Overwrite)
    assert middleware.after_agent({"sandbox": {"sandbox_id": "declared-sandbox"}}, runtime) is None
    assert provider.acquired == []
    assert provider.released == []


@pytest.mark.asyncio
async def test_async_middleware_binds_the_declared_sandbox(declared, provider) -> None:
    middleware = SandboxMiddleware(lazy_init=False)
    runtime = Runtime(context={"thread_id": "thread-1", "user_id": "user-1"})

    assert await middleware.abefore_agent({}, runtime) == {"sandbox": {"sandbox_id": "declared-sandbox"}}
    assert await middleware.aafter_agent({"sandbox": {"sandbox_id": "declared-sandbox"}}, runtime) is None
    assert provider.acquired == []
    assert provider.released == []
