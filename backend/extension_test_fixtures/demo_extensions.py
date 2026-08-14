"""Install functions used by the extension loader tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionRegistry, extension

INSTALLED: list[str] = []


class _Contributor:
    def __init__(self, tag: str) -> None:
        self.tag = tag


def install_ok(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    INSTALLED.append("ok")
    registry.middlewares(_Contributor("ok"))


@extension(api="0.1", name="stamped")
def install_stamped(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    INSTALLED.append("stamped")
    registry.task_lifecycle(_Contributor("stamped"))


@extension(api="99.0", name="future")
def install_future_api(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    INSTALLED.append("future")
    registry.middlewares(_Contributor("future"))


@extension(api="0.2", name="newer-minor")
def install_newer_minor_api(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Written against a newer 0.x minor than the host provides: before 1.0,
    minors carry no compatibility promise in either direction."""
    INSTALLED.append("newer-minor")
    registry.middlewares(_Contributor("newer-minor"))


def install_partial_then_raise(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register every contribution kind, then fail to exercise five-bucket rollback."""
    partial = _Contributor("partial")
    registry.middlewares(partial)
    registry.task_lifecycle(partial)
    registry.system_model_observer(partial)
    registry.service(partial)
    registry.routers((partial,))
    raise ValueError("boom")


def install_reads_config(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    INSTALLED.append(f"config:{config.get('mode')}")


def install_disabled(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Registers nothing when disabled — the zero-cost path."""
    if not config.get("enabled", False):
        return
    registry.middlewares(_Contributor("enabled"))


def install_shared_use(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Registers a middleware contributor; raises afterward if configured to.

    Two ExtensionSpecs may legitimately share the same `use` with different
    config (e.g. the same extension mounted twice with different settings).
    This exists to exercise that rollback must be positional, not keyed by
    `use` — a failing instance must not erase an earlier, successful
    instance's registrations just because they share a source string.
    """
    registry.middlewares(_Contributor(f"shared:{config.get('label', '')}"))
    if config.get("fail"):
        raise ValueError("boom-shared")


NOT_CALLABLE = "i am not a function"
