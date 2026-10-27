"""Standalone Jev extension. No imports from DeerFlow host internals."""

import os

from deerflow_extension_api import AgentScope, BackendAction, MiddlewarePlacement, Placement, PluginContribution, SettingsField, extension

from .compaction import JevCompaction, Options


class Contributor:
    def __init__(self, options):
        self.options = options

    def contribute_middlewares(self, app_store, context):
        if not self.options.enabled or context.scope != AgentScope.LEAD:
            return ()
        return (MiddlewarePlacement(JevCompaction(self.options), Placement.MODEL_LOGICAL, AgentScope.LEAD),)


@extension(api="0.2.2", name="jev-context")
def install(registry, config):
    options = Options.model_validate(dict(config))

    async def status(payload, context):
        if payload:
            raise ValueError("Status takes no arguments")
        # Configuration only: never expose keys, environment names, transcripts,
        # cross-user counters, or per-process counters mistaken for durable totals.
        return {"enabled": options.enabled, "configured": bool(os.environ.get(options.api_key_env)), "trigger_tokens": options.trigger_tokens}

    if (
        registry.plugin(
            PluginContribution(
                namespace="community.jev-context",
                title="Jev 上下文裁剪 / Jev context pruning",
                description="按需缩短旧的只读工具结果；保留近期消息与原生摘要。需要部署者配置 Jev 密钥。",
                enabled=options.enabled,
                fields=(SettingsField("trigger_tokens", "触发阈值 / Estimated token threshold", "integer", options.trigger_tokens, minimum=1000, maximum=2000000),),
                backend=(BackendAction("status", status),),
            )
        )
        is not True
    ):
        raise RuntimeError("Jev context requires the full-stack plugin host contract")
    registry.middlewares(Contributor(options))
