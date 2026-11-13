"""Browser-only previews; all file reads retain the host artifact authorization."""

from pathlib import Path

from deerflow_extension_api import extension
from deerflow_extension_api.plugins import BrowserAssets, PluginContribution


@extension(api="0.2.3", name="office-preview")
def install(registry, config):
    enabled = config.get("enabled", True)
    if type(enabled) is not bool:
        raise ValueError("enabled must be a boolean")
    accepted = registry.plugin(
        PluginContribution(
            namespace="office-preview",
            title="Office preview / Office 文件预览",
            description="Read Excel, Word and PowerPoint files in the artifact panel.",
            enabled=enabled,
            frontend=BrowserAssets(module="office-preview", root=Path(__file__).parent),
        )
    )
    if not accepted:
        raise RuntimeError("This host does not support browser plugin contributions")
