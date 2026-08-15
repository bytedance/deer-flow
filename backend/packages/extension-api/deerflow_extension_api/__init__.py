"""Public contracts for DeerFlow extensions.

This package MUST NOT import `deerflow`. Every host contract an extension
needs lives here, while framework imports remain direct extension dependencies;
extensions can therefore be released independently of the host.
"""

from __future__ import annotations

from deerflow_extension_api.contracts import (
    ExtensionInstall,
    ExtensionRegistry,
    ExtensionRuntimeDeps,
    ExtensionService,
    HostPolicySnapshot,
    MiddlewareContributor,
    SystemModelCallObserver,
    SystemModelRequest,
    SystemModelResult,
    SystemOperationKind,
    TaskInfo,
    TaskLifecycleContributor,
    TaskOutcome,
    extension,
)
from deerflow_extension_api.placement import (
    AgentBuildContext,
    AgentScope,
    MiddlewarePlacement,
    Placement,
)
from deerflow_extension_api.runtime_bridge import (
    EXTENSION_TASK_STORE_KEY,
    task_store_from_runtime,
)
from deerflow_extension_api.state import ExtensionData

#: Contract version. Before 1.0, minors may break and patches are additive.
#: From 1.0 on, bump the major for breaking changes.
API_VERSION = "0.1.2"

__all__ = [
    "API_VERSION",
    "EXTENSION_TASK_STORE_KEY",
    "AgentBuildContext",
    "AgentScope",
    "ExtensionData",
    "ExtensionInstall",
    "ExtensionRegistry",
    "ExtensionRuntimeDeps",
    "ExtensionService",
    "HostPolicySnapshot",
    "MiddlewareContributor",
    "MiddlewarePlacement",
    "Placement",
    "SystemModelCallObserver",
    "SystemModelRequest",
    "SystemModelResult",
    "SystemOperationKind",
    "TaskInfo",
    "TaskLifecycleContributor",
    "TaskOutcome",
    "extension",
    "task_store_from_runtime",
]
