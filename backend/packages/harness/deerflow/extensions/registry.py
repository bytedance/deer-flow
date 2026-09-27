"""Registration-phase registry and its immutable runtime product.

Extensions only ever see the write-only public ``ExtensionRegistry`` contract.
The concrete host type additionally owns attribution, rollback, and immutable
runtime projection.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any

from deerflow_extension_api import (
    AgentAssemblyObserver,
    ContextCompactionObserver,
    ExtensionData,
    ExtensionService,
    MiddlewareContributor,
    SystemModelCallObserver,
    TaskLifecycleContributor,
)
from deerflow_extension_api import ExtensionRegistry as ExtensionRegistryContract
from deerflow_extension_api.plugins import BrowserAssets, BrowserModule, PluginContribution

from deerflow.extensions.model_access import ModelInvocationScope, ModelInvocationService

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
    agent_assembly_observers: tuple[tuple[str, AgentAssemblyObserver], ...] = ()
    # No has_context_compaction_observers precomputed flag: unlike agent-assembly
    # description (a synchronous, per-graph-build cost worth short-circuiting
    # ahead of time), the compaction hook sites test this tuple's own truthiness
    # directly, so a redundant flag would just be another thing to keep in sync.
    # Note "sites", plural: notify_context_compacted is the last of them, and a
    # check there cannot cover work already done by the time it is called --
    # _freeze_compaction_sources runs an O(context-size) hashing pass one frame
    # earlier and has to make the same test itself.
    context_compaction_observers: tuple[tuple[str, ContextCompactionObserver], ...] = ()
    services: tuple[tuple[str, ExtensionService], ...] = ()
    routers: tuple[tuple[str, Any], ...] = ()
    plugins: tuple[tuple[str, PluginContribution], ...] = ()

    # Precomputed attributes, not methods: hook sites read one attribute to
    # short-circuit, so the zero-extension path constructs nothing.
    has_middleware_contributors: bool = False
    has_task_lifecycle: bool = False
    has_system_model_observers: bool = False
    has_agent_assembly_observers: bool = False
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
        self._agent_assembly_observers: list[_Entry] = []
        self._context_compaction_observers: list[_Entry] = []
        self._services: list[_Entry] = []
        self._routers: list[_Entry] = []
        self._plugins: list[_Entry] = []
        self._current_source: str | None = None
        self._model_access: ModelInvocationScope | None = None

    @contextmanager
    def attributed_to(self, source: str, *, model_access: ModelInvocationScope | None = None) -> Iterator[None]:
        """Attribute everything registered inside the block to ``source``."""
        previous = self._current_source
        previous_access = self._model_access
        self._current_source = source
        self._model_access = model_access
        try:
            yield
        finally:
            self._current_source = previous
            self._model_access = previous_access

    def _source(self) -> str:
        if self._current_source is None:
            raise RuntimeError("registration must happen inside ExtensionRegistry.attributed_to(...)")
        return self._current_source

    def plugin(self, contribution: PluginContribution) -> bool:
        if not isinstance(contribution, PluginContribution) or contribution.api_version != 1:
            raise ValueError("Unsupported plugin contract")
        if not contribution.frontend and not contribution.backend and not contribution.tools:
            raise ValueError("A plugin must contribute a browser module, backend action or tool")
        from deerflow.extensions.plugin_tools import validate_schema

        tool_names = set()
        for tool in contribution.tools:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", tool.name) or tool.name in tool_names or not tool.description or not inspect.iscoroutinefunction(tool.handler):
                raise ValueError("Model tools require unique names, descriptions and async handlers")
            validate_schema(tool.input_schema, tool=True)
            tool_names.add(tool.name)
        names = set()
        for action in contribution.backend:
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", action.name) or action.name in names or not inspect.iscoroutinefunction(action.handler):
                raise ValueError("Backend actions require unique names and async handlers")
            names.add(action.name)
        if isinstance(contribution.frontend, BrowserAssets):
            from deerflow.extensions.browser_assets import load_browser_assets

            contribution = replace(contribution, frontend=load_browser_assets(contribution.frontend))
        elif isinstance(contribution.frontend, BrowserModule):
            if not contribution.frontend.code or len(contribution.frontend.code.encode()) > 512 * 1024:
                raise ValueError("Browser code must be nonempty and at most 512 KiB")
        elif contribution.frontend is not None:
            raise ValueError("Unsupported browser transport")
        # Validate everything before writing the plugin bucket; loader rollback also
        # covers a later failure elsewhere in this package's install function.
        from deerflow.config.plugin_settings import validate_contribution

        validate_contribution(contribution.settings_contribution())
        if any(item.namespace == contribution.namespace for _, item in self._plugins):
            raise ValueError("Duplicate plugin namespace")
        if contribution.frontend and any(item.frontend and item.frontend.module == contribution.frontend.module for _, item in self._plugins):
            raise ValueError("Duplicate browser module")
        self._plugins.append((self._source(), contribution))
        return True

    def middlewares(self, contributor: MiddlewareContributor) -> None:
        self._middlewares.append((self._source(), contributor))

    def task_lifecycle(self, contributor: TaskLifecycleContributor) -> None:
        self._task_lifecycle.append((self._source(), contributor))

    def system_model_observer(self, observer: SystemModelCallObserver) -> None:
        self._system_model_observers.append((self._source(), observer))

    def agent_assembly_observer(self, observer: AgentAssemblyObserver) -> None:
        self._agent_assembly_observers.append((self._source(), observer))

    def context_compaction_observer(self, observer: ContextCompactionObserver) -> None:
        self._context_compaction_observers.append((self._source(), observer))

    def service(self, service: ExtensionService) -> None:
        if self._model_access is not None:
            service = ModelInvocationService(service, self._model_access)
        self._services.append((self._source(), service))

    def routers(self, routers: Sequence[Any]) -> None:
        source = self._source()
        self._routers.extend((source, router) for router in routers)

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
            self._agent_assembly_observers,
            self._context_compaction_observers,
            self._services,
            self._routers,
            self._plugins,
        ):
            bucket[:] = [entry for entry in bucket if entry[0] != source]

    def mark(self) -> tuple[int, ...]:
        """Snapshot bucket lengths so one install() can be undone positionally."""
        return (
            len(self._middlewares),
            len(self._task_lifecycle),
            len(self._system_model_observers),
            len(self._agent_assembly_observers),
            len(self._context_compaction_observers),
            len(self._services),
            len(self._routers),
            len(self._plugins),
        )

    def rollback_to(self, mark: tuple[int, ...]) -> None:
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
                self._agent_assembly_observers,
                self._context_compaction_observers,
                self._services,
                self._routers,
                self._plugins,
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
            agent_assembly_observers=tuple(self._agent_assembly_observers),
            context_compaction_observers=tuple(self._context_compaction_observers),
            services=tuple(self._services),
            routers=tuple(self._routers),
            plugins=tuple(self._plugins),
            has_middleware_contributors=bool(self._middlewares),
            has_task_lifecycle=bool(self._task_lifecycle),
            has_system_model_observers=bool(self._system_model_observers),
            has_agent_assembly_observers=bool(self._agent_assembly_observers),
            needs_task_store=bool(self._middlewares or self._task_lifecycle or self._system_model_observers or self._context_compaction_observers),
        )


#: Shared empty instance for hosts that load no extensions.
EMPTY_EXTENSIONS = ExtensionRegistry().build()
