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
    assert loaded.services == ()
    assert loaded.routers == ()


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


def test_app_scoped_contributions_do_not_require_a_task_store():
    registry = ExtensionRegistry()
    with registry.attributed_to("demo:install"):
        registry.service(_Contributor())
        registry.routers([object()])

    assert registry.build().needs_task_store is False


def test_entries_carry_their_source():
    registry = ExtensionRegistry()
    contributor = _Contributor("mw")
    with registry.attributed_to("demo_ext:install"):
        registry.middlewares(contributor)
    loaded = registry.build()
    assert loaded.middleware_contributors == (("demo_ext:install", contributor),)
    assert loaded.has_middleware_contributors is True


def test_registration_order_is_preserved():
    registry = ExtensionRegistry()
    first, second = _Contributor("a"), _Contributor("b")
    with registry.attributed_to("a_ext:install"):
        registry.task_lifecycle(first)
    with registry.attributed_to("b_ext:install"):
        registry.task_lifecycle(second)
    loaded = registry.build()
    assert [source for source, _ in loaded.task_lifecycle] == ["a_ext:install", "b_ext:install"]


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
        registry.routers([object()])
    registry.discard("bad:install")
    loaded = registry.build()
    assert loaded.middleware_contributors == (("good:install", keep),)
    assert loaded.task_lifecycle == (("good:install", keep),)
    assert loaded.system_model_observers == ()
    assert loaded.routers == ()


def test_registering_outside_attributed_to_raises():
    registry = ExtensionRegistry()
    with pytest.raises(RuntimeError, match="attributed_to"):
        registry.middlewares(_Contributor())


def test_build_result_is_frozen():
    loaded = ExtensionRegistry().build()
    with pytest.raises(Exception):
        loaded.services = ()  # type: ignore[misc]


def test_app_store_is_created_at_build_time():
    """The app store must exist before binding so the registration phase and
    the binding phase see the same object."""
    loaded = ExtensionRegistry().build()
    assert loaded.app_store is not None
    assert loaded.app_store.scope_id == "app"


def test_routers_keep_their_source_in_order():
    """Routers carry (source, router) like every other bucket.

    Router prefix conflicts must produce a diagnostic naming the responsible
    extension; attribution dropped at build() cannot be recovered later."""
    registry = ExtensionRegistry()
    r1, r2, r3 = object(), object(), object()
    with registry.attributed_to("a:install"):
        registry.routers([r1, r2])
    with registry.attributed_to("b:install"):
        registry.routers([r3])
    assert registry.build().routers == (
        ("a:install", r1),
        ("a:install", r2),
        ("b:install", r3),
    )
