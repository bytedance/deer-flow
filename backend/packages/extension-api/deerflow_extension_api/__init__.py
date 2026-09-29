"""Public contracts for DeerFlow extensions.

This package MUST NOT import `deerflow`. Every host contract an extension
needs lives here, while framework imports remain direct extension dependencies;
extensions can therefore be released independently of the host.
"""

from __future__ import annotations

from deerflow_extension_api.assembly import (
    AgentAssemblyDescriptor,
    AgentAssemblyObserver,
    MiddlewareDescriptor,
    ToolDescriptor,
)
from deerflow_extension_api.auth import (
    EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY,
    EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY,
    EXTENSION_PRINCIPAL_RESOLVER_KEY,
    ExtensionPrincipal,
    arequire_plugin_management,
    require_admin,
    require_plugin_management,
    resolve_principal,
)
from deerflow_extension_api.compaction import (
    CompactionEvent,
    ContextCompactionObserver,
)
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
from deerflow_extension_api.model_invocation import (
    ModelInvocationError,
    ModelInvocationFailed,
    ModelInvocationRequest,
    ModelInvocationResult,
    ModelInvocationUnauthorized,
    ModelInvocationUnavailable,
    ModelInvoker,
    ModelMessage,
    ModelOutputValidationError,
    ModelUsage,
)
from deerflow_extension_api.placement import (
    AgentBuildContext,
    AgentScope,
    MiddlewarePlacement,
    Placement,
)
from deerflow_extension_api.plugins import ActionContext, BackendAction, BrowserAssets, BrowserModule, ModelTool, PluginContribution, ToolContext
from deerflow_extension_api.provenance import (
    MESSAGE_CONTENT_KIND_KEY,
    MESSAGE_PRODUCER_ENTITY_ID_KEY,
    MESSAGE_PRODUCER_KIND_KEY,
    PROVENANCE_KEYS,
    ContentKind,
    MessageProvenance,
    provenance_kwargs,
    read_provenance,
)
from deerflow_extension_api.release import (
    ReleasePolicyProvider,
    canonical_hash,
    canonical_json,
    collect_release_policies,
)
from deerflow_extension_api.run_evidence import (
    RUN_EVIDENCE_READER_RESOLVER_KEY,
    InvalidRunEvidenceCursor,
    RunEventPage,
    RunEventView,
    RunEvidenceReader,
    RunPage,
    RunStatusView,
    require_run_evidence_reader,
    resolve_run_evidence_reader,
)
from deerflow_extension_api.runtime_bridge import (
    EXTENSION_TASK_STORE_KEY,
    task_store_from_runtime,
)
from deerflow_extension_api.settings import SettingsField
from deerflow_extension_api.state import ExtensionData

#: Contract version. Before 1.0, minors may break and patches are additive.
#: From 1.0 on, bump the major for breaking changes.
API_VERSION = "0.2.4"

__all__ = [
    "ModelInvocationError",
    "ModelInvocationFailed",
    "ModelInvocationRequest",
    "ModelInvocationResult",
    "ModelInvocationUnauthorized",
    "ModelInvocationUnavailable",
    "ModelInvoker",
    "ModelMessage",
    "ModelOutputValidationError",
    "ModelUsage",
    "ActionContext",
    "BackendAction",
    "BrowserAssets",
    "BrowserModule",
    "ModelTool",
    "PluginContribution",
    "ToolContext",
    "SettingsField",
    "API_VERSION",
    "EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY",
    "EXTENSION_PLUGIN_AUTHZ_RESOLVER_KEY",
    "EXTENSION_PRINCIPAL_RESOLVER_KEY",
    "EXTENSION_TASK_STORE_KEY",
    "MESSAGE_CONTENT_KIND_KEY",
    "MESSAGE_PRODUCER_ENTITY_ID_KEY",
    "MESSAGE_PRODUCER_KIND_KEY",
    "PROVENANCE_KEYS",
    "AgentAssemblyDescriptor",
    "AgentAssemblyObserver",
    "AgentBuildContext",
    "AgentScope",
    "CompactionEvent",
    "ContentKind",
    "ContextCompactionObserver",
    "ExtensionData",
    "ExtensionInstall",
    "ExtensionPrincipal",
    "ExtensionRegistry",
    "ExtensionRuntimeDeps",
    "ExtensionService",
    "HostPolicySnapshot",
    "InvalidRunEvidenceCursor",
    "MessageProvenance",
    "MiddlewareContributor",
    "MiddlewareDescriptor",
    "MiddlewarePlacement",
    "Placement",
    "ReleasePolicyProvider",
    "RunEvidenceReader",
    "RUN_EVIDENCE_READER_RESOLVER_KEY",
    "RunEventPage",
    "RunEventView",
    "RunPage",
    "RunStatusView",
    "require_run_evidence_reader",
    "resolve_run_evidence_reader",
    "SystemModelCallObserver",
    "SystemModelRequest",
    "SystemModelResult",
    "SystemOperationKind",
    "TaskInfo",
    "TaskLifecycleContributor",
    "TaskOutcome",
    "ToolDescriptor",
    "canonical_hash",
    "canonical_json",
    "collect_release_policies",
    "arequire_plugin_management",
    "extension",
    "provenance_kwargs",
    "read_provenance",
    "require_admin",
    "require_plugin_management",
    "resolve_principal",
    "task_store_from_runtime",
]
