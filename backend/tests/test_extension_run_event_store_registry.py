"""Host collection of extension-provided run-event store factories."""

from __future__ import annotations

import pytest

from deerflow.extensions.registry import EMPTY_EXTENSIONS, ExtensionRegistry


def _factory(cfg):
    return object()


def test_run_event_store_registration_collected():
    registry = ExtensionRegistry()
    with registry.attributed_to("ext-a"):
        assert registry.run_event_store("kurrent", _factory) is True
    built = registry.build()
    assert built.run_event_store_factories == (("ext-a", ("kurrent", _factory)),)
    assert EMPTY_EXTENSIONS.run_event_store_factories == ()


@pytest.mark.parametrize("name", ["memory", "db", "jsonl"])
def test_run_event_store_rejects_builtin_name(name):
    registry = ExtensionRegistry()
    with registry.attributed_to("ext-a"):
        assert registry.run_event_store(name, _factory) is False
    assert registry.build().run_event_store_factories == ()


def test_run_event_store_rejects_duplicate_name():
    registry = ExtensionRegistry()
    with registry.attributed_to("ext-a"):
        assert registry.run_event_store("kurrent", _factory) is True
    with registry.attributed_to("ext-b"):
        assert registry.run_event_store("kurrent", _factory) is False
    assert len(registry.build().run_event_store_factories) == 1


@pytest.mark.parametrize("name", ["", "Kurrent", "1abc", "_a", "a b", "a" * 65, None, 5])
def test_run_event_store_rejects_bad_name(name):
    registry = ExtensionRegistry()
    with registry.attributed_to("ext-a"):
        assert registry.run_event_store(name, _factory) is False
    assert registry.build().run_event_store_factories == ()


def test_run_event_store_rolled_back_and_discarded():
    registry = ExtensionRegistry()
    mark = registry.mark()
    with registry.attributed_to("ext-a"):
        registry.run_event_store("kurrent", _factory)
    registry.rollback_to(mark)
    assert registry.build().run_event_store_factories == ()
    with registry.attributed_to("ext-a"):
        registry.run_event_store("kurrent", _factory)
    registry.discard("ext-a")
    assert registry.build().run_event_store_factories == ()
