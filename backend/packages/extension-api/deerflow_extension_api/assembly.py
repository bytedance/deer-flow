"""What an agent was assembled from, captured where it is knowable.

The lead-agent factory resolves a model (after runtime overrides), renders a
system prompt, filters a tool list through authorization, and composes a
middleware stack. All four are decided inside one synchronous call and none of
them survives to any later observation point: a middleware sees its neighbours
but not the prompt, the run worker sees the graph but not what went into it.

The factory therefore emits a descriptor alongside the graph. Its fingerprint
is what makes "did anything about this agent change between these two runs?"
answerable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Protocol

from deerflow_extension_api.release import canonical_hash
from deerflow_extension_api.state import ExtensionData


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description_hash: str
    schema_hash: str
    source: str
    mcp_server: str | None = None
    mcp_transport: str | None = None


@dataclass(frozen=True)
class MiddlewareDescriptor:
    name: str
    module: str
    policy_parameters: dict[str, Any] = field(default_factory=dict)
    #: Extension this middleware was contributed by, or ``None`` for a host
    #: middleware. Contributed middlewares reach the stack inside a wrapper
    #: whose class name is shared by all of them, so without this two
    #: extensions' middlewares would be indistinguishable here.
    extension: str | None = None


@dataclass(frozen=True)
class AgentAssemblyDescriptor:
    namespace: str
    agent_name: str
    requested_model: str | None
    effective_model: str
    model_parameters: dict[str, Any]
    thinking_enabled: bool
    reasoning_effort: Any
    base_prompt_hash: str
    tools: tuple[ToolDescriptor, ...]
    middlewares: tuple[MiddlewareDescriptor, ...]
    deferred_tool_names: tuple[str, ...]
    enabled_skills: tuple[str, ...]
    effective_policies: dict[str, Any]
    #: Which host build produced this assembly (package version, image digest,
    #: git commit). Reported, but deliberately outside ``fingerprint`` — see
    #: the note there.
    build: dict[str, Any] = field(default_factory=dict)

    @cached_property
    def fingerprint(self) -> str:
        """Identity of everything that changes how this agent behaves.

        Tools and skills are sorted: their assembly order is incidental.
        Middlewares are not: stack order decides what wraps what.

        Two fields are reported but deliberately excluded:

        * ``build`` — the fingerprint answers "did this agent's assembly
          change", which is a finer question than "did the host binary
          change". Folding the build in would change every agent's fingerprint
          on every redeploy, making the fine question unanswerable; leaving it
          out keeps both answerable, because a consumer can still compare
          ``build`` directly.
        * ``requested_model`` — only ``effective_model`` reaches the provider,
          so a request that resolves to the same effective model is not a
          behavioural difference.
        """
        return canonical_hash(
            {
                "namespace": self.namespace,
                "agent_name": self.agent_name,
                "effective_model": self.effective_model,
                "model_parameters": self.model_parameters,
                "thinking_enabled": self.thinking_enabled,
                "reasoning_effort": self.reasoning_effort,
                "base_prompt_hash": self.base_prompt_hash,
                "tools": sorted(
                    [
                        {
                            "name": tool.name,
                            "description_hash": tool.description_hash,
                            "schema_hash": tool.schema_hash,
                            "source": tool.source,
                            "mcp_server": tool.mcp_server,
                            "mcp_transport": tool.mcp_transport,
                        }
                        for tool in self.tools
                    ],
                    key=lambda entry: entry["name"],
                ),
                "middlewares": [{"name": m.name, "module": m.module, "extension": m.extension, "policy_parameters": m.policy_parameters} for m in self.middlewares],
                "deferred_tool_names": sorted(self.deferred_tool_names),
                "enabled_skills": sorted(self.enabled_skills),
                "effective_policies": self.effective_policies,
            }
        )


class AgentAssemblyObserver(Protocol):
    def on_agent_assembled(self, app_store: ExtensionData, descriptor: AgentAssemblyDescriptor) -> None:
        """Called synchronously at the end of agent construction.

        Synchronous because construction is: there is no loop to await on, and
        the descriptor must be captured before the graph is handed out.
        Implementations must be cheap and must not raise.
        """
        return None
