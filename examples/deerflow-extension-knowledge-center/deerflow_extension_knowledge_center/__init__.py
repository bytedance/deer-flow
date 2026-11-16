"""Browser-only client of the independently authorized platform API."""

from pathlib import Path

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BrowserAssets, PluginContribution


@extension(api="0.2.9", name="knowledge-center")
def install(registry, config):
    if set(config) - {"enabled"} or type(config.get("enabled", False)) is not bool:
        raise ValueError("Knowledge center accepts only a boolean enabled setting")
    if not registry.plugin(
        PluginContribution(
            namespace="knowledge-center",
            title="知识中心 / Knowledge center",
            description="浏览授权空间，导入知识并查询处理状态 / Browse authorized spaces, import knowledge and inspect processing status",
            enabled=config.get("enabled", False),
            frontend=BrowserAssets("knowledge-center.v1", Path(__file__).parent),
        )
    ):
        raise RuntimeError("Knowledge center requires the full-stack plugin host")
