"""Tests for ExtensionData, the per-scope typed store handed to extensions."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Thread

from deerflow_extension_api import ExtensionData


@dataclass
class _Counter:
    value: int = 0


@dataclass
class _Other:
    name: str = ""


def test_get_returns_none_when_absent():
    store = ExtensionData("task-1")
    assert store.get(_Counter) is None


def test_set_then_get_roundtrips():
    store = ExtensionData("task-1")
    store.set(_Counter(value=7))
    got = store.get(_Counter)
    assert got is not None
    assert got.value == 7


def test_get_or_init_creates_once():
    store = ExtensionData("task-1")
    calls = []

    def _init() -> _Counter:
        calls.append(1)
        return _Counter(value=1)

    first = store.get_or_init(_Counter, _init)
    second = store.get_or_init(_Counter, _init)
    assert first is second
    assert calls == [1]


def test_get_or_init_allows_initializer_to_use_the_same_store():
    """Extension initializers may compose other extension-local state."""
    store = ExtensionData("task-1")
    completed: list[_Counter] = []

    def _init_counter() -> _Counter:
        store.set(_Other(name="nested"))
        return _Counter(value=2)

    def _initialize() -> None:
        completed.append(store.get_or_init(_Counter, _init_counter))

    thread = Thread(target=_initialize, daemon=True)
    thread.start()
    thread.join(timeout=0.5)

    assert not thread.is_alive(), "nested store access deadlocked"
    assert completed == [_Counter(value=2)]
    assert store.get(_Other) == _Other(name="nested")


def test_types_are_isolated():
    store = ExtensionData("task-1")
    store.set(_Counter(value=1))
    store.set(_Other(name="x"))
    assert store.get(_Counter).value == 1
    assert store.get(_Other).name == "x"


def test_remove_returns_and_clears():
    store = ExtensionData("task-1")
    store.set(_Counter(value=3))
    removed = store.remove(_Counter)
    assert removed.value == 3
    assert store.get(_Counter) is None


def test_scope_id_is_exposed():
    store = ExtensionData("run-42")
    assert store.scope_id == "run-42"


def test_stores_are_independent():
    a = ExtensionData("task-a")
    b = ExtensionData("task-b")
    a.set(_Counter(value=1))
    assert b.get(_Counter) is None


def test_api_package_does_not_import_deerflow():
    """The API package must stay independent of the host so extensions can
    depend on it alone. A `deerflow` import here would silently couple every
    extension to the harness release cadence."""
    import pathlib

    import deerflow_extension_api

    root = pathlib.Path(deerflow_extension_api.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("import deerflow", "from deerflow")) and not stripped.startswith(("import deerflow_extension_api", "from deerflow_extension_api")):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert offenders == [], "deerflow-extension-api must not import deerflow: " + "; ".join(offenders)
