import threading
import time

import deerflow.sandbox.sandbox_provider as sandbox_provider
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider


class SlowSandboxProvider(SandboxProvider):
    instances_created = 0
    instances_lock = threading.Lock()

    def __init__(self):
        time.sleep(0.05)
        with self.instances_lock:
            type(self).instances_created += 1

    def acquire(self, thread_id: str | None = None) -> str:
        return "sandbox-id"

    def get(self, sandbox_id: str) -> Sandbox | None:
        return None

    def release(self, sandbox_id: str) -> None:
        pass


class SandboxConfig:
    use = "SlowSandboxProvider"


class AppConfig:
    sandbox = SandboxConfig()


def test_get_sandbox_provider_initializes_singleton_once_under_concurrent_access(monkeypatch):
    sandbox_provider.reset_sandbox_provider()
    SlowSandboxProvider.instances_created = 0
    monkeypatch.setattr(sandbox_provider, "get_app_config", lambda: AppConfig())
    monkeypatch.setattr(sandbox_provider, "resolve_class", lambda *args: SlowSandboxProvider)

    providers: list[SandboxProvider] = []
    start = threading.Event()

    def get_provider() -> None:
        start.wait()
        providers.append(sandbox_provider.get_sandbox_provider())

    threads = [threading.Thread(target=get_provider) for _ in range(8)]
    for thread in threads:
        thread.start()

    start.set()

    for thread in threads:
        thread.join()

    assert len({id(provider) for provider in providers}) == 1
    assert SlowSandboxProvider.instances_created == 1
