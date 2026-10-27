"""Standalone text classification plugin. No imports from DeerFlow host internals."""

import os

from deerflow_extension_api import BackendAction, ModelTool, PluginContribution, SettingsField, extension

from .classify import INPUT_SCHEMA, TOOL_DESCRIPTION, Options, classify_texts


@extension(api="0.2.2", name="jev-classify")
def install(registry, config):
    options = Options.model_validate(dict(config))
    key_env = options.jev_api_key_env if options.backend == "jev" else options.llm_api_key_env

    async def classify(payload, context):
        return await classify_texts(payload, options)

    async def status(payload, context):
        if payload:
            raise ValueError("Status takes no arguments")
        # Configuration only: never keys, environment variable names or item text.
        return {"enabled": options.enabled, "backend": options.backend, "configured": bool(os.environ.get(key_env)), "batch_size": options.batch_size, "max_items": options.max_items}

    contribution = PluginContribution(
        namespace="community.jev-classify",
        title="文本分类 / Text classification",
        description="按给定类别给文本列表打标签；后端由部署方配置为 Jev 或聊天模型。/ Label a list of texts with the deployment-configured Jev or chat-model backend.",
        enabled=options.enabled,
        fields=(
            SettingsField("backend", "后端 / Backend", "string", options.backend, max_length=8),
            SettingsField("batch_size", "每请求条数 / Items per request", "integer", options.batch_size, minimum=1, maximum=20),
            SettingsField("max_items", "每次调用上限 / Items per call", "integer", options.max_items, minimum=1, maximum=300),
        ),
        backend=(BackendAction("status", status),),
        tools=(ModelTool("classify_texts", TOOL_DESCRIPTION, INPUT_SCHEMA, classify),),
    )
    if registry.plugin(contribution) is not True:
        raise RuntimeError("Text classification requires the full-stack plugin host contract")
