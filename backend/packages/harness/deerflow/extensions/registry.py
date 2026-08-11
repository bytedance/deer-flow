"""Registration-phase registry and its immutable runtime product.

Extensions only ever see the write-only public ``ExtensionRegistry`` contract.
The concrete host type additionally owns attribution, rollback, and immutable
runtime projection.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from deerflow_extension_api import (
    ExtensionData,
    MiddlewareContributor,
    SystemModelCallObserver,
    TaskLifecycleContributor,
)
from deerflow_extension_api import ExtensionRegistry as ExtensionRegistryContract

_Entry = tuple[str, Any]


@dataclass(frozen=True)
class LoadedExtensions:
    """Immutable view consumed at runtime.

    Every entry carries its source string so diagnostics, provenance and
    ordering errors can name the extension responsible.
    """

    app_store: ExtensionData
    middleware_contributors: tuple[tuple[str, MiddlewareContributor], ...] = ()
    task_lifecycle: tuple[tuple[str, TaskLifecycleContributor], ...] = ()
    system_model_observers: tuple[tuple[str, SystemModelCallObserver], ...] = ()

    # Precomputed attributes, not methods: hook sites read one attribute to
    # short-circuit, so the zero-extension path constructs nothing.
    has_middleware_contributors: bool = False
    has_task_lifecycle: bool = False
    has_system_model_observers: bool = False
    needs_task_store: bool = False


class ExtensionRegistry(ExtensionRegistryContract):
    """Mutable, registration-phase only.

    Subclasses the public contract Protocol so the host implementation is
    type-checked against what extensions annotate; the host-only machinery
    below (attribution, discard, mark/rollback_to, build) stays out of the
    contract on purpose.
    """

    def __init__(self) -> None:
        self._middlewares: list[_Entry] = []
        self._task_lifecycle: list[_Entry] = []
        self._system_model_observers: list[_Entry] = []
        self._current_source: str | None = None

    @contextmanager
    def attributed_to(self, source: str) -> Iterator[None]:
        """Attribute everything registered inside the block to ``source``."""
        previous = self._current_source
        self._current_source = source
        try:
            yield
        finally:
            self._current_source = previous

    def _source(self) -> str:
        if self._current_source is None:
            raise RuntimeError("registration must happen inside ExtensionRegistry.attributed_to(...)")
        return self._current_source

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        self._middlewares.append((self._source(), contributor))

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        self._task_lifecycle.append((self._source(), contributor))

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
        self._system_model_observers.append((self._source(), observer))

    def discard(self, source: str) -> None:
        """Remove every entry registered by ``source``.

        Called when install() raises partway through. A half-registered
        extension is more dangerous than an absent one because the data it
        produces looks complete.

        Note: this matches by source string, so it is unsafe when two specs
        share the same ``use`` with different config — it would remove a
        different, successfully-installed instance's entries too. Callers
        that process one install() at a time should prefer
        ``mark()``/``rollback_to()`` instead.
        """
        for bucket in (
            self._middlewares,
            self._task_lifecycle,
            self._system_model_observers,
        ):
            bucket[:] = [entry for entry in bucket if entry[0] != source]

    def mark(self) -> tuple[int, int, int]:
        """Snapshot bucket lengths so one install() can be undone positionally."""
        return (
            len(self._middlewares),
            len(self._task_lifecycle),
            len(self._system_model_observers),
        )

    def rollback_to(self, mark: tuple[int, int, int]) -> None:
        """Undo every registration made since ``mark``.

        Positional rather than source-keyed: two specs may legitimately share
        a ``use`` string with different config, and deleting by source would
        take the other instance's successful registrations with it.
        """
        for bucket, size in zip(
            (
                self._middlewares,
                self._task_lifecycle,
                self._system_model_observers,
            ),
            mark,
            strict=True,
        ):
            del bucket[size:]

    def build(self) -> LoadedExtensions:
        return LoadedExtensions(
            app_store=ExtensionData("app"),
            middleware_contributors=tuple(self._middlewares),
            task_lifecycle=tuple(self._task_lifecycle),
            system_model_observers=tuple(self._system_model_observers),
            has_middleware_contributors=bool(self._middlewares),
            has_task_lifecycle=bool(self._task_lifecycle),
            has_system_model_observers=bool(self._system_model_observers),
            needs_task_store=bool(self._middlewares or self._task_lifecycle or self._system_model_observers),
        )


#: Shared empty instance for hosts that load no extensions.
EMPTY_EXTENSIONS = ExtensionRegistry().build()
