"""Optional operator browser affinity/control provider contract.

This is a trusted Gateway startup hook, not a public Python extension contract.
Providers must route authenticated native browser operations to the actual native
session owner and preserve the native routes' security checks.
"""

from __future__ import annotations

import importlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class BrowserControlProvider(Protocol):
    def validate_startup(self, config): ...
    async def bind(self, app, native_host): ...
    async def navigate(self, request, thread_id, url): ...
    async def stream(self, websocket, thread_id, user_id): ...
    async def session_scope(self, thread_id, user_id): ...
    async def execution_scope(self, native): ...
    async def stop(self): ...


@dataclass(frozen=True)
class BrowserControlSnapshot:
    native_json: str
    provider: BrowserControlProvider | None = None

    @property
    def native_config(self) -> dict:
        # Fresh copies prevent a host mutating the immutable startup snapshot.
        return json.loads(self.native_json)


def load_browser_control_snapshot(config) -> BrowserControlSnapshot | None:
    path = os.environ.get("ECS_NATIVE_CONFIG")
    if not path:
        return None
    native = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(native, dict):
        raise ValueError("Invalid native operator configuration")
    provider = None
    settings = native.get("browser_control")
    if settings is not None:
        if native.get("enabled") is not True or not isinstance(settings, dict):
            raise ValueError("Browser control requires enabled operator host")
        name = settings.get("provider")
        if not isinstance(name, str) or name.count(":") != 1:
            raise ValueError("Browser control requires explicit provider factory")
        module, factory = name.split(":")
        provider = getattr(importlib.import_module(module), factory)(native_config=native, settings=settings)
        if not isinstance(provider, BrowserControlProvider):
            raise ValueError("Browser control provider contract is incomplete")
        provider.validate_startup(config)
    return BrowserControlSnapshot(json.dumps(native, sort_keys=True), provider)


def has_browser_affinity(snapshot) -> bool:
    return isinstance(snapshot, BrowserControlSnapshot) and isinstance(snapshot.provider, BrowserControlProvider)


def get_browser_control(app):
    snapshot = getattr(app.state, "browser_control_snapshot", None)
    return snapshot.provider if has_browser_affinity(snapshot) else None
