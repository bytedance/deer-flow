"""Tests for the extension registry and its immutable build product."""

from __future__ import annotations

import pytest

from deerflow.extensions.registry import EMPTY_EXTENSIONS, ExtensionRegistry


class _Contributor:
    def __init__(self, tag: str = "") -> None:
        self.tag = tag


def test_empty_registry_builds_with_all_flags_false():
    loaded = ExtensionRegistry().build()
    assert loaded.has_middleware_contributors is False
    assert loaded.has_task_lifecycle is False
    assert loaded.has_system_model_observers is False
    assert loaded.needs_task_store is False


def test_empty_singleton_matches_an_empty_build():
    assert EMPTY_EXTENSIONS.has_middleware_contributors is False
    assert EMPTY_EXTENSIONS.has_task_lifecycle is False
    assert EMPTY_EXTENSIONS.has_system_model_observers is False
    assert EMPTY_EXTENSIONS.needs_task_store is False


@pytest.mark.parametrize(
    "register",
    [
        lambda registry, contributor: registry.middlewares(contributor),
        lambda registry, contributor: registry.task_lifecycle(contributor),
        lambda registry, contributor: registry.system_model_observer(contributor),
    ],
    ids=["middleware", "task-lifecycle", "system-model-observer"],
)
def test_task_scoped_contributions_require_a_task_store(register):
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        register(registry, _Contributor())

    assert registry.build().needs_task_store is True


def test_entries_carry_their_source():
    registry = ExtensionRegistry()
    contributor = _Contributor("mw")
    with registry.attributed_to("demo_ext:install"):
        registry.middlewares(contributor)
    loaded = registry.build()
    assert loaded.middleware_contributors == (("demo_ext:install", contributor),)
    assert loaded.has_middleware_contributors is True


def test_task_lifecycle_entries_are_attributed_and_require_task_storage():
    registry = ExtensionRegistry()
    contributor = _Contributor("lifecycle")
    with registry.attributed_to("lifecycle_ext:install"):
        registry.task_lifecycle(contributor)

    loaded = registry.build()

    assert loaded.task_lifecycle == (("lifecycle_ext:install", contributor),)
    assert loaded.has_task_lifecycle is True
    assert loaded.needs_task_store is True


def test_system_model_observers_are_attributed_and_require_task_storage():
    registry = ExtensionRegistry()
    observer = _Contributor("system-model")
    with registry.attributed_to("observer_ext:install"):
        registry.system_model_observer(observer)

    loaded = registry.build()

    assert loaded.system_model_observers == (("observer_ext:install", observer),)
    assert loaded.has_system_model_observers is True
    assert loaded.needs_task_store is True


def test_rollback_restores_all_registration_buckets_positionally():
    registry = ExtensionRegistry()
    with registry.attributed_to("keep:install"):
        registry.middlewares(_Contributor("keep"))
    mark = registry.mark()
    with registry.attributed_to("drop:install"):
        registry.middlewares(_Contributor("drop-middleware"))
        registry.task_lifecycle(_Contributor("drop-lifecycle"))
        registry.system_model_observer(_Contributor("drop-observer"))

    registry.rollback_to(mark)
    loaded = registry.build()

    assert [contributor.tag for _, contributor in loaded.middleware_contributors] == ["keep"]
    assert loaded.task_lifecycle == ()
    assert loaded.system_model_observers == ()


def test_registration_order_is_preserved():
    registry = ExtensionRegistry()
    first, second = _Contributor("a"), _Contributor("b")
    with registry.attributed_to("a_ext:install"):
        registry.middlewares(first)
    with registry.attributed_to("b_ext:install"):
        registry.middlewares(second)
    loaded = registry.build()
    assert [source for source, _ in loaded.middleware_contributors] == ["a_ext:install", "b_ext:install"]


def test_discard_removes_every_entry_of_one_source():
    """A partially-registered extension is worse than an absent one: the data
    it produces looks complete but is not."""
    registry = ExtensionRegistry()
    keep, drop = _Contributor("keep"), _Contributor("drop")
    with registry.attributed_to("good:install"):
        registry.middlewares(keep)
        registry.task_lifecycle(keep)
    with registry.attributed_to("bad:install"):
        registry.middlewares(drop)
        registry.system_model_observer(drop)
    registry.discard("bad:install")
    loaded = registry.build()
    assert loaded.middleware_contributors == (("good:install", keep),)
    assert loaded.task_lifecycle == (("good:install", keep),)
    assert loaded.system_model_observers == ()


def test_registering_outside_attributed_to_raises():
    registry = ExtensionRegistry()
    with pytest.raises(RuntimeError, match="attributed_to"):
        registry.middlewares(_Contributor())


def test_build_result_is_frozen():
    loaded = ExtensionRegistry().build()
    with pytest.raises(Exception):
        loaded.middleware_contributors = ()  # type: ignore[misc]


def test_app_store_is_created_at_build_time():
    """The app store must exist before binding so the registration phase and
    the binding phase see the same object."""
    loaded = ExtensionRegistry().build()
    assert loaded.app_store is not None
    assert loaded.app_store.scope_id == "app"
