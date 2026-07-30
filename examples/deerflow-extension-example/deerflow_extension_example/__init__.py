"""A worked example of a DeerFlow extension.

One package, one entry point, all five contribution points. What it does is
deliberately trivial -- it counts things and serves the counts on one route --
because the point is the *shape*, not the feature: where each contribution
attaches, which scope owns which data, and when host capabilities exist.

Install it and list it under ``plugins:`` in ``config.yaml``; see README.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from deerflow_extension_api import ExtensionInstall, ExtensionRegistry, extension

from deerflow_extension_example.lifecycle import SystemCallRecorder, TaskRecorder
from deerflow_extension_example.probes import ProbeContributor
from deerflow_extension_example.service import ExampleService, build_router
from deerflow_extension_example.stats import DEFAULT_RECENT_TASKS, StatsAccess

__all__ = ["install"]


def _recent_limit(config: Mapping[str, Any]) -> int:
    """Read one setting, tolerantly.

    The host hands ``install()`` this extension's own config block verbatim and
    does not validate it -- validating it is this package's job, and doing it
    here means a typo in ``config.yaml`` surfaces as a startup diagnostic naming
    this extension rather than as a confusing failure later.
    """
    raw = config.get("recent_task_limit", DEFAULT_RECENT_TASKS)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"recent_task_limit must be an integer, got {raw!r}") from exc


@extension(api="0.1", name="example")
def install(registry: ExtensionRegistry, config: Mapping[str, Any]) -> None:
    """Register everything this extension contributes.

    The decorator stamps the contract version this code was written against.
    pip's resolver is the primary compatibility mechanism; the stamp covers
    ``--no-deps`` installs and editable monorepo checkouts, where a host/contract
    version skew would otherwise surface as a deep ``AttributeError`` instead of
    an actionable startup diagnostic.

    Registration is capability-free by construction: ``registry`` is write-only,
    so nothing here can reach the host's runtime even by accident. Real
    dependencies arrive later, in ``ExampleService.start()``.
    """
    if not config.get("enabled", True):
        # An installed package that registers nothing is the correct way to be
        # switched off. Raising here would be a load failure, which is a
        # different -- and louder -- thing than being disabled on purpose.
        return

    access = StatsAccess(recent_limit=_recent_limit(config))
    service = ExampleService(access)

    registry.middlewares(ProbeContributor(access))
    registry.task_lifecycle(TaskRecorder(access))
    registry.system_model_observer(SystemCallRecorder(access))
    registry.service(service)
    # Same object as the service above: that is what lets an eagerly built route
    # resolve runtime dependencies the registration phase cannot have yet.
    registry.routers([build_router(service, access)])


#: Conformance to the published entry-point signature, checked by the type
#: checker rather than trusted. A host that changes the signature breaks here,
#: at the boundary, instead of at call time.
_entry_point: ExtensionInstall = install
