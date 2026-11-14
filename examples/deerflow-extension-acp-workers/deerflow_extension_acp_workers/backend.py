"""Translate ACP protocol facts into delegated-worker outcomes."""

from deerflow.acp.transport import invoke_acp
from deerflow.config.acp_config import ACPAgentConfig
from deerflow.subagents.worker_backends import (
    WorkerCapabilities,
    WorkerOperation,
    WorkerOutcome,
)


class ACPWorkerBackend:
    capabilities = WorkerCapabilities()

    def bind(self, name, config, app_config):
        if set(config) != {"agent"} or not isinstance(config["agent"], str):
            raise ValueError("ACP worker config requires only agent: <acp_agents name>")
        agent = config["agent"]
        agents = app_config.acp_agents
        if agent not in agents:
            raise ValueError(f"Unknown ACP agent: {agent}")
        launch = agents[agent].model_dump(mode="json")
        return {
            "agent": agent,
            "launch": launch,
            "timeout_seconds": launch["timeout_seconds"],
        }

    def operation(self, plan, prompt):
        return WorkerOperation(
            "invoke_acp_agent", {"agent": plan.config["agent"], "prompt": prompt}
        )

    async def execute(self, plan, execution):
        config = ACPAgentConfig.model_validate(dict(plan.config["launch"]))
        outcome = await invoke_acp(
            plan.config["agent"],
            config,
            execution.prompt,
            cwd=execution.workspace,
            mcp_servers=[],
            on_text=execution.publish,
        )
        common = {
            "backend_stop_reason": outcome.stop_reason,
            "external_usage": outcome.usage,
            "workspace_ref": execution.workspace,
        }
        if outcome.error_code:
            return WorkerOutcome(
                status="failed",
                error=outcome.error,
                error_code=outcome.error_code,
                **common,
            )
        if outcome.stop_reason == "refusal":
            return WorkerOutcome(
                status="failed",
                error="The external agent refused the task.",
                error_code="backend_refusal",
                **common,
            )
        if outcome.stop_reason in {"max_tokens", "max_turn_requests"}:
            if outcome.text.strip():
                return WorkerOutcome(
                    result=outcome.text, stop_reason="backend_capped", **common
                )
            return WorkerOutcome(
                status="failed",
                error="The external agent reached its limit without returning text.",
                stop_reason="backend_capped",
                error_code="backend_capped",
                **common,
            )
        if outcome.stop_reason == "cancelled":
            return WorkerOutcome(
                status="cancelled",
                error="The external agent cancelled the task.",
                **common,
            )
        if outcome.stop_reason != "end_turn":
            return WorkerOutcome(
                status="failed",
                error="The external agent returned an unsupported stop reason.",
                error_code="acp_protocol_error",
                **common,
            )
        return WorkerOutcome(
            result=outcome.text if outcome.text.strip() else "(no text returned)",
            **common,
        )
